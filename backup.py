#!/usr/bin/env python3
"""Versioned, local-first Penny backups.

The canonical database and the Penny-owned content-addressed object store are
the only inputs accepted here.  iCloud is a rebuildable mirror and is never a
backup source.  A backup set is published by writing a complete sibling
directory and renaming it only after the catalog is durable; a partially
written set therefore never looks like a restorable set to a verifier.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from archive import CHUNK_SIZE, fsync_directory, sha256_file


BACKUP_SCHEMA_VERSION = 1
BACKUP_RETENTION_DAYS = 90
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA256_PREFIX_RE = re.compile(r"^[0-9a-f]{2}$")
_OBJECT_NAME_RE = re.compile(r"^(?P<sha>[0-9a-f]{64})(?P<extension>\.[A-Za-z0-9]{1,10})?$")
_SET_ID_RE = re.compile(r"^\d{8}T\d{6}Z$")
_FORBIDDEN_CLOUD_PARTS = frozenset(
    {"Mobile Documents", "com~apple~CloudDocs", "iCloud Drive", "CloudDocs"}
)
_FORBIDDEN_CLOUD_XATTRS = frozenset(
    {
        "com.apple.fileprovider.provider-domain-id",
        "com.apple.fileprovider.fpfs#P",
        "com.apple.ubiquity",
        "com.apple.CloudDocs",
    }
)


class BackupError(RuntimeError):
    """A backup input, destination, or publication contract was unsafe."""


@dataclass(frozen=True)
class BackupReceipt:
    status: str
    backup_root: Path
    set_path: Path
    database_path: Path
    catalog_path: Path
    backup_set_id: str
    catalog_sha256: str
    object_count: int
    row_count: int
    max_transcript_id: int | None


@dataclass(frozen=True)
class VerificationReceipt:
    valid: bool
    status: str
    backup_set_id: str | None
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    row_count: int | None = None
    max_transcript_id: int | None = None


@dataclass(frozen=True)
class RetentionPlan:
    cutoff: str
    expired_set_ids: tuple[str, ...]
    retained_set_ids: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    deletes_objects: bool = False

    @property
    def sets_to_remove(self) -> tuple[str, ...]:
        """Compatibility name for operators reading the plan."""
        return self.expired_set_ids


def _utc(value: datetime | str | None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime | str | None) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _set_id(value: datetime | str | None) -> str:
    return _utc(value).strftime("%Y%m%dT%H%M%SZ")


def _safe_regular(path: Path, *, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise BackupError(f"{label}_unreadable") from exc
    if stat.S_ISLNK(info.st_mode):
        raise BackupError(f"{label}_symlink")
    if not stat.S_ISREG(info.st_mode):
        raise BackupError(f"{label}_not_regular")
    return info


def _safe_immutable_file(path: Path, *, label: str) -> os.stat_result:
    """Validate the immutable-file contract used by published backups."""
    info = _safe_regular(path, label=label)
    if info.st_nlink != 1:
        raise BackupError(f"{label}_hardlink")
    if stat.S_IMODE(info.st_mode) != 0o400:
        raise BackupError(f"{label}_mode_invalid")
    return info


def _reject_symlink_components(path: Path, *, label: str) -> None:
    """Reject symlinked components that could redirect a backup destination."""
    current = Path(path.anchor) if path.is_absolute() else Path()
    for part in path.parts[1:] if path.is_absolute() else path.parts:
        current = current / part
        try:
            if current.is_symlink():
                resolved = current.resolve(strict=True)
                # macOS exposes a few system aliases (`/var`, `/tmp`, and
                # `/etc`) as stable links into `/private`.  They cannot be
                # used to redirect a caller-selected backup path, so permit
                # only those exact, canonical aliases and continue checking
                # later components from the resolved directory.
                allowed_aliases = {
                    Path("/var"): Path("/private/var"),
                    Path("/tmp"): Path("/private/tmp"),
                    Path("/etc"): Path("/private/etc"),
                }
                if allowed_aliases.get(current) != resolved:
                    raise BackupError(f"{label}_symlink")
                current = resolved
        except OSError as exc:
            raise BackupError(f"{label}_unreadable") from exc


def _reject_cloud_root(path: Path) -> None:
    if any(part in _FORBIDDEN_CLOUD_PARTS for part in path.parts):
        raise BackupError("archive_root_must_be_local")


def _reject_cloud_placeholder(path: Path) -> None:
    try:
        names = set(os.listxattr(path))
    except (AttributeError, OSError):
        names = set()
    if names & _FORBIDDEN_CLOUD_XATTRS:
        raise BackupError("archive_object_not_materialized")


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise BackupError("catalog_path_invalid")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts or "." in candidate.parts:
        raise BackupError("catalog_path_invalid")
    normalized = candidate.as_posix()
    if normalized != value or normalized.startswith("/"):
        raise BackupError("catalog_path_invalid")
    return normalized


def _assert_inside(path: Path, root: Path, *, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise BackupError(f"{label}_outside_root") from exc


def _fsync_file(path: Path) -> None:
    with path.open("rb") as reader:
        os.fsync(reader.fileno())


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.partial")
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )
    try:
        with temporary.open("xb") as writer:
            os.chmod(temporary, 0o600)
            writer.write(payload)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o400)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _copy_immutable(source: Path, destination: Path, *, expected_sha: str, expected_size: int) -> None:
    source_info = _safe_regular(source, label="archive_object")
    _reject_cloud_placeholder(source)
    if source_info.st_size != expected_size or sha256_file(source) != expected_sha:
        raise BackupError("archive_object_hash_mismatch")
    if destination.exists() or destination.is_symlink():
        destination_info = _safe_regular(destination, label="backup_object")
        if destination_info.st_nlink != 1:
            raise BackupError("backup_object_hardlink")
        if destination_info.st_size != expected_size or sha256_file(destination) != expected_sha:
            raise BackupError("destination_hash_conflict")
        os.chmod(destination, 0o400)
        return

    _reject_symlink_components(destination.parent, label="backup_object")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination.parent, 0o700)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.partial")
    copied = 0
    digest = hashlib.sha256()
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            os.chmod(temporary, 0o600)
            for chunk in iter(lambda: reader.read(CHUNK_SIZE), b""):
                writer.write(chunk)
                digest.update(chunk)
                copied += len(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        if copied != expected_size or digest.hexdigest() != expected_sha:
            raise BackupError("archive_object_changed")
        os.replace(temporary, destination)
        os.chmod(destination, 0o400)
        fsync_directory(destination.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _archive_objects(archive_root: Path) -> list[tuple[str, Path, int, str]]:
    archive_root = Path(archive_root).expanduser()
    _reject_cloud_root(archive_root)
    _reject_symlink_components(archive_root, label="archive_root")
    if not archive_root.exists() and not archive_root.is_symlink():
        # A first backup may legitimately precede the first durable audio
        # object.  Treat a missing local object root as an empty authority;
        # callers still get a complete SQLite snapshot and catalog.
        return []
    if archive_root.is_symlink():
        raise BackupError("archive_root_symlink")
    if not archive_root.is_dir():
        raise BackupError("archive_root_not_directory")
    sha_root = archive_root / "sha256"
    if sha_root.exists() and sha_root.is_symlink():
        raise BackupError("archive_root_symlink")
    if not sha_root.exists():
        return []
    if not sha_root.is_dir():
        raise BackupError("archive_root_not_directory")

    objects: list[tuple[str, Path, int, str]] = []
    for path in sorted(sha_root.rglob("*"), key=lambda item: item.as_posix()):
        try:
            relative = path.relative_to(archive_root).as_posix()
        except ValueError as exc:
            raise BackupError("archive_object_path_invalid") from exc
        if path.is_symlink():
            raise BackupError("archive_object_symlink")
        if path.is_dir():
            continue
        info = _safe_regular(path, label="archive_object")
        if info.st_nlink != 1:
            raise BackupError("archive_object_hardlink")
        parts = relative.split("/")
        if len(parts) != 3 or parts[0] != "sha256" or not _SHA256_PREFIX_RE.fullmatch(parts[1]):
            raise BackupError("archive_object_path_invalid")
        match = _OBJECT_NAME_RE.fullmatch(parts[2])
        if match is None or match.group("sha")[:2] != parts[1]:
            raise BackupError("archive_object_path_invalid")
        _reject_cloud_placeholder(path)
        digest = sha256_file(path)
        if digest != match.group("sha"):
            raise BackupError("archive_object_hash_mismatch")
        objects.append((relative, path, info.st_size, digest))
    return objects


def _database_metadata(path: Path) -> dict[str, Any]:
    _safe_regular(path, label="database")
    uri = f"file:{path.resolve()}?mode=ro"
    try:
        source = sqlite3.connect(uri, uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        raise BackupError("database_unreadable") from exc
    try:
        source.row_factory = sqlite3.Row
        integrity = str(source.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = source.execute("PRAGMA foreign_key_check").fetchall()
        user_version = int(source.execute("PRAGMA user_version").fetchone()[0])
        row = source.execute("SELECT COUNT(*) AS count, MAX(id) AS max_id FROM transcripts").fetchone()
        schema_rows = source.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE type IN ('table', 'index', 'trigger', 'view') ORDER BY type, name"
        ).fetchall()
    except sqlite3.Error as exc:
        raise BackupError("database_schema_invalid") from exc
    finally:
        source.close()
    schema = [
        {
            "type": str(item["type"]),
            "name": str(item["name"]),
            "sql_sha256": hashlib.sha256(str(item["sql"] or "").encode("utf-8")).hexdigest(),
        }
        for item in schema_rows
    ]
    return {
        "path": path.name,
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "integrity": "ok" if integrity == "ok" else "failed",
        "foreign_key_violations": len(foreign_keys),
        "user_version": user_version,
        "schema": schema,
        "row_count": int(row["count"]),
        "max_transcript_id": None if row["max_id"] is None else int(row["max_id"]),
    }


def _snapshot_database(source_path: Path, destination: Path) -> dict[str, Any]:
    _safe_regular(source_path, label="database")
    source_uri = f"file:{source_path.resolve()}?mode=ro"
    source: sqlite3.Connection | None = None
    target: sqlite3.Connection | None = None
    try:
        source = sqlite3.connect(source_uri, uri=True, timeout=5.0)
        target = sqlite3.connect(str(destination), timeout=5.0)
        source.backup(target)
        target.commit()
    except sqlite3.Error as exc:
        raise BackupError("database_snapshot_failed") from exc
    finally:
        if target is not None:
            target.close()
        if source is not None:
            source.close()
    _fsync_file(destination)
    os.chmod(destination, 0o400)
    metadata = _database_metadata(destination)
    # Opening a WAL-mode snapshot for metadata can recreate transient journal
    # sidecars.  Remove them only after that read-only pass and before the
    # staging directory is published.
    for suffix in ("-wal", "-shm"):
        sidecar = destination.with_name(destination.name + suffix)
        if sidecar.is_symlink():
            raise BackupError("database_sidecar_symlink")
        sidecar.unlink(missing_ok=True)
    fsync_directory(destination.parent)
    if metadata["integrity"] != "ok" or metadata["foreign_key_violations"]:
        raise BackupError("database_snapshot_invalid")
    return metadata


def _catalog_files(
    *, database: dict[str, Any], objects: Iterable[tuple[str, Path, int, str]], set_id: str
) -> list[dict[str, Any]]:
    files = [
        {
            "path": f"sets/{set_id}/transcripts.db",
            "size": int(database["size"]),
            "sha256": str(database["sha256"]),
        }
    ]
    files.extend(
        {
            "path": f"objects/{relative.replace('\\\\', '/')}",
            "size": int(size),
            "sha256": digest,
        }
        for relative, _source, size, digest in objects
    )
    return files


def create_backup_set(
    db_path: Path,
    archive_root: Path,
    backup_root: Path,
    now: datetime | str | None = None,
) -> BackupReceipt:
    """Create and atomically publish one immutable backup set."""
    db_path = Path(db_path).expanduser()
    archive_root = Path(archive_root).expanduser()
    backup_root = Path(backup_root).expanduser()
    _reject_symlink_components(backup_root, label="backup_root")
    if not backup_root.is_absolute():
        backup_root = backup_root.resolve()
    if backup_root.exists() and backup_root.is_symlink():
        raise BackupError("backup_root_symlink")
    if backup_root.exists() and not backup_root.is_dir():
        raise BackupError("backup_root_not_directory")
    backup_root = backup_root.resolve()
    _safe_regular(db_path, label="database")
    _reject_cloud_root(archive_root)
    objects = _archive_objects(archive_root)
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup_root, 0o700)
    objects_root = backup_root / "objects" / "sha256"
    sets_root = backup_root / "sets"
    _reject_symlink_components(objects_root, label="backup_objects_root")
    _reject_symlink_components(sets_root, label="backup_sets_root")
    if (backup_root / "objects").is_symlink() or (backup_root / "sets").is_symlink():
        raise BackupError("backup_root_symlink")
    objects_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    sets_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if objects_root.is_symlink() or sets_root.is_symlink():
        raise BackupError("backup_root_symlink")
    if objects_root.exists() and not objects_root.is_dir():
        raise BackupError("objects_root_not_directory")
    if sets_root.exists() and not sets_root.is_dir():
        raise BackupError("sets_root_not_directory")
    os.chmod(objects_root, 0o700)
    os.chmod(sets_root, 0o700)

    for relative, source, size, digest in objects:
        destination = backup_root / "objects" / relative.removeprefix("sha256/")
        # The backup layout has objects/sha256/<prefix>/<hash><ext>.
        destination = backup_root / "objects" / relative
        _assert_inside(destination, backup_root, label="backup_object")
        _copy_immutable(source, destination, expected_sha=digest, expected_size=size)

    set_id = _set_id(now)
    final_set = sets_root / set_id
    if final_set.exists() or final_set.is_symlink():
        raise BackupError("backup_set_exists")
    staging = sets_root / f".{set_id}.{uuid.uuid4().hex}.partial"
    staging.mkdir(mode=0o700)
    os.chmod(staging, 0o700)
    try:
        database_path = staging / "transcripts.db"
        database = _snapshot_database(db_path, database_path)
        catalog = {
            "schema_version": BACKUP_SCHEMA_VERSION,
            "backup_set_id": set_id,
            "created_at": _utc_text(now),
            "database": database,
            "objects": [
                {
                    "path": f"objects/{relative.replace('\\\\', '/')}",
                    "size": size,
                    "sha256": digest,
                }
                for relative, _source, size, digest in objects
            ],
            "files": _catalog_files(database=database, objects=objects, set_id=set_id),
        }
        catalog_path = staging / "catalog.json"
        # Catalog is written last inside the staging directory.  No final set
        # path is visible until this operation and its directory fsync pass.
        _atomic_write_json(catalog_path, catalog)
        fsync_directory(staging)
        os.replace(staging, final_set)
        fsync_directory(sets_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    database_path = final_set / "transcripts.db"
    catalog_path = final_set / "catalog.json"
    catalog_sha = sha256_file(catalog_path)
    return BackupReceipt(
        status="created",
        backup_root=backup_root,
        set_path=final_set,
        database_path=database_path,
        catalog_path=catalog_path,
        backup_set_id=set_id,
        catalog_sha256=catalog_sha,
        object_count=len(objects),
        row_count=int(database["row_count"]),
        max_transcript_id=database["max_transcript_id"],
    )


def _safe_set_and_root(set_path: Path) -> tuple[Path, Path]:
    set_path = Path(set_path)
    if not set_path.is_absolute():
        raise BackupError("backup_set_path_must_be_absolute")
    _reject_symlink_components(set_path, label="backup_set_path")
    if set_path.is_symlink() or not set_path.is_dir():
        raise BackupError("backup_set_path_invalid")
    if not _SET_ID_RE.fullmatch(set_path.name) or set_path.parent.name != "sets":
        raise BackupError("backup_set_path_invalid")
    backup_root = set_path.parent.parent
    _reject_symlink_components(backup_root, label="backup_root")
    if backup_root.name == "" or backup_root.is_symlink():
        raise BackupError("backup_root_invalid")
    try:
        resolved_set = set_path.resolve(strict=True)
        resolved_root = backup_root.resolve(strict=True)
        resolved_set.relative_to(resolved_root / "sets")
    except (OSError, ValueError) as exc:
        raise BackupError("backup_set_path_invalid") from exc
    return resolved_set, resolved_root


def _safe_scratch(scratch_root: Path, set_path: Path, backup_root: Path) -> Path:
    scratch_root = Path(scratch_root)
    if not scratch_root.is_absolute():
        raise BackupError("scratch_path_must_be_absolute")
    if scratch_root.exists() and scratch_root.is_symlink():
        raise BackupError("scratch_path_symlink")
    live_root = Path("~/.penny").expanduser().resolve()
    try:
        scratch_resolved = scratch_root.resolve(strict=False)
        if scratch_resolved == live_root or live_root in scratch_resolved.parents:
            raise BackupError("scratch_path_live")
        if scratch_resolved == backup_root or backup_root in scratch_resolved.parents:
            raise BackupError("scratch_path_nested")
        if scratch_resolved == set_path or set_path in scratch_resolved.parents:
            raise BackupError("scratch_path_nested")
    except OSError as exc:
        raise BackupError("scratch_path_invalid") from exc
    scratch_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return scratch_root


def _catalog_entry_path(backup_root: Path, value: object) -> Path:
    relative = _safe_relative(value)
    candidate = backup_root / relative
    _assert_inside(candidate, backup_root, label="catalog_entry")
    # Check each path component without following links.  The catalog must
    # never make verification escape through a symlink.
    current = backup_root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise BackupError("catalog_entry_symlink")
    return candidate


def _catalog_size(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BackupError("catalog_size_invalid")
    return value


def _catalog_sha(value: object) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise BackupError("catalog_hash_invalid")
    return value


def _validate_extra_object(path: Path, backup_root: Path) -> None:
    """Validate an unlisted object in the shared immutable object pool."""
    relative = path.relative_to(backup_root).as_posix()
    parts = relative.split("/")
    if len(parts) != 4 or parts[:2] != ["objects", "sha256"]:
        raise BackupError("extra_object_path_invalid")
    prefix = parts[2]
    match = _OBJECT_NAME_RE.fullmatch(parts[3])
    if not _SHA256_PREFIX_RE.fullmatch(prefix) or match is None:
        raise BackupError("extra_object_path_invalid")
    digest = match.group("sha")
    if digest[:2] != prefix:
        raise BackupError("extra_object_path_invalid")
    info = _safe_immutable_file(path, label="extra_object")
    if sha256_file(path) != digest:
        raise BackupError("extra_object_hash_mismatch")
    if info.st_size <= 0:
        raise BackupError("extra_object_empty")


def _verify_database(path: Path, expected: dict[str, Any]) -> tuple[int, int | None]:
    _safe_immutable_file(path, label="snapshot")
    if path.stat().st_size != _catalog_size(expected.get("size")):
        raise BackupError("database_size_mismatch")
    if sha256_file(path) != _catalog_sha(expected.get("sha256")):
        raise BackupError("database_hash_mismatch")
    uri = f"file:{path.resolve()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.execute("PRAGMA query_only=ON")
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
        user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        row = conn.execute("SELECT COUNT(*), MAX(id) FROM transcripts").fetchone()
        schema_rows = conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE type IN ('table', 'index', 'trigger', 'view') ORDER BY type, name"
        ).fetchall()
    except sqlite3.Error as exc:
        raise BackupError("database_verification_failed") from exc
    finally:
        try:
            conn.close()
        except (NameError, UnboundLocalError):
            pass
    if integrity != "ok" or foreign_keys:
        raise BackupError("database_integrity_failed")
    expected_user_version = expected.get("user_version")
    if (
        isinstance(expected_user_version, bool)
        or not isinstance(expected_user_version, int)
        or user_version != expected_user_version
    ):
        raise BackupError("database_user_version_mismatch")
    actual_schema = [
        {
            "type": str(item[0]),
            "name": str(item[1]),
            "sql_sha256": hashlib.sha256(str(item[2] or "").encode("utf-8")).hexdigest(),
        }
        for item in schema_rows
    ]
    if actual_schema != expected.get("schema"):
        raise BackupError("database_schema_mismatch")
    expected_row_count = expected.get("row_count")
    if (
        isinstance(expected_row_count, bool)
        or not isinstance(expected_row_count, int)
        or int(row[0]) != expected_row_count
    ):
        raise BackupError("database_row_count_mismatch")
    expected_max = expected.get("max_transcript_id")
    if expected_max is not None and (
        isinstance(expected_max, bool) or not isinstance(expected_max, int)
    ):
        raise BackupError("database_max_id_invalid")
    actual_max = None if row[1] is None else int(row[1])
    if actual_max != expected_max:
        raise BackupError("database_max_id_mismatch")
    return int(row[0]), actual_max


def verify_backup_set(set_path: Path, scratch_root: Path) -> VerificationReceipt:
    """Verify one set using a private scratch restore and no live writes."""
    try:
        set_path, backup_root = _safe_set_and_root(Path(set_path))
        scratch_root = _safe_scratch(Path(scratch_root), set_path, backup_root)
    except BackupError:
        raise

    owned = scratch_root / f".penny-verify-{uuid.uuid4().hex}"
    owned.mkdir(mode=0o700)
    errors: list[str] = []
    warnings: list[str] = []
    row_count: int | None = None
    max_id: int | None = None
    backup_set_id: str | None = None
    try:
        catalog_path = set_path / "catalog.json"
        _safe_immutable_file(catalog_path, label="catalog")
        allowed_set_files = {"catalog.json", "transcripts.db"}
        for child in set_path.iterdir():
            if child.name not in allowed_set_files:
                raise BackupError("set_extra_file")
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise BackupError("catalog_invalid") from exc
        if not isinstance(catalog, dict) or catalog.get("schema_version") != BACKUP_SCHEMA_VERSION:
            raise BackupError("catalog_schema_invalid")
        backup_set_id = str(catalog.get("backup_set_id", ""))
        if backup_set_id != set_path.name or not _SET_ID_RE.fullmatch(backup_set_id):
            raise BackupError("catalog_set_id_invalid")
        files = catalog.get("files")
        if not isinstance(files, list) or not files:
            raise BackupError("catalog_files_invalid")
        expected_paths: set[str] = set()
        file_entries: dict[str, tuple[int, str]] = {}
        database_relative = f"sets/{set_path.name}/transcripts.db"
        for item in files:
            if not isinstance(item, dict):
                raise BackupError("catalog_entry_invalid")
            relative = _safe_relative(item.get("path"))
            if relative in expected_paths:
                raise BackupError("catalog_duplicate_path")
            if relative != database_relative and not relative.startswith("objects/sha256/"):
                raise BackupError("catalog_entry_scope_invalid")
            expected_paths.add(relative)
            candidate = _catalog_entry_path(backup_root, relative)
            info = _safe_immutable_file(candidate, label="catalog_entry")
            expected_size = _catalog_size(item.get("size"))
            expected_sha = _catalog_sha(item.get("sha256"))
            if info.st_size != expected_size or sha256_file(candidate) != expected_sha:
                raise BackupError("catalog_hash_mismatch")
            file_entries[relative] = (expected_size, expected_sha)

        database_meta = catalog.get("database")
        if not isinstance(database_meta, dict):
            raise BackupError("catalog_database_invalid")
        if database_meta.get("path") != "transcripts.db":
            raise BackupError("catalog_database_path_invalid")
        if database_relative not in file_entries:
            raise BackupError("catalog_database_missing")
        database_size = _catalog_size(database_meta.get("size"))
        database_sha = _catalog_sha(database_meta.get("sha256"))
        if file_entries[database_relative] != (database_size, database_sha):
            raise BackupError("catalog_database_mismatch")
        database_path = _catalog_entry_path(backup_root, database_relative)
        object_metadata = catalog.get("objects")
        if not isinstance(object_metadata, list):
            raise BackupError("catalog_objects_invalid")
        catalog_objects: dict[str, tuple[int, str]] = {}
        for item in object_metadata:
            if not isinstance(item, dict):
                raise BackupError("catalog_object_invalid")
            relative = _safe_relative(item.get("path"))
            if not relative.startswith("objects/sha256/"):
                raise BackupError("catalog_object_scope_invalid")
            if relative in catalog_objects:
                raise BackupError("catalog_duplicate_object")
            catalog_objects[relative] = (
                _catalog_size(item.get("size")),
                _catalog_sha(item.get("sha256")),
            )
        file_objects = {
            path: metadata
            for path, metadata in file_entries.items()
            if path.startswith("objects/sha256/")
        }
        if catalog_objects != file_objects:
            raise BackupError("catalog_objects_mismatch")
        scratch_db = owned / "transcripts.db"
        shutil.copyfile(database_path, scratch_db)
        os.chmod(scratch_db, 0o400)
        _fsync_file(scratch_db)
        row_count, max_id = _verify_database(scratch_db, database_meta)

        listed_objects = {
            path for path in expected_paths if path.startswith("objects/sha256/")
        }
        objects_root = backup_root / "objects"
        if objects_root.exists():
            if objects_root.is_symlink():
                raise BackupError("backup_object_symlink")
            for candidate in sorted(objects_root.rglob("*"), key=lambda item: item.as_posix()):
                if candidate.is_symlink():
                    raise BackupError("backup_object_symlink")
                if candidate.is_dir():
                    continue
                relative = candidate.relative_to(backup_root).as_posix()
                if relative not in listed_objects:
                    _validate_extra_object(candidate, backup_root)
                    # Objects are a shared immutable pool.  A valid physical
                    # object may be absent from this set's catalog because a
                    # later set references it; retain it and report the
                    # inventory difference without invalidating the set.
                    warnings.append("extra_object")

        return VerificationReceipt(
            valid=not errors,
            status="verified" if not errors else "invalid",
            backup_set_id=backup_set_id,
            errors=tuple(errors),
            warnings=tuple(sorted(set(warnings))),
            row_count=row_count,
            max_transcript_id=max_id,
        )
    except BackupError as exc:
        errors.append(str(exc))
        return VerificationReceipt(
            valid=False,
            status="invalid",
            backup_set_id=backup_set_id,
            errors=tuple(errors),
            warnings=tuple(sorted(set(warnings))),
            row_count=row_count,
            max_transcript_id=max_id,
        )
    except (TypeError, ValueError, OverflowError, KeyError, IndexError, OSError, sqlite3.Error):
        # A malformed or truncated catalog is an invalid backup, not an
        # operator path/usage error.  Keep the receipt and CLI output bounded.
        errors.append("catalog_invalid")
        return VerificationReceipt(
            valid=False,
            status="invalid",
            backup_set_id=backup_set_id,
            errors=tuple(errors),
            warnings=tuple(sorted(set(warnings))),
            row_count=row_count,
            max_transcript_id=max_id,
        )
    finally:
        # Remove only the verifier-owned temporary directory.  Caller data in
        # scratch_root is intentionally left untouched.
        if owned.parent == scratch_root and owned.name.startswith(".penny-verify-"):
            shutil.rmtree(owned, ignore_errors=True)


def plan_retention(
    backup_root: Path,
    now: datetime | str | None = None,
    retention_days: int = BACKUP_RETENTION_DAYS,
) -> RetentionPlan:
    """Return a deterministic deletion plan; this function never deletes."""
    backup_root = Path(backup_root).expanduser()
    if not backup_root.is_absolute():
        backup_root = backup_root.resolve()
    if retention_days < 1:
        raise ValueError("retention_days must be positive")
    cutoff_dt = _utc(now) - timedelta(days=retention_days)
    sets_root = backup_root / "sets"
    expired: list[str] = []
    retained: list[str] = []
    valid_expired: list[tuple[datetime, str]] = []
    warnings: list[str] = []
    if not sets_root.exists():
        return RetentionPlan(_utc_text(cutoff_dt), (), (), ())
    if sets_root.is_symlink() or not sets_root.is_dir():
        raise BackupError("sets_root_invalid")
    for candidate in sorted(sets_root.iterdir(), key=lambda item: item.name):
        if candidate.is_symlink():
            warnings.append("symlink_set_ignored")
            continue
        if not candidate.is_dir() or not _SET_ID_RE.fullmatch(candidate.name):
            warnings.append("invalid_set_ignored")
            continue
        try:
            created = datetime.strptime(candidate.name, "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            warnings.append("invalid_set_ignored")
            continue
        try:
            with tempfile.TemporaryDirectory(prefix="penny-retention-") as scratch:
                verification = verify_backup_set(candidate, Path(scratch))
        except (BackupError, OSError, ValueError, TypeError, OverflowError):
            verification = None
        if verification is None or not verification.valid:
            warnings.append("invalid_set_verification")
            continue
        if created < cutoff_dt:
            expired.append(candidate.name)
            valid_expired.append((created, candidate.name))
        else:
            retained.append(candidate.name)
    if not retained and valid_expired:
        # Never discard the only valid rollback point.  Preserve the newest
        # *verified* set; corrupt/unknown timestamps never enter this choice.
        _, newest = max(valid_expired)
        expired.remove(newest)
        retained.append(newest)
    return RetentionPlan(
        cutoff=_utc_text(cutoff_dt),
        expired_set_ids=tuple(expired),
        retained_set_ids=tuple(retained),
        warnings=tuple(sorted(set(warnings))),
        deletes_objects=False,
    )


def sqlite_integrity(path: Path) -> str:
    """Small read-only helper retained for operator/test callers."""
    _safe_regular(Path(path), label="database")
    conn = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        conn.close()


__all__ = [
    "BACKUP_RETENTION_DAYS",
    "BACKUP_SCHEMA_VERSION",
    "BackupError",
    "BackupReceipt",
    "RetentionPlan",
    "VerificationReceipt",
    "create_backup_set",
    "plan_retention",
    "sqlite_integrity",
    "verify_backup_set",
]
