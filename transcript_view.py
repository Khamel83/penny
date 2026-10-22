#!/usr/bin/env python3
"""Markdown-only shared transcript view for the iCloud Drive folder.

The shared view is a text-only projection of the canonical SQLite ledger.
It contains one Markdown file per accepted transcript plus one index file.
It never contains audio, raw JSON envelopes, databases, models, backups or
hidden conflict generations: source recordings stay on the local SSD.

Every file keeps a stable identity derived from the canonical transcript row,
so a changed accepted text updates one existing file instead of adding a
second copy, and a pre-existing one-time snapshot reconciles into the same
naming without duplicates.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VIEW_SCHEMA_VERSION = 1
VIEW_INDEX_FILENAME = "INDEX.md"
VIEW_SUFFIX = ".md"
VIEW_TEMP_PREFIX = ".penny-view-"


class TranscriptViewError(RuntimeError):
    """The shared Markdown view could not be published safely."""


@dataclass(frozen=True)
class ViewScan:
    """The Markdown files currently present in a shared view directory."""

    files: tuple[Path, ...]
    by_transcript_id: Mapping[int, tuple[Path, ...]]
    by_transcript_sha256: Mapping[str, tuple[Path, ...]]
    by_normalized_text: Mapping[str, tuple[Path, ...]]


def normalized_text_digest(text: str) -> str:
    """Hash a transcript body with its whitespace collapsed.

    A hand-made snapshot may re-wrap the same text, so identity is checked
    against the normalized body as well as the exact bytes.
    """
    collapsed = " ".join(str(text).split())
    return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()


def _parse_utc(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_utc(value: Any) -> str:
    parsed = _parse_utc(value)
    if parsed is None:
        return ""
    return parsed.isoformat().replace("+00:00", "Z")


def iso_utc(value: Any) -> str:
    """Return one timestamp as an ISO-8601 UTC string, or an empty string."""
    return _iso_utc(value)


def _safe_source(value: Any) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    return (safe or "unknown")[:64]


def _timestamp_slug(value: Any) -> str:
    parsed = _parse_utc(value)
    if parsed is None:
        return "unknown-time"
    return parsed.strftime("%Y-%m-%dT%H-%M-%SZ")


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Split a Markdown document into its front matter fields and its body."""
    if not text.startswith("---\n"):
        return {}, text
    closing = text.find("\n---\n", 4)
    if closing < 0:
        return {}, text
    header = text[4 : closing + 1]
    body = text[closing + 5 :]
    fields: dict[str, str] = {}
    for line in header.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        value = raw_value.strip()
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = value[1:-1]
        fields[key.strip()] = str(value)
    return fields, body


def view_filename(transcript_id: int, captured_at: Any, source: Any) -> str:
    """Return the stable filename for one accepted transcript."""
    return (
        f"p{int(transcript_id):08d}"
        f"__{_timestamp_slug(captured_at)}"
        f"__{_safe_source(source)}{VIEW_SUFFIX}"
    )


def render_transcript_markdown(row: Mapping[str, Any]) -> bytes:
    """Render one transcript as Markdown with compact provenance."""
    transcript_id = int(row["transcript_row_id"])
    transcript = str(row["transcript"])
    transcript_sha256 = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    header = (
        "---\n"
        f"schema_version: {VIEW_SCHEMA_VERSION}\n"
        f"canonical_transcript_id: {transcript_id}\n"
        f"source: {json.dumps(str(row.get('source') or ''), ensure_ascii=False)}\n"
        f"captured_at: {json.dumps(_iso_utc(row.get('captured_at')))}\n"
        f"ingested_at: {json.dumps(_iso_utc(row.get('ingested_at')))}\n"
        f"transcript_sha256: {json.dumps(transcript_sha256)}\n"
        f"audio_sha256: {json.dumps(str(row.get('audio_sha256') or ''))}\n"
        f"transcription_backend: {json.dumps(str(row.get('transcription_backend') or ''))}\n"
        f"transcription_model: {json.dumps(str(row.get('transcription_model') or ''))}\n"
        f"quality_status: {json.dumps(str(row.get('quality_status') or ''))}\n"
        "---\n"
    )
    return header.encode("utf-8") + transcript.encode("utf-8")


def render_index(entries: Iterable[Mapping[str, Any]]) -> bytes:
    """Render the index of the shared view from published ledger entries."""
    ordered = sorted(
        entries,
        key=lambda entry: (
            str(entry.get("captured_at") or ""),
            int(entry.get("transcript_row_id") or 0),
        ),
    )
    lines = [
        "# Penny Transcripts",
        "",
        "Markdown-only view of accepted Penny transcripts. Audio, raw JSON",
        "envelopes, databases, models and backups stay on the local SSD; source",
        "recordings are never written here.",
        "",
        f"Entries: {len(ordered)}",
        "",
        "| Captured (UTC) | Transcript | Source | Transcript SHA-256 | File |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in ordered:
        captured = str(entry.get("captured_at") or "")
        filename = str(entry.get("filename") or "")
        digest = str(entry.get("transcript_sha256") or "")
        lines.append(
            f"| {captured} | p{int(entry.get('transcript_row_id') or 0):08d} "
            f"| {entry.get('source') or ''} | `{digest[:12]}` "
            f"| [{filename}]({filename}) |"
        )
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def scan_view_root(view_root: Path) -> ViewScan:
    """Index the Markdown files already present in the shared view."""
    root = Path(view_root)
    files: list[Path] = []
    by_id: dict[int, list[Path]] = {}
    by_sha: dict[str, list[Path]] = {}
    by_normalized: dict[str, list[Path]] = {}
    if not root.is_dir():
        return ViewScan((), {}, {}, {})
    for path in sorted(root.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() != VIEW_SUFFIX or path.name == VIEW_INDEX_FILENAME:
            continue
        files.append(path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        fields, body = split_front_matter(text)
        raw_id = fields.get("canonical_transcript_id")
        if raw_id:
            try:
                by_id.setdefault(int(raw_id), []).append(path)
            except ValueError:
                pass
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        by_sha.setdefault(digest, []).append(path)
        by_normalized.setdefault(normalized_text_digest(body), []).append(path)
    return ViewScan(tuple(files), by_id, by_sha, by_normalized)


def _write_atomic(path: Path, content: bytes) -> None:
    temporary = path.with_name(f"{VIEW_TEMP_PREFIX}{uuid.uuid4().hex}.partial")
    try:
        with temporary.open("xb") as writer:
            os.chmod(temporary, 0o644)
            writer.write(content)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o644)
    finally:
        temporary.unlink(missing_ok=True)


def publish_transcript_view(
    row: Mapping[str, Any],
    view_root: Path,
    scan: ViewScan | None = None,
) -> Path:
    """Publish one accepted transcript as Markdown under its stable name.

    A pre-existing file for the same transcript is renamed into place instead
    of duplicated, and any further copy of the same transcript is removed.
    """
    root = Path(view_root)
    if not root.parent.is_dir():
        raise TranscriptViewError("view_root_unavailable")
    root.mkdir(parents=True, exist_ok=True)
    transcript_id = int(row["transcript_row_id"])
    transcript = str(row["transcript"])
    if not transcript.strip():
        raise TranscriptViewError("empty_transcript")
    digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    desired = root / view_filename(
        transcript_id,
        row.get("captured_at"),
        row.get("source"),
    )
    current = scan if scan is not None else scan_view_root(root)

    candidates: list[Path] = []
    for group in (
        current.by_transcript_id.get(transcript_id, ()),
        current.by_transcript_sha256.get(digest, ()),
        current.by_normalized_text.get(normalized_text_digest(transcript), ()),
    ):
        for candidate in group:
            if candidate not in candidates:
                candidates.append(candidate)
    if desired.exists() and desired not in candidates:
        candidates.append(desired)

    if desired in candidates:
        for duplicate in candidates:
            if duplicate != desired:
                duplicate.unlink(missing_ok=True)
    elif candidates:
        os.replace(candidates[0], desired)
        for duplicate in candidates[1:]:
            duplicate.unlink(missing_ok=True)

    content = render_transcript_markdown(row)
    if not desired.exists() or desired.read_bytes() != content:
        _write_atomic(desired, content)
    return desired


def write_index(view_root: Path, entries: Iterable[Mapping[str, Any]]) -> bool:
    """Write the shared index file; return True when its bytes changed."""
    root = Path(view_root)
    if not root.parent.is_dir():
        raise TranscriptViewError("view_root_unavailable")
    root.mkdir(parents=True, exist_ok=True)
    destination = root / VIEW_INDEX_FILENAME
    content = render_index(entries)
    if destination.exists() and destination.read_bytes() == content:
        return False
    _write_atomic(destination, content)
    return True
