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

from backup import BackupError, BackupReceipt, create_backup_set, verify_backup_set  # noqa: E402


DEFAULT_DB = Path("~/.penny/transcripts.db").expanduser()
DEFAULT_ARCHIVE_ROOT = Path("~/.penny/archive/objects").expanduser()
DEFAULT_BACKUP_ROOT = Path("~/.penny/backup").expanduser()
DEFAULT_REMOTE = "homelab:~/backups/penny/"
DEFAULT_VERIFICATION_RECEIPT = DEFAULT_BACKUP_ROOT / "last_verification.json"
_BACKUP_SET_ID_RE = re.compile(r"^\d{8}T\d{6}Z$")


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

    if not getattr(verification, "valid", False) or not remote_catalog_verified:
        raise SyncError("verification_not_complete")
    set_id = str(getattr(verification, "backup_set_id", "") or receipt.backup_set_id)
    if set_id != receipt.backup_set_id or not _BACKUP_SET_ID_RE.fullmatch(set_id):
        raise SyncError("verification_set_mismatch")
    catalog_sha = str(receipt.catalog_sha256)
    if len(catalog_sha) != 64 or any(char not in "0123456789abcdef" for char in catalog_sha.lower()):
        raise SyncError("verification_catalog_hash_invalid")
    timestamp = (verified_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    raw_max_id = getattr(verification, "max_transcript_id", receipt.max_transcript_id)
    try:
        max_id = None if raw_max_id is None else int(raw_max_id)
        row_count = int(getattr(verification, "row_count", receipt.row_count) or 0)
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
    if destination.is_symlink():
        raise SyncError("verification_receipt_symlink")
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
        raise SyncError("verification_receipt_write_failed") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _safe_remote(value: str) -> tuple[str, str]:
    remote = str(value or "").strip()
    if not remote or ":" not in remote:
        raise SyncError("remote_invalid")
    host, root = remote.split(":", 1)
    if not host or not root or any(char in host for char in " /\\\n\t"):
        raise SyncError("remote_invalid")
    if "\n" in root or "\r" in root or any(char in root for char in ";|&$`'\""):
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
    if runner is None:
        runner = subprocess.run
    objects_source = str(receipt.backup_root / "objects") + "/"
    set_source = str(receipt.set_path) + "/"
    commands: list[Sequence[str]] = [
        (
            "rsync",
            "--archive",
            "--checksum",
            "--protect-args",
            objects_source,
            f"{host}:{remote_root}objects/",
        ),
        (
            "rsync",
            "--archive",
            "--checksum",
            "--protect-args",
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
    parser.add_argument("--skip-export", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--verification-receipt",
        type=Path,
        default=Path(os.environ.get("PENNY_BACKUP_VERIFICATION_RECEIPT", DEFAULT_VERIFICATION_RECEIPT)),
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def _run_export() -> None:
    try:
        import export_transcripts

        records = export_transcripts.dump_transcripts()
        export_transcripts.export_json(records)
        if not export_transcripts.rsync_to_homelab():
            raise SyncError("export_sync_failed")
    except SyncError:
        raise
    except (OSError, RuntimeError, ValueError, SystemExit) as exc:
        raise SyncError("export_failed") from exc


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        receipt = create_backup_set(args.db, args.archive_root, args.backup_root, args.now)
        scratch_root = Path(
            os.environ.get("PENNY_BACKUP_SCRATCH_ROOT", "~/.penny/backup-scratch")
        ).expanduser()
        verification = verify_backup_set(receipt.set_path, scratch_root)
        if not verification.valid:
            raise SyncError("local_backup_verification_failed")
        sync = sync_backup_set(receipt, args.remote)
        write_verification_receipt(
            args.verification_receipt,
            receipt=receipt,
            verification=verification,
            remote_catalog_verified=sync.catalog_verified,
        )
        if not args.skip_export:
            _run_export()
    except (BackupError, SyncError, OSError, ValueError):
        # Keep command output bounded and free of paths/provider details.
        print("penny backup failed", file=sys.stderr)
        return 1
    print(f"penny backup {receipt.backup_set_id} synced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
