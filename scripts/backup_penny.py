#!/usr/bin/env python3
"""Create and propagate one Penny backup set.

The command intentionally reports only bounded status and identifiers.  It
does not print transcript bodies, absolute paths, provider stderr, or secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from archive import sha256_file  # noqa: E402
from backup import (  # noqa: E402
    BACKUP_ALERT_NAME,
    BACKUP_RETAINED_SETS,
    DEFAULT_BACKUP_REMOTE,
    BackupError,
    BackupReceipt,
    _reject_symlink_components,
    apply_retention,
    create_backup_set,
    plan_retention,
    verify_backup_set,
)


DEFAULT_DB = Path("~/.penny/transcripts.db").expanduser()
DEFAULT_ARCHIVE_ROOT = Path("~/.penny/archive/objects").expanduser()
DEFAULT_BACKUP_ROOT = Path("~/.penny/backup").expanduser()
DEFAULT_SCRATCH_ROOT = Path("~/Library/Caches/Penny/backup-scratch").expanduser()
DEFAULT_REMOTE = DEFAULT_BACKUP_REMOTE
DEFAULT_VERIFICATION_RECEIPT = DEFAULT_BACKUP_ROOT / "last_verification.json"
_BACKUP_SET_ID_RE = re.compile(r"^\d{8}T\d{6}Z$")
_REMOTE_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_REMOTE_PATH_COMPONENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class SyncError(RuntimeError):
    """Remote backup propagation or catalog read-back failed."""


@dataclass(frozen=True)
class SyncReceipt:
    status: str
    remote: str
    catalog_verified: bool


def write_verification_receipt(
    path: Path,
    *,
    receipt: BackupReceipt,
    verification: Any,
    remote_catalog_verified: bool,
    verified_at: datetime | None = None,
) -> Path:
    """Atomically publish bounded metadata for the latest verified set.

    The receipt intentionally contains no filesystem paths, remote names,
    transcript text, audio metadata, or provider output.  A failed verify or
    sync must never call this function, so a prior good receipt remains intact.
    """

    if getattr(verification, "valid", None) is not True or remote_catalog_verified is not True:
        raise SyncError("verification_not_complete")
    set_id = str(getattr(verification, "backup_set_id", "") or receipt.backup_set_id)
    if set_id != receipt.backup_set_id or not _BACKUP_SET_ID_RE.fullmatch(set_id):
        raise SyncError("verification_set_mismatch")
    catalog_sha = str(receipt.catalog_sha256)
    if len(catalog_sha) != 64 or any(char not in "0123456789abcdef" for char in catalog_sha.lower()):
        raise SyncError("verification_catalog_hash_invalid")
    if verified_at is None:
        timestamp = datetime.now(timezone.utc)
    elif not isinstance(verified_at, datetime) or verified_at.tzinfo is None:
        raise SyncError("verification_timestamp_invalid")
    else:
        try:
            timestamp = verified_at.astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError) as exc:
            raise SyncError("verification_timestamp_invalid") from exc
    raw_max_id = getattr(verification, "max_transcript_id", receipt.max_transcript_id)
    raw_row_count = getattr(verification, "row_count", receipt.row_count)
    try:
        if isinstance(raw_max_id, bool) or (raw_max_id is not None and int(raw_max_id) < 0):
            raise ValueError("max_transcript_id")
        max_id = None if raw_max_id is None else int(raw_max_id)
        if isinstance(raw_row_count, bool):
            raise ValueError("row_count")
        row_count = int(raw_row_count)
        if row_count < 0:
            raise ValueError("row_count")
    except (TypeError, ValueError, OverflowError) as exc:
        raise SyncError("verification_metadata_invalid") from exc
    payload = {
        "schema_version": 1,
        "status": "verified",
        "valid": True,
        "backup_set_id": set_id,
        "catalog_sha256": catalog_sha,
        "row_count": row_count,
        "max_transcript_id": max_id,
        "verified_at": timestamp.isoformat().replace("+00:00", "Z"),
        "remote_catalog_verified": True,
    }
    destination = Path(path).expanduser()
    try:
        _reject_symlink_components(destination.absolute(), label="verification_receipt")
    except BackupError as exc:
        raise SyncError("verification_receipt_symlink") from exc
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        _reject_symlink_components(destination.absolute(), label="verification_receipt")
    except BackupError as exc:
        raise SyncError("verification_receipt_symlink") from exc
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".partial",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return destination
    except (OSError, TypeError, ValueError) as exc:
        raise SyncError("verification_receipt_write_failed") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _safe_remote(value: str) -> tuple[str, str]:
    remote = str(value or "").strip()
    if not remote or ":" not in remote:
        raise SyncError("remote_invalid")
    host, root = remote.split(":", 1)
    if not _REMOTE_HOST_RE.fullmatch(host) or not root:
        raise SyncError("remote_invalid")
    if root.startswith("~/"):
        path = root[2:]
    elif root.startswith("/"):
        path = root[1:]
    else:
        raise SyncError("remote_invalid")
    path = path[:-1] if path.endswith("/") else path
    components = path.split("/")
    if not path or any(
        not component
        or component in {".", ".."}
        or not _REMOTE_PATH_COMPONENT_RE.fullmatch(component)
        for component in components
    ):
        raise SyncError("remote_invalid")
    return host, root.rstrip("/") + "/"


def _result_ok(result: Any) -> bool:
    try:
        return int(result.returncode) == 0
    except (AttributeError, TypeError, ValueError):
        return False


def _remote_catalog_path(remote_root: str, set_id: str) -> str:
    # `remote_root` is already operator-supplied and validated for control
    # characters; quote only for the remote command argument boundary.
    return f"{remote_root}sets/{set_id}/catalog.json"


def sync_backup_set(
    receipt: BackupReceipt,
    remote: str = DEFAULT_REMOTE,
    *,
    runner: Callable[..., Any] | None = None,
) -> SyncReceipt:
    """Rsync immutable objects/set and verify the remote catalog hash."""
    host, remote_root = _safe_remote(remote)
    _reject_boot_disk(remote_root)
    if runner is None:
        runner = subprocess.run
    _assert_remote_mount(host, remote_root, runner)
    objects_source = str(receipt.backup_root / "objects") + "/"
    set_source = str(receipt.set_path) + "/"
    try:
        prepared = runner(
            [
                "ssh",
                host,
                "mkdir",
                "-p",
                "--",
                f"{remote_root}objects",
                f"{remote_root}sets",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SyncError("remote_prepare_failed") from exc
    if not _result_ok(prepared):
        raise SyncError("remote_prepare_failed")
    commands: list[Sequence[str]] = [
        (
            "rsync",
            "--archive",
            "--checksum",
            "--",
            objects_source,
            f"{host}:{remote_root}objects/",
        ),
        (
            "rsync",
            "--archive",
            "--checksum",
            "--",
            set_source,
            f"{host}:{remote_root}sets/{receipt.backup_set_id}/",
        ),
    ]
    for command in commands:
        try:
            result = runner(
                list(command),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SyncError("rsync_failed") from exc
        if not _result_ok(result):
            raise SyncError("rsync_failed")

    remote_catalog = _remote_catalog_path(remote_root, receipt.backup_set_id)
    try:
        result = runner(
            ["ssh", host, "sha256sum", "--", remote_catalog],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SyncError("remote_catalog_verification_failed") from exc
    if not _result_ok(result):
        raise SyncError("remote_catalog_verification_failed")
    try:
        observed = str(result.stdout or "").strip().split()[0]
    except (IndexError, AttributeError):
        observed = ""
    if observed != receipt.catalog_sha256:
        raise SyncError("remote_catalog_mismatch")
    return SyncReceipt(status="synced", remote=host, catalog_verified=True)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("PENNY_TRANSCRIPT_DB", DEFAULT_DB)))
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=Path(os.environ.get("PENNY_ARCHIVE_OBJECT_ROOT", DEFAULT_ARCHIVE_ROOT)),
    )
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=Path(os.environ.get("PENNY_BACKUP_ROOT", DEFAULT_BACKUP_ROOT)),
    )
    parser.add_argument("--remote", default=os.environ.get("PENNY_BACKUP_REMOTE", DEFAULT_REMOTE))
    parser.add_argument("--now", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--verify-latest", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--skip-export", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--verification-receipt",
        type=Path,
        default=Path(os.environ.get("PENNY_BACKUP_VERIFICATION_RECEIPT", DEFAULT_VERIFICATION_RECEIPT)),
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def _run_export(remote: str) -> None:
    try:
        import export_transcripts

        records = export_transcripts.dump_transcripts()
        export_transcripts.export_json(records)
        if not export_transcripts.rsync_to_homelab(remote):
            raise SyncError("export_sync_failed")
    except SyncError:
        raise
    except (OSError, RuntimeError, ValueError, SystemExit) as exc:
        raise SyncError("export_failed") from exc


def _reject_boot_disk(root: str) -> None:
    """Home and root paths on the homelab land on the boot SSD."""
    if (
        root.startswith("~/")
        or root.startswith("/home/")
        or root.startswith("/root/")
        or root in {"/", "/home", "/home/", "/root", "/root/"}
    ):
        raise SyncError("remote_on_boot_disk")


def _remote_mount_anchor(root: str) -> str:
    parts = [part for part in root.strip("/").split("/") if part]
    if root.startswith("~/") or len(parts) < 2:
        raise SyncError("remote_invalid")
    return f"/{parts[0]}/{parts[1]}"


def _assert_remote_mount(host: str, root: str, runner: Callable[..., Any]) -> None:
    """Refuse a destination whose anchor is missing or mounted on `/`."""
    anchor = _remote_mount_anchor(root)
    try:
        result = runner(
            ["ssh", host, "findmnt", "-n", "-o", "TARGET", "-T", anchor],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SyncError("remote_disk_unavailable") from exc
    if not _result_ok(result):
        raise SyncError("remote_disk_unavailable")
    try:
        target = str(result.stdout or "").strip().splitlines()[0]
    except IndexError:
        target = ""
    if not target.startswith("/") or target == "/":
        raise SyncError("remote_on_boot_disk")


def _alert_path(receipt_path: Path) -> Path:
    return Path(receipt_path).expanduser().with_name(BACKUP_ALERT_NAME)


def write_backup_alert(path: Path, *, observed_at: datetime | None = None) -> Path:
    """Record a metadata-only failure without advancing the good receipt."""
    timestamp = observed_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise SyncError("verification_timestamp_invalid")
    payload = {
        "schema_version": 1,
        "status": "failed",
        "reason": "backup_verification_failed",
        "observed_at": timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    destination = Path(path).expanduser()
    try:
        _reject_symlink_components(destination.absolute(), label="backup_alert")
    except BackupError as exc:
        raise SyncError("backup_alert_symlink") from exc
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".partial",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
        return destination
    except (OSError, TypeError, ValueError) as exc:
        raise SyncError("backup_alert_write_failed") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def clear_backup_alert(path: Path) -> None:
    destination = Path(path).expanduser()
    if destination.is_symlink():
        raise SyncError("backup_alert_symlink")
    destination.unlink(missing_ok=True)


def _latest_set(backup_root: Path) -> Path | None:
    sets_root = Path(backup_root).expanduser() / "sets"
    if sets_root.is_symlink() or not sets_root.is_dir():
        return None
    names = sorted(
        entry.name
        for entry in sets_root.iterdir()
        if entry.is_dir() and not entry.is_symlink() and _BACKUP_SET_ID_RE.fullmatch(entry.name)
    )
    if not names:
        return None
    return sets_root / names[-1]


def remote_catalog_sha(
    remote: str,
    set_id: str,
    *,
    runner: Callable[..., Any] | None = None,
) -> str:
    if not _BACKUP_SET_ID_RE.fullmatch(set_id):
        raise SyncError("verification_set_mismatch")
    host, remote_root = _safe_remote(remote)
    _reject_boot_disk(remote_root)
    if runner is None:
        runner = subprocess.run
    _assert_remote_mount(host, remote_root, runner)
    try:
        result = runner(
            ["ssh", host, "sha256sum", "--", f"{remote_root}sets/{set_id}/catalog.json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SyncError("remote_catalog_verification_failed") from exc
    if not _result_ok(result):
        raise SyncError("remote_catalog_verification_failed")
    try:
        return str(result.stdout or "").strip().split()[0]
    except IndexError as exc:
        raise SyncError("remote_catalog_verification_failed") from exc


def prune_remote_sets(
    remote: str,
    *,
    verified_set_id: str,
    retain: int = BACKUP_RETAINED_SETS,
    runner: Callable[..., Any] | None = None,
) -> tuple[str, ...]:
    """Remove remote set directories beyond the newest verified keepers.

    Runs only after the keeper set has been verified. Does not touch objects.
    """
    if isinstance(retain, bool) or not isinstance(retain, int) or retain < 1:
        raise SyncError("remote_prune_refused")
    if not _BACKUP_SET_ID_RE.fullmatch(verified_set_id):
        raise SyncError("remote_prune_refused")
    host, remote_root = _safe_remote(remote)
    _reject_boot_disk(remote_root)
    if runner is None:
        runner = subprocess.run
    _assert_remote_mount(host, remote_root, runner)
    try:
        listed = runner(
            ["ssh", host, "ls", "-1", "--", f"{remote_root}sets"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SyncError("remote_prune_failed") from exc
    if not _result_ok(listed):
        raise SyncError("remote_prune_failed")
    ids = sorted(
        line
        for line in str(listed.stdout or "").splitlines()
        if _BACKUP_SET_ID_RE.fullmatch(line)
    )
    if verified_set_id not in ids or verified_set_id not in set(ids[-retain:]):
        raise SyncError("remote_prune_refused")
    removed: list[str] = []
    for set_id in ids:
        if set_id in set(ids[-retain:]):
            continue
        target = f"{remote_root}sets/{set_id}"
        if "/objects" in target or not target.endswith(f"/sets/{set_id}"):
            raise SyncError("remote_prune_refused")
        try:
            result = runner(
                ["ssh", host, "rm", "-rf", "--", target],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SyncError("remote_prune_failed") from exc
        if not _result_ok(result):
            raise SyncError("remote_prune_failed")
        removed.append(set_id)
    return tuple(removed)


def _refresh_latest_verification(args: argparse.Namespace) -> BackupReceipt:
    latest = _latest_set(args.backup_root)
    if latest is None:
        raise SyncError("scheduled_verification_missing")
    scratch_root = Path(
        os.environ.get("PENNY_BACKUP_SCRATCH_ROOT", str(DEFAULT_SCRATCH_ROOT))
    ).expanduser()
    verification = verify_backup_set(latest, scratch_root)
    if not verification.valid:
        raise SyncError("scheduled_verification_failed")
    catalog_sha = sha256_file(latest / "catalog.json")
    observed = remote_catalog_sha(args.remote, latest.name)
    if observed != catalog_sha:
        raise SyncError("remote_catalog_mismatch")
    receipt = BackupReceipt(
        status="verified",
        backup_root=Path(args.backup_root),
        set_path=latest,
        database_path=latest / "transcripts.db",
        catalog_path=latest / "catalog.json",
        backup_set_id=latest.name,
        catalog_sha256=catalog_sha,
        object_count=0,
        row_count=int(verification.row_count or 0),
        max_transcript_id=verification.max_transcript_id,
    )
    write_verification_receipt(
        args.verification_receipt,
        receipt=receipt,
        verification=verification,
        remote_catalog_verified=True,
    )
    clear_backup_alert(_alert_path(args.verification_receipt))
    return receipt


def _retain_local_sets(args: argparse.Namespace, verified_set_id: str) -> None:
    plan = plan_retention(args.backup_root, args.now)
    if verified_set_id not in plan.retained_set_ids:
        raise SyncError("retention_refused")
    apply_retention(args.backup_root, plan)



def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    alert = _alert_path(args.verification_receipt)
    try:
        host, remote_root = _safe_remote(args.remote)
        _reject_boot_disk(remote_root)
        del host
        if args.verify_latest:
            receipt = _refresh_latest_verification(args)
            print(f"penny backup {receipt.backup_set_id} verified")
            return 0
        try:
            _refresh_latest_verification(args)
        except SyncError as exc:
            if str(exc) != "scheduled_verification_missing":
                write_backup_alert(alert)
        receipt = create_backup_set(args.db, args.archive_root, args.backup_root, args.now)
        scratch_root = Path(
            os.environ.get("PENNY_BACKUP_SCRATCH_ROOT", str(DEFAULT_SCRATCH_ROOT))
        ).expanduser()
        verification = verify_backup_set(receipt.set_path, scratch_root)
        if not verification.valid:
            raise SyncError("local_backup_verification_failed")
        _retain_local_sets(args, receipt.backup_set_id)
        sync = sync_backup_set(receipt, args.remote)
        write_verification_receipt(
            args.verification_receipt,
            receipt=receipt,
            verification=verification,
            remote_catalog_verified=sync.catalog_verified,
        )
        clear_backup_alert(alert)
        prune_remote_sets(args.remote, verified_set_id=receipt.backup_set_id)
        if not args.skip_export:
            _run_export(args.remote)
    except (BackupError, SyncError, OSError, ValueError):
        try:
            write_backup_alert(alert)
        except SyncError:
            pass
        # Keep command output bounded and free of paths/provider details.
        print("penny backup failed", file=sys.stderr)
        return 1
    print(f"penny backup {receipt.backup_set_id} synced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
