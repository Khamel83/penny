#!/usr/bin/env python3
"""Penny-owned immutable audio objects and manifest-last iCloud publication."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

CHUNK_SIZE = 1024 * 1024
ARCHIVE_SCHEMA_VERSION = 1


class SourceChangedError(RuntimeError):
    """The source changed while Penny was making its durable copy."""


class ArchivePublishError(RuntimeError):
    """Archive publication failed without producing an acceptable manifest."""


@dataclass(frozen=True)
class StagedAudio:
    path: Path
    audio_sha256: str
    byte_length: int
    extension: str


@dataclass(frozen=True)
class ArchiveReceipt:
    status: str
    audio_path: Path
    markdown_path: Path
    manifest_path: Path
    receipt_sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        for chunk in iter(lambda: reader.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _mkdir_private(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


def _safe_original_name(value: str | None, fallback: str) -> str:
    name = str(value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."}:
        name = fallback
    return name[:255]


def _source_signature_from_stat(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino


def _open_source_nofollow(path: Path) -> int:
    """Open one regular source without following its final path component."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SourceChangedError("source_unavailable") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise SourceChangedError("source_unavailable")
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def stage_audio(source: Path, object_root: Path) -> StagedAudio:
    """Stream a stable source into a content-addressed Penny-owned object."""
    source = Path(source)
    object_root = Path(object_root)
    extension = source.suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", extension):
        raise ValueError("unsafe_audio_extension")
    descriptor = _open_source_nofollow(source)
    try:
        before = _source_signature_from_stat(os.fstat(descriptor))
        if before[0] <= 0:
            raise SourceChangedError(source.name)
        _mkdir_private(object_root)
    except Exception:
        os.close(descriptor)
        raise
    temporary = object_root / f".{uuid.uuid4().hex}.partial"
    digest = hashlib.sha256()
    copied = 0
    try:
        with os.fdopen(descriptor, "rb") as reader, temporary.open("xb") as writer:
            os.chmod(temporary, 0o600)
            for chunk in iter(lambda: reader.read(CHUNK_SIZE), b""):
                digest.update(chunk)
                copied += len(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
            after = _source_signature_from_stat(os.fstat(reader.fileno()))
        if before != after or copied != before[0] or temporary.stat().st_size != before[0]:
            raise SourceChangedError(source.name)

        audio_sha256 = digest.hexdigest()
        destination_dir = object_root / "sha256" / audio_sha256[:2]
        _mkdir_private(destination_dir)
        destination = destination_dir / f"{audio_sha256}{extension}"
        if destination.exists():
            if destination.stat().st_size != copied or sha256_file(destination) != audio_sha256:
                raise ArchivePublishError("local_object_hash_mismatch")
            os.chmod(destination, 0o400)
        else:
            os.replace(temporary, destination)
            os.chmod(destination, 0o400)
            fsync_directory(destination_dir)
        return StagedAudio(destination, audio_sha256, copied, extension)
    finally:
        temporary.unlink(missing_ok=True)


def _parse_utc(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_source(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return (safe or "unknown")[:64]


def _write_atomic(
    destination: Path,
    content: bytes,
    *,
    expected_sha256: str,
    on_replace: Callable[[Path], None] | None,
) -> None:
    if destination.exists():
        if sha256_file(destination) == expected_sha256:
            os.chmod(destination, 0o400)
            return
        raise ArchivePublishError("destination_hash_conflict")
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.partial")
    try:
        with temporary.open("xb") as writer:
            os.chmod(temporary, 0o600)
            writer.write(content)
            writer.flush()
            os.fsync(writer.fileno())
        if on_replace is not None:
            on_replace(destination)
        os.replace(temporary, destination)
        os.chmod(destination, 0o400)
        fsync_directory(destination.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _copy_atomic(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str,
    expected_size: int,
    on_replace: Callable[[Path], None] | None,
) -> None:
    if destination.exists():
        if (
            destination.stat().st_size == expected_size
            and sha256_file(destination) == expected_sha256
        ):
            os.chmod(destination, 0o400)
            return
        raise ArchivePublishError("destination_hash_conflict")
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.partial")
    digest = hashlib.sha256()
    copied = 0
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            os.chmod(temporary, 0o600)
            for chunk in iter(lambda: reader.read(CHUNK_SIZE), b""):
                digest.update(chunk)
                copied += len(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        if copied != expected_size or digest.hexdigest() != expected_sha256:
            raise ArchivePublishError("local_object_changed_during_publish")
        if on_replace is not None:
            on_replace(destination)
        os.replace(temporary, destination)
        os.chmod(destination, 0o400)
        fsync_directory(destination.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _markdown_bytes(
    *,
    transcript_id: int,
    source: str,
    captured_at: str,
    transcript: str,
    audio_sha256: str,
    transcript_sha256: str,
    backend: str | None,
    model: str | None,
    quality_status: str,
) -> bytes:
    header = (
        "---\n"
        f"schema_version: {ARCHIVE_SCHEMA_VERSION}\n"
        f"canonical_transcript_id: {transcript_id}\n"
        f"source: {json.dumps(source, ensure_ascii=False)}\n"
        f"captured_at: {json.dumps(captured_at)}\n"
        f"audio_sha256: {audio_sha256}\n"
        f"transcript_sha256: {transcript_sha256}\n"
        f"transcription_backend: {json.dumps(backend)}\n"
        f"transcription_model: {json.dumps(model)}\n"
        f"quality_status: {json.dumps(quality_status)}\n"
        "---\n"
    )
    return header.encode("utf-8") + transcript.encode("utf-8")


def publish_archive(
    *,
    staged: StagedAudio,
    transcript_id: int,
    transcript: str,
    source: str,
    captured_at: str | datetime | None,
    mirror_root: Path,
    source_aliases: Iterable[str] = (),
    original_name: str | None = None,
    ingested_at: str | datetime | None = None,
    duration_seconds: float | None = None,
    mime_type: str | None = None,
    backend: str | None = None,
    model: str | None = None,
    quality_status: str | None = None,
    publication_generation: int = 1,
    alias_set_sha256: str | None = None,
    on_replace: Callable[[Path], None] | None = None,
) -> ArchiveReceipt:
    """Publish audio and Markdown atomically, then expose the JSON manifest last."""
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", staged.extension):
        raise ArchivePublishError("unsafe_audio_extension")
    if staged.path.stat().st_size != staged.byte_length:
        raise ArchivePublishError("local_object_size_mismatch")
    if sha256_file(staged.path) != staged.audio_sha256:
        raise ArchivePublishError("local_object_hash_mismatch")

    captured = _parse_utc(captured_at)
    captured_text = captured.isoformat().replace("+00:00", "Z")
    ingested_text = _parse_utc(ingested_at).isoformat().replace("+00:00", "Z")
    day_dir = Path(mirror_root) / captured.strftime("%Y") / captured.strftime("%Y-%m") / captured.strftime("%Y-%m-%d")
    _mkdir_private(day_dir)
    basename = (
        f"{captured.strftime('%Y-%m-%dT%H-%M-%SZ')}__p{transcript_id:08d}__"
        f"{_safe_source(source)}__{staged.audio_sha256[:12]}"
    )
    audio_path = day_dir / f"{basename}{staged.extension}"
    markdown_path = day_dir / f"{basename}.md"
    manifest_path = day_dir / f"{basename}.json"
    transcript_sha256 = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    normalized_quality = quality_status or "unknown"
    markdown = _markdown_bytes(
        transcript_id=transcript_id,
        source=source,
        captured_at=captured_text,
        transcript=transcript,
        audio_sha256=staged.audio_sha256,
        transcript_sha256=transcript_sha256,
        backend=backend,
        model=model,
        quality_status=normalized_quality,
    )
    markdown_sha256 = hashlib.sha256(markdown).hexdigest()
    aliases = sorted({str(alias) for alias in source_aliases if str(alias)} | {source})
    aliases_json = json.dumps(aliases, separators=(",", ":"), ensure_ascii=False)
    computed_alias_hash = hashlib.sha256(aliases_json.encode("utf-8")).hexdigest()
    if alias_set_sha256 is not None and alias_set_sha256 != computed_alias_hash:
        raise ArchivePublishError("alias_set_hash_mismatch")
    alias_set_sha256 = computed_alias_hash
    basename = f"{basename}__g{publication_generation:04d}__a{alias_set_sha256[:12]}"
    audio_path = day_dir / f"{basename}{staged.extension}"
    markdown_path = day_dir / f"{basename}.md"
    manifest_path = day_dir / f"{basename}.json"
    manifest: dict[str, Any] = {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "canonical_transcript_id": transcript_id,
        "source": source,
        "source_aliases": aliases,
        "alias_set_sha256": alias_set_sha256,
        "publication_generation": publication_generation,
        "publication_scope": "local_mirror",
        "original_name": _safe_original_name(original_name, staged.path.name),
        "recorded_at": captured_text,
        "ingested_at": ingested_text,
        "duration_seconds": duration_seconds,
        "mime_type": mime_type or mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream",
        "byte_length": staged.byte_length,
        "audio_sha256": staged.audio_sha256,
        "transcript_sha256": transcript_sha256,
        "markdown_sha256": markdown_sha256,
        "transcription_backend": backend,
        "transcription_model": model,
        "quality_status": normalized_quality,
        "audio_file": audio_path.name,
        "markdown_file": markdown_path.name,
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    try:
        _copy_atomic(
            staged.path,
            audio_path,
            expected_sha256=staged.audio_sha256,
            expected_size=staged.byte_length,
            on_replace=on_replace,
        )
        _write_atomic(
            markdown_path,
            markdown,
            expected_sha256=markdown_sha256,
            on_replace=on_replace,
        )
        _write_atomic(
            manifest_path,
            manifest_bytes,
            expected_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            on_replace=on_replace,
        )
    except ArchivePublishError:
        raise
    except Exception as exc:
        raise ArchivePublishError(type(exc).__name__) from exc
    if not validate_archive(manifest_path):
        manifest_path.unlink(missing_ok=True)
        fsync_directory(manifest_path.parent)
        raise ArchivePublishError("published_archive_validation_failed")
    return ArchiveReceipt(
        "published",
        audio_path,
        markdown_path,
        manifest_path,
        sha256_file(manifest_path),
    )


def validate_archive(manifest_path: Path) -> bool:
    """Consumer gate: accept only a complete trio with every required hash."""
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        required = {
            "audio_sha256",
            "transcript_sha256",
            "markdown_sha256",
            "audio_file",
            "markdown_file",
            "byte_length",
        }
        if not required.issubset(manifest):
            return False
        parent = Path(manifest_path).parent
        audio_name = str(manifest["audio_file"])
        markdown_name = str(manifest["markdown_file"])
        if Path(audio_name).name != audio_name or Path(markdown_name).name != markdown_name:
            return False
        audio_path = parent / audio_name
        markdown_path = parent / markdown_name
        if not audio_path.exists() or not markdown_path.exists():
            return False
        if audio_path.stem != Path(manifest_path).stem or markdown_path.stem != Path(manifest_path).stem:
            return False
        if audio_path.stat().st_size != int(manifest["byte_length"]):
            return False
        if audio_path.stat().st_size <= 0:
            return False
        if sha256_file(audio_path) != manifest["audio_sha256"]:
            return False
        markdown = markdown_path.read_bytes()
        if hashlib.sha256(markdown).hexdigest() != manifest["markdown_sha256"]:
            return False
        separator = b"---\n"
        if not markdown.startswith(separator):
            return False
        closing = markdown.find(separator, len(separator))
        if closing < 0:
            return False
        transcript = markdown[closing + len(separator):]
        return hashlib.sha256(transcript).hexdigest() == manifest["transcript_sha256"]
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def validate_local_mirror_receipt(row: dict[str, Any]) -> bool:
    """Bind a valid local trio to the canonical delivery generation and receipt."""
    try:
        manifest_path = Path(str(row["destination_manifest_path"]))
        if not validate_archive(manifest_path):
            return False
        if sha256_file(manifest_path) != str(row["receipt_sha256"]):
            return False
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return (
            manifest.get("canonical_transcript_id")
            == int(row["transcript_row_id"])
            and manifest.get("publication_generation")
            == int(row["publication_generation"])
            and manifest.get("alias_set_sha256") == row["alias_set_sha256"]
            and manifest.get("publication_scope") == "local_mirror"
            and row.get("publication_scope") == "local_mirror"
        )
    except (KeyError, OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def preserve_invalid_local_mirror(
    row: dict[str, Any], mirror_root: Path
) -> list[Path]:
    """Move conflicting local-mirror material into a private recoverable area."""
    root = Path(mirror_root).resolve()
    conflict_dir = (
        root
        / ".penny-conflicts"
        / f"p{int(row['transcript_row_id']):08d}"
        / f"g{int(row.get('publication_generation') or 1):04d}-{uuid.uuid4().hex}"
    )
    moved: list[Path] = []
    for key in (
        "destination_audio_path",
        "destination_markdown_path",
        "destination_manifest_path",
    ):
        raw_path = row.get(key)
        if not raw_path:
            continue
        source = Path(str(raw_path))
        resolved = source.resolve()
        if not resolved.is_relative_to(root):
            raise ArchivePublishError("local_mirror_path_outside_root")
        if not source.exists():
            continue
        _mkdir_private(conflict_dir)
        destination = conflict_dir / source.name
        os.replace(source, destination)
        fsync_directory(source.parent)
        fsync_directory(conflict_dir)
        moved.append(destination)
    return moved


def process_archive_delivery(row: dict[str, Any], mirror_root: Path) -> ArchiveReceipt:
    staged = StagedAudio(
        Path(row["local_object_path"]),
        str(row["audio_sha256"]),
        int(row["byte_length"]),
        str(row["extension"]),
    )
    aliases = json.loads(row.get("source_aliases") or "[]")
    return publish_archive(
        staged=staged,
        transcript_id=int(row["transcript_row_id"]),
        transcript=str(row["transcript"]),
        source=str(row["archive_source"] or row["source"]),
        source_aliases=aliases,
        original_name=row.get("original_name"),
        captured_at=(
            row.get("archive_recorded_at")
            or row.get("recorded_at")
            or row.get("canonical_recorded_at")
            or row.get("created_at")
        ),
        ingested_at=row.get("ingested_at") or row.get("created_at"),
        duration_seconds=row.get("archive_duration_seconds"),
        mime_type=row.get("mime_type"),
        backend=row.get("transcription_backend"),
        model=row.get("transcription_model"),
        quality_status=row.get("quality_status"),
        publication_generation=int(row.get("publication_generation") or 1),
        alias_set_sha256=row.get("alias_set_sha256"),
        mirror_root=mirror_root,
    )
