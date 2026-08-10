#!/usr/bin/env python3
"""Poll iCloud Voice Memos, transcribe new recordings, and route them through Penny."""

from __future__ import annotations

import logging
import mimetypes
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

from archive import (
    SourceChangedError,
    StagedAudio,
    process_archive_delivery,
    preserve_invalid_local_mirror,
    sha256_file,
    stage_audio,
    validate_archive,
    validate_local_mirror_receipt,
)
from config import get_config
from core import classify_and_route, get_file_hash, setup_logging
from maya_delivery import process_pending_maya_deliveries
from slack_delivery import process_pending_slack
from transcript_quality import transcribe_with_quality
from transcript_log import (
    InsertOutcome,
    get_archive_delivery_health,
    get_archive_backfill_candidates,
    get_pending_archive_deliveries,
    get_published_archive_deliveries,
    get_maya_delivery_health,
    get_source_watermark,
    get_slack_delivery_health,
    get_transcript_by_hash,
    get_voice_memo_health,
    get_voice_memo_recordings_waiting_for_file,
    get_voice_memo_recordings_for_retry,
    init_db,
    insert_transcript_result,
    is_already_logged,
    get_pending,
    link_voice_memo_transcript,
    mark_voice_memo_file_seen,
    mark_voice_memo_routed,
    mark_voice_memo_routed_for_transcript,
    mark_voice_memo_retryable,
    mark_voice_memo_terminal,
    mark_voice_memo_waiting_for_file,
    mark_archive_delivery_failed,
    mark_archive_delivery_published,
    mark_archive_delivery_rebuild_needed,
    mark_archive_delivery_validated,
    needs_archive_delivery,
    queue_archive_delivery,
    record_archive_backfill_failure,
    record_archive_unavailable,
    upsert_voice_memo_recording,
    advance_source_watermark,
)

cfg = get_config()
log = setup_logging("watcher")

# Paths
VOICE_MEMOS_DIR = Path(
    os.environ.get(
        "VOICE_MEMOS_DIR",
        "~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings",
    )
).expanduser()
STATE_FILE = Path("~/.penny/last_pk.txt").expanduser()
CLOUDRECORDINGS_DB = VOICE_MEMOS_DIR / "CloudRecordings.db"
HEALTH_FILE = Path("~/.penny/health.txt").expanduser()

POLL_INTERVAL = cfg.voice_memos.poll_interval_seconds
HEALTH_CHECK_INTERVAL = 300
MAX_FILE_SIZE = cfg.voice_memos.max_file_size_mb * 1024 * 1024
FILE_SCAN_PROCESS_LIMIT = cfg.voice_memos.startup_process_limit
# Only process files created within this window. Prevents re-processing old files
# when VoiceMemos touches their mtimes during sync or restart.
MAX_FILE_AGE = timedelta(hours=24)

VOICE_MEMOS_RESPONSIVENESS_SCRIPT = (
    "with timeout of 5 seconds\n"
    '  tell application "Voice Memos" to get name\n'
    "end timeout"
)
VOICE_MEMO_UNRESPONSIVE_LIMIT = 3
_voicememos_unresponsive_streak = 0


# ===== Dependencies =====


def check_dependencies() -> tuple[List[str], List[str]]:
    """Return (errors, warnings) for startup dependency checks."""
    errors: List[str] = []
    warnings: List[str] = []

    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        if result.returncode != 0:
            errors.append("ffmpeg found but not working")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        errors.append(f"ffmpeg not found: {e}")

    try:
        import mlx_whisper  # noqa: F401
    except ImportError:
        errors.append("mlx_whisper not installed")

    try:
        import requests  # noqa: F401
    except ImportError:
        errors.append("requests not installed")

    if not VOICE_MEMOS_DIR.exists():
        errors.append(f"Voice Memos directory not found: {VOICE_MEMOS_DIR}")

    if cfg.notifications.telegram_enabled and (
        not cfg.telegram_bot_token or not cfg.telegram_chat_id
    ):
        errors.append(
            "Telegram is enabled but TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID is missing"
        )

    if not cfg.openrouter_api_key:
        warnings.append(
            "OPENROUTER_API_KEY not set — classification falls back to Inbox"
        )

    if CLOUDRECORDINGS_DB.exists():
        conn = None
        try:
            conn = sqlite3.connect(str(CLOUDRECORDINGS_DB), timeout=5.0)
            conn.execute("SELECT COUNT(*) FROM ZCLOUDRECORDING")
        except Exception as e:
            errors.append(f"Database corrupted or unreadable: {e}")
        finally:
            if conn:
                conn.close()

    return errors, warnings


# ===== Health =====


def _db_recordings_count() -> int:
    if not CLOUDRECORDINGS_DB.exists():
        return 0
    conn = None
    try:
        conn = sqlite3.connect(str(CLOUDRECORDINGS_DB), timeout=5.0)
        cursor = conn.execute("SELECT COUNT(*) FROM ZCLOUDRECORDING")
        row = cursor.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0
    finally:
        if conn:
            conn.close()


def _voicememos_running() -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-x", "VoiceMemos"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def _voicememos_responsive() -> bool:
    """Check that Voice Memos answers an Apple Event, not just has a PID."""
    try:
        result = subprocess.run(
            ["osascript", "-e", VOICE_MEMOS_RESPONSIVENESS_SCRIPT],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if result.returncode != 0:
            detail = (result.stderr or "").strip().replace("\n", " ")[:200]
            log.warning("VoiceMemos responsiveness probe failed: %s", detail)
            return False
        return True
    except Exception as e:
        log.warning("VoiceMemos responsiveness probe errored: %s", e)
        return False


def _cloud_recording_snapshot() -> dict[str, Any]:
    """Return non-secret evidence about the local Voice Memos sync database."""
    snapshot: dict[str, Any] = {
        "db_ok": False,
        "record_count": 0,
        "latest_pk": 0,
        "latest_date": None,
        "wal_exists": False,
        "wal_age_seconds": -1,
    }
    if not CLOUDRECORDINGS_DB.exists():
        return snapshot

    connection = None
    try:
        connection = sqlite3.connect(str(CLOUDRECORDINGS_DB), timeout=5.0)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        snapshot["db_ok"] = bool(integrity and integrity[0] == "ok")
        row = connection.execute(
            "SELECT COUNT(*), COALESCE(MAX(Z_PK), 0), MAX(ZDATE) "
            "FROM ZCLOUDRECORDING"
        ).fetchone()
        if row:
            snapshot["record_count"] = int(row[0] or 0)
            snapshot["latest_pk"] = int(row[1] or 0)
            snapshot["latest_date"] = row[2]
    except Exception as e:
        log.warning("VoiceMemos sync database probe failed: %s", e)
    finally:
        if connection:
            connection.close()

    wal_path = Path(f"{CLOUDRECORDINGS_DB}-wal")
    try:
        wal_stat = wal_path.stat()
        snapshot["wal_exists"] = True
        snapshot["wal_age_seconds"] = max(0, int(time.time() - wal_stat.st_mtime))
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("VoiceMemos WAL probe failed: %s", e)
    return snapshot


def _transcripts_pending() -> int:
    pending = get_pending(limit=1)
    return len(pending)


def update_health_check() -> None:
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat()
    vm = 1 if _voicememos_running() else 0
    vm_responsive = 1 if vm and _voicememos_responsive() else 0
    pending = _transcripts_pending()
    vm_health = get_voice_memo_health()
    slack_health = get_slack_delivery_health()
    maya_health = get_maya_delivery_health()
    archive_health = get_archive_delivery_health()
    cloud_health = _cloud_recording_snapshot()
    slack_health_error = int(slack_health.get("health_error", 0))
    maya_health_error = int(maya_health.get("health_error", 0))
    maya_configured = int(
        bool(cfg.maya.transcript_url.strip() and cfg.maya.ingest_token.strip())
    )
    watcher_ok = int(
        not slack_health_error
        and int(slack_health.get("failed_count", 0)) == 0
        and int(slack_health.get("quality_failure_failed_count", 0)) == 0
        and not maya_health_error
        and maya_configured
        and int(maya_health.get("failed_count", 0)) == 0
        and int(vm_health.get("terminal_failure_count", 0)) == 0
        and not int(archive_health.get("health_error", 0))
        and int(archive_health.get("failed_count", 0)) == 0
        and int(archive_health.get("invalid_count", 0)) == 0
        and int(archive_health.get("rebuild_needed_count", 0)) == 0
        and int(archive_health.get("backfill_failed_count", 0)) == 0
    )
    HEALTH_FILE.write_text(
        (
            f"{now}|db_records:{cloud_health['record_count']}|"
            f"watcher_ok:{watcher_ok}|voicememos:{vm}|"
            f"voicememos_responsive:{vm_responsive}|"
            f"voice_db_ok:{int(cloud_health['db_ok'])}|"
            f"voice_db_wal_age_seconds:{cloud_health['wal_age_seconds']}|"
            f"cloud_latest_recording_pk:{cloud_health['latest_pk']}|"
            f"pending:{pending}|latest_recording_pk:{vm_health['latest_recording_pk']}|"
            f"awaiting_file:{vm_health['awaiting_file_count']}|"
            f"voice_memo_failed:{vm_health['failed_count']}|"
            f"voice_memo_retry_due:{vm_health.get('retry_due_count', 0)}|"
            f"voice_memo_terminal:{vm_health.get('terminal_count', 0)}|"
            f"voice_memo_terminal_failures:"
            f"{vm_health.get('terminal_failure_count', 0)}|"
            f"voice_memo_max_attempts:{vm_health.get('max_attempt_count', 0)}|"
            f"voice_memo_source_watermark:{vm_health.get('source_watermark', 0)}|"
            f"slack_pending:{slack_health['pending_count']}|"
            f"slack_failed:{slack_health['failed_count']}|"
            f"slack_health_error:{slack_health_error}|"
            f"quality_failure_slack_pending:"
            f"{slack_health.get('quality_failure_pending_count', 0)}|"
            f"quality_failure_slack_failed:"
            f"{slack_health.get('quality_failure_failed_count', 0)}|"
            f"maya_configured:{maya_configured}|"
            f"maya_pending:{maya_health['pending_count']}|"
            f"maya_due:{maya_health['due_count']}|"
            f"maya_failed:{maya_health['failed_count']}|"
            f"maya_oldest_due_age_seconds:"
            f"{maya_health['oldest_due_age_seconds']}|"
            f"maya_query_ok:{int(maya_health.get('query_ok', not maya_health_error))}|"
            f"maya_health_error:{maya_health_error}|"
            f"quality_needs_review:"
            f"{maya_health['quality_needs_review_count']}|"
            f"archive_pending:{archive_health.get('pending_count', 0)}|"
            f"archive_local_mirror_published:"
            f"{archive_health.get('local_mirror_published_count', archive_health.get('sent_count', 0))}|"
            f"archive_failed:{archive_health.get('failed_count', 0)}|"
            f"archive_unavailable:{archive_health.get('unavailable_count', 0)}|"
            f"archive_not_applicable:{archive_health.get('not_applicable_count', 0)}|"
            f"archive_invalid:{archive_health.get('invalid_count', 0)}|"
            f"archive_rebuild_needed:{archive_health.get('rebuild_needed_count', 0)}|"
            f"archive_backfill_pending:{archive_health.get('backfill_pending_count', 0)}|"
            f"archive_backfill_failed:{archive_health.get('backfill_failed_count', 0)}|"
            f"archive_oldest_pending_age_seconds:"
            f"{archive_health.get('oldest_pending_age_seconds', 0)}|"
            f"archive_health_error:{archive_health.get('health_error', 0)}\n"
        ),
        encoding="utf-8",
    )


# ===== State (last seen DB primary key) =====


def get_last_seen_pk() -> int:
    """Return the SQLite source cursor; last_pk.txt is only a compatibility mirror."""
    return get_source_watermark("voice_memos")


def set_last_seen_pk(pk: int) -> None:
    """Atomically mirror an already-durable source watermark for compatibility."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_name(f".{STATE_FILE.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(str(pk))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, STATE_FILE)


# ===== Database polling =====


def get_new_recordings() -> List[Dict[str, Any]]:
    if not CLOUDRECORDINGS_DB.exists():
        log.warning("Database not found: %s", CLOUDRECORDINGS_DB)
        return []

    last_pk = get_last_seen_pk()
    conn = None
    try:
        conn = sqlite3.connect(str(CLOUDRECORDINGS_DB), timeout=5.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT Z_PK, ZCUSTOMLABEL, ZDATE, ZDURATION, ZPATH
            FROM ZCLOUDRECORDING
            WHERE Z_PK > ?
            ORDER BY Z_PK ASC
            """,
            (last_pk,),
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        log.error("Database query failed: %s", e)
        return []
    finally:
        if conn:
            conn.close()


def get_recordings_by_pk(recording_pks: List[int]) -> Dict[int, Dict[str, Any]]:
    """Fetch current Voice Memos DB rows for already-discovered recordings."""
    if not recording_pks or not CLOUDRECORDINGS_DB.exists():
        return {}

    unique_pks = sorted({int(pk) for pk in recording_pks})
    placeholders = ",".join("?" for _ in unique_pks)
    conn = None
    try:
        conn = sqlite3.connect(str(CLOUDRECORDINGS_DB), timeout=5.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            f"""
            SELECT Z_PK, ZCUSTOMLABEL, ZDATE, ZDURATION, ZPATH
            FROM ZCLOUDRECORDING
            WHERE Z_PK IN ({placeholders})
            """,
            unique_pks,
        )
        return {int(row["Z_PK"]): dict(row) for row in cursor.fetchall()}
    except Exception as e:
        log.error("Database refresh query failed: %s", e)
        return {}
    finally:
        if conn:
            conn.close()


def _recording_timestamp_utc(recording: Dict[str, Any]) -> str | None:
    """Normalize Voice Memos' Foundation ZDATE or a persisted UTC value."""
    persisted = recording.get("recorded_at")
    if persisted:
        parsed = datetime.fromisoformat(str(persisted).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    zdate = recording.get("ZDATE")
    if zdate is None:
        return None
    reference_date = datetime(2001, 1, 1, tzinfo=timezone.utc)
    recorded_at = reference_date + timedelta(seconds=float(zdate))
    return recorded_at.isoformat().replace("+00:00", "Z")


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def scan_for_unprocessed_files() -> List[tuple[Path, str]]:
    """Return list of (path, file_hash) tuples for unprocessed files."""
    try:
        all_files = list(VOICE_MEMOS_DIR.glob("*.m4a"))
    except Exception as e:
        log.error("File scan failed: %s", e)
        return []

    all_files.sort(key=_safe_mtime, reverse=True)
    unprocessed: List[tuple[Path, str]] = []
    cutoff = time.time() - MAX_FILE_AGE.total_seconds()

    for audio_file in all_files:
        # Skip files older than MAX_FILE_AGE — they're either already processed
        # or were touched by VoiceMemos/CloudKit without actual content changes.
        if _safe_mtime(audio_file) < cutoff:
            break  # sorted by mtime desc, so all remaining are even older

        try:
            file_hash = get_file_hash(audio_file)
        except FileNotFoundError:
            continue
        except Exception as e:
            log.warning("Could not hash %s during scan: %s", audio_file.name, e)
            continue

        if not is_already_logged(file_hash) or needs_archive_delivery(file_hash):
            unprocessed.append((audio_file, file_hash))

    return unprocessed


# ===== Processing =====


def _find_audio_path_for_recording(recording: Dict[str, Any]) -> Optional[Path]:
    raw_path = recording.get("ZPATH")
    label = recording.get("ZCUSTOMLABEL") or ""

    if raw_path:
        audio_path = VOICE_MEMOS_DIR / str(raw_path)
        if audio_path.exists():
            return audio_path
        log.warning("File in DB not found yet: %s", audio_path)

    if label:
        normalized_prefix = str(label)[:10].replace("-", "")
        for candidate in VOICE_MEMOS_DIR.glob("*.m4a"):
            name = candidate.name
            if label in name or (
                normalized_prefix and name.startswith(normalized_prefix)
            ):
                return candidate

    return None


def _process_audio_file(
    audio_path: Path,
    file_hash: str | None = None,
    *,
    duration_seconds: float | None = None,
    recording_pk: int | None = None,
    recorded_at: str | None = None,
) -> bool:
    if file_hash is None:
        file_hash = get_file_hash(audio_path)
    staged = stage_audio(audio_path, cfg.archive.object_root)
    if len(file_hash) == 32 and all(character in "0123456789abcdef" for character in file_hash.lower()):
        if get_file_hash(staged.path) != file_hash.lower():
            raise SourceChangedError(audio_path.name)
    ingested_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def metadata(
        quality_status: str,
        *,
        backend: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        return {
            "source": "iCloud",
            "source_alias": audio_path.name,
            "original_name": audio_path.name,
            "captured_at": recorded_at,
            "ingested_at": ingested_at,
            "duration_seconds": duration_seconds,
            "mime_type": mimetypes.guess_type(audio_path.name)[0],
            "backend": backend,
            "model": model,
            "quality_status": quality_status,
        }

    def persist_archive(
        row_id: int,
        quality_status: str,
        canonical: dict[str, Any] | None = None,
    ) -> bool:
        try:
            canonical = canonical or get_transcript_by_hash(file_hash) or {}
            queue_archive_delivery(
                row_id,
                staged,
                metadata(
                    quality_status,
                    backend=canonical.get("transcription_backend"),
                    model=canonical.get("transcription_model"),
                ),
            )
            return True
        except Exception as exc:
            log.error(
                "Could not durably queue archive for transcript id=%s: %s",
                row_id,
                type(exc).__name__,
            )
            return False

    file_size = staged.byte_length
    if file_size > MAX_FILE_SIZE:
        log.warning(
            "Skipping %s (%.1fMB) — too large",
            audio_path.name,
            file_size / (1024 * 1024),
        )
        result = insert_transcript_result(
            content_hash=file_hash,
            source="iCloud",
            transcript="(skipped: file too large)",
            audio_path=str(staged.path),
            duration_seconds=duration_seconds,
            ingest_state="skipped_too_large",
            recorded_at=recorded_at,
            file_seen_at=datetime.now().isoformat(),
            quality_status="skipped_too_large",
            enqueue_slack=False,
            archive_staged=staged,
            archive_metadata=metadata("skipped_too_large"),
        )
        if result.outcome is InsertOutcome.FAILED:
            log.error("Could not durably record oversized file: %s", audio_path.name)
            return False
        if result.outcome is InsertOutcome.DUPLICATE:
            existing = get_transcript_by_hash(file_hash)
            if existing is None:
                log.error("Oversized file duplicate has no canonical row: %s", audio_path.name)
                return False
            row_id = int(existing["id"])
        else:
            row_id = int(result.row_id)
        if result.outcome is InsertOutcome.DUPLICATE and not persist_archive(
            row_id, "skipped_too_large", existing
        ):
            return False
        if recording_pk is not None:
            if not link_voice_memo_transcript(
                recording_pk,
                transcript_row_id=row_id,
                content_hash=file_hash,
                audio_path=str(audio_path),
            ):
                return False
            mark_voice_memo_terminal(recording_pk, "skipped_too_large")
        return True

    existing = get_transcript_by_hash(file_hash)
    if existing is not None:
        log.info("Already logged: %s", audio_path.name)
        row_id = int(existing["id"])
        if not persist_archive(
            row_id, str(existing.get("quality_status") or "unknown"), existing
        ):
            return False
        already_routed = existing.get("status") in {"routed", "processed"}
        if recording_pk is not None:
            mark_voice_memo_file_seen(recording_pk, str(audio_path))
            if not link_voice_memo_transcript(
                recording_pk,
                transcript_row_id=row_id,
                content_hash=file_hash,
                audio_path=str(audio_path),
                routed=already_routed,
            ):
                return False
        if already_routed or existing.get("quality_status") != "passed":
            if recording_pk is not None:
                mark_voice_memo_terminal(
                    recording_pk,
                    "routed" if already_routed else "needs_review",
                )
            return True

        classify_and_route(
            str(existing["transcript"]),
            source=str(existing["source"]),
            row_id=row_id,
            duration_seconds=duration_seconds,
            allow_maya=False,
        )
        if recording_pk is not None:
            mark_voice_memo_routed(recording_pk)
        return True

    file_seen_at = datetime.now().isoformat()
    transcription_started_at = datetime.now().isoformat()
    transcription = transcribe_with_quality(
        staged.path,
        model=cfg.voice_memos.whisper_model,
    )
    transcription_completed_at = datetime.now().isoformat()
    transcript = transcription.text

    if not transcription.quality.passed:
        quality_detail = transcription.quality_detail or (
            f"attempt_{transcription.attempts}="
            f"{transcription.quality.reason or 'unknown_quality_failure'}"
        )
        log.warning(
            "Transcript needs review for %s (reason=%s)",
            audio_path.name,
            transcription.quality.reason,
        )
        result = insert_transcript_result(
            content_hash=file_hash,
            source="iCloud",
            transcript=transcript,
            audio_path=str(staged.path),
            duration_seconds=duration_seconds,
            ingest_state="needs_review",
            recorded_at=recorded_at,
            file_seen_at=file_seen_at,
            transcription_started_at=transcription_started_at,
            transcription_completed_at=transcription_completed_at,
            quality_status="needs_review",
            quality_detail=quality_detail,
            enqueue_slack=False,
            archive_staged=staged,
            archive_metadata=metadata(
                "needs_review",
                backend="mlx-whisper",
                model=cfg.voice_memos.whisper_model,
            ),
        )
        if result.outcome is InsertOutcome.FAILED:
            log.error("Could not durably retain quality-review transcript: %s", audio_path.name)
            return False
        if result.outcome is InsertOutcome.DUPLICATE:
            existing = get_transcript_by_hash(file_hash)
            if existing is None:
                log.error("Quality-review duplicate has no canonical row: %s", audio_path.name)
                return False
            row_id = int(existing["id"])
        else:
            row_id = int(result.row_id)
        if result.outcome is InsertOutcome.DUPLICATE and not persist_archive(
            row_id, "needs_review", existing
        ):
            return False
        if recording_pk is not None:
            if not link_voice_memo_transcript(
                recording_pk,
                transcript_row_id=row_id,
                content_hash=file_hash,
                audio_path=str(audio_path),
            ):
                return False
            mark_voice_memo_terminal(recording_pk, "needs_review")
        return True

    result = insert_transcript_result(
        content_hash=file_hash,
        source="iCloud",
        transcript=transcript,
        audio_path=str(staged.path),
        duration_seconds=duration_seconds,
        ingest_state="transcribed",
        recorded_at=recorded_at,
        file_seen_at=file_seen_at,
        transcription_started_at=transcription_started_at,
        transcription_completed_at=transcription_completed_at,
        maya_delivery_eligible=recorded_at is not None,
        archive_staged=staged,
        archive_metadata=metadata(
            "passed",
            backend="mlx-whisper",
            model=cfg.voice_memos.whisper_model,
        ),
    )
    if result.outcome is InsertOutcome.FAILED:
        log.error("Could not durably record transcript: %s", audio_path.name)
        return False

    if result.outcome is InsertOutcome.DUPLICATE:
        existing = get_transcript_by_hash(file_hash)
        if existing is None:
            log.error("Transcript duplicate has no canonical row: %s", audio_path.name)
            return False
        row_id = int(existing["id"])
        if not persist_archive(row_id, "passed", existing):
            return False
        if recording_pk is not None:
            if not link_voice_memo_transcript(
                recording_pk,
                transcript_row_id=row_id,
                content_hash=file_hash,
                audio_path=str(audio_path),
                routed=existing.get("status") in {"routed", "processed"},
            ):
                return False
        if existing.get("status") in {"routed", "processed"}:
            if recording_pk is not None:
                mark_voice_memo_terminal(recording_pk, "routed")
            return True
        if existing.get("quality_status") != "passed":
            if recording_pk is not None:
                mark_voice_memo_terminal(recording_pk, "needs_review")
            return True
        transcript = str(existing["transcript"])
    else:
        row_id = int(result.row_id)
        if recording_pk is not None:
            if not link_voice_memo_transcript(
                recording_pk,
                transcript_row_id=row_id,
                content_hash=file_hash,
                audio_path=str(audio_path),
            ):
                return False

    classify_and_route(
        transcript,
        source="iCloud",
        row_id=row_id,
        duration_seconds=duration_seconds,
        allow_maya=False,
    )
    if recording_pk is not None:
        mark_voice_memo_routed(recording_pk)
    return True


def process_recording(
    recording: Dict[str, Any], *, already_upserted: bool = False
) -> bool:
    pk = int(recording["Z_PK"])
    label = recording.get("ZCUSTOMLABEL") or f"Recording {pk}"
    raw_path = str(recording.get("ZPATH") or "")
    duration_seconds = (
        float(recording.get("ZDURATION"))
        if recording.get("ZDURATION") is not None
        else None
    )
    recorded_at = _recording_timestamp_utc(recording)
    if not already_upserted and not upsert_voice_memo_recording(
        pk,
        label=label,
        raw_path=raw_path,
        duration_seconds=duration_seconds,
        recorded_at=recorded_at,
    ):
        return False
    log.info("Processing %s (PK=%s)", label, pk)

    audio_path = _find_audio_path_for_recording(recording)
    if not audio_path or not audio_path.exists():
        log.error(
            "File not found for %s (PK=%s); will retry via later DB poll or disk scan",
            label,
            pk,
        )
        mark_voice_memo_waiting_for_file(pk, "file not downloaded yet")
        mark_voice_memo_retryable(pk, "file_not_downloaded")
        return False

    try:
        mark_voice_memo_file_seen(pk, str(audio_path))
        processed = _process_audio_file(
            audio_path,
            duration_seconds=duration_seconds,
            recording_pk=pk,
            recorded_at=recorded_at,
        )
        if not processed:
            mark_voice_memo_retryable(pk, "transcription_failed")
        return processed
    except SourceChangedError:
        mark_voice_memo_retryable(pk, "source_changed")
        log.error("Voice Memo changed during durable staging (PK=%s)", pk)
        return False
    except Exception as e:
        mark_voice_memo_retryable(pk, "processing_error")
        log.error("Error processing Voice Memo PK=%s: %s", pk, type(e).__name__)
        return False


def process_file(audio_path: Path, *, file_hash: str | None = None) -> bool:
    try:
        log.info(
            "Processing file: %s (%.1fMB)",
            audio_path.name,
            audio_path.stat().st_size / (1024 * 1024),
        )
        return _process_audio_file(audio_path, file_hash=file_hash)
    except FileNotFoundError:
        log.warning("File disappeared before processing: %s", audio_path)
        return False
    except Exception as e:
        log.error("Error processing %s: %s", audio_path.name, e, exc_info=True)
        return False


def _ensure_voicememos_running() -> None:
    """Refresh Voice Memos and recycle it after repeated failed probes."""
    global _voicememos_unresponsive_streak
    try:
        running = _voicememos_running()
        responsive = running and _voicememos_responsive()
        if not running:
            _voicememos_unresponsive_streak = 0
            log.warning("VoiceMemos not running — launching for CloudKit sync")
        elif not responsive:
            _voicememos_unresponsive_streak += 1
            log.warning(
                "VoiceMemos is not responsive (probe %s/%s)",
                _voicememos_unresponsive_streak,
                VOICE_MEMO_UNRESPONSIVE_LIMIT,
            )
            if _voicememos_unresponsive_streak >= VOICE_MEMO_UNRESPONSIVE_LIMIT:
                log.error(
                    "VoiceMemos stayed unresponsive; recycling it to recover sync"
                )
                subprocess.run(
                    ["pkill", "-TERM", "-x", "VoiceMemos"],
                    check=False,
                    capture_output=True,
                    timeout=10,
                )
                _voicememos_unresponsive_streak = 0
        else:
            _voicememos_unresponsive_streak = 0

        refresh = subprocess.run(
            ["open", "-g", "-a", "VoiceMemos"],
            check=False,
            capture_output=True,
            timeout=10,
        )
        if refresh.returncode != 0:
            log.warning("VoiceMemos sync refresh failed (exit=%s)", refresh.returncode)
    except Exception as e:
        log.warning("Could not check/launch VoiceMemos: %s", e)


def _process_db_batch(recordings: List[Dict[str, Any]]) -> None:
    if not recordings:
        return
    log.info("Found %s new recording(s)", len(recordings))
    max_registered_pk = get_source_watermark("voice_memos")
    for recording in recordings[:FILE_SCAN_PROCESS_LIMIT]:
        pk = int(recording["Z_PK"])
        persisted = upsert_voice_memo_recording(
            pk,
            label=recording.get("ZCUSTOMLABEL") or f"Recording {pk}",
            raw_path=str(recording.get("ZPATH") or ""),
            duration_seconds=(
                float(recording.get("ZDURATION"))
                if recording.get("ZDURATION") is not None
                else None
            ),
            recorded_at=_recording_timestamp_utc(recording),
        )
        if not persisted:
            log.error("Stopping discovery batch after durable upsert failure pk=%s", pk)
            break
        max_registered_pk = max(max_registered_pk, pk)
        process_recording(recording, already_upserted=True)
    if max_registered_pk > get_source_watermark("voice_memos"):
        if advance_source_watermark("voice_memos", max_registered_pk):
            set_last_seen_pk(max_registered_pk)
    if len(recordings) > FILE_SCAN_PROCESS_LIMIT:
        log.info(
            "Batch capped at %s of %s recordings (remaining will process next cycle)",
            FILE_SCAN_PROCESS_LIMIT,
            len(recordings),
        )


def _process_disk_backlog(limit: int) -> None:
    unprocessed = scan_for_unprocessed_files()
    if not unprocessed:
        return
    log.info("Found %s unprocessed file(s) on disk", len(unprocessed))
    for audio_file, file_hash in unprocessed[:limit]:
        process_file(audio_file, file_hash=file_hash)


def _process_slack_outbox() -> None:
    try:
        delivered = process_pending_slack(limit=1)
        if delivered:
            log.info("Delivered %s transcript(s) to Slack", delivered)
    except Exception as e:
        log.error("Slack outbox processing failed: %s", e, exc_info=True)


def _process_maya_outbox() -> None:
    try:
        delivered = process_pending_maya_deliveries(limit=1)
        if delivered:
            log.info("Delivered %s transcript(s) to Maya", delivered)
    except Exception as e:
        log.error("Maya outbox processing failed: %s", e, exc_info=True)


def _process_archive_outbox() -> None:
    """Drain a bounded archive batch without coupling it to routing delivery."""
    for row in get_pending_archive_deliveries(limit=cfg.archive.delivery_batch_limit):
        delivery_id = int(row["id"])
        try:
            receipt = process_archive_delivery(row, cfg.archive.mirror_root)
            mark_archive_delivery_published(
                delivery_id,
                audio_path=str(receipt.audio_path),
                markdown_path=str(receipt.markdown_path),
                manifest_path=str(receipt.manifest_path),
                receipt_sha256=receipt.receipt_sha256,
            )
        except Exception as exc:
            mark_archive_delivery_failed(delivery_id, type(exc).__name__)
            log.error(
                "Archive publication failed for delivery id=%s: %s",
                delivery_id,
                type(exc).__name__,
            )


def _reconcile_archive_backfill(limit: int) -> None:
    """Reconcile old canonical rows without retranscription or rerouting."""
    for row in get_archive_backfill_candidates(limit=limit):
        transcript_id = int(row["transcript_row_id"])
        raw_candidates = [
            Path(value)
            for value in (row.get("transcript_audio_path"), row.get("voice_audio_path"))
            if value
        ]
        object_root = Path(cfg.archive.object_root).resolve()
        voice_root = Path(VOICE_MEMOS_DIR).resolve()

        def safe_path(path: Path, root: Path) -> Path | None:
            try:
                if not path.is_absolute() or path.is_symlink():
                    return None
                resolved = path.resolve()
                return resolved if resolved.is_relative_to(root) else None
            except OSError:
                return None

        staged: StagedAudio | None = None
        candidate: Path | None = None
        unsafe_candidate = False
        invalid_local_object = False
        for raw_candidate in raw_candidates:
            local = safe_path(raw_candidate, object_root)
            if local is not None:
                known_sha = str(row.get("audio_sha256") or "")
                try:
                    info = local.stat()
                    expected = (
                        object_root / "sha256" / known_sha[:2]
                        / f"{known_sha}{local.suffix.lower()}"
                    )
                    if (
                        len(known_sha) != 64
                        or local != expected
                        or not local.is_file()
                        or info.st_size <= 0
                        or (info.st_mode & 0o777) != 0o400
                        or sha256_file(local) != known_sha
                    ):
                        invalid_local_object = True
                        continue
                    staged = StagedAudio(
                        local, known_sha, info.st_size, local.suffix.lower()
                    )
                    candidate = local
                    break
                except OSError:
                    invalid_local_object = True
                    continue
            external = safe_path(raw_candidate, voice_root)
            if external is not None:
                if external.is_file():
                    candidate = external
                    break
                continue
            unsafe_candidate = True

        if candidate is None:
            source = str(row.get("source") or "").lower()
            transcript = str(row.get("transcript") or "").lstrip().lower()
            if invalid_local_object:
                status, reason = "unavailable", "invalid_local_object"
            elif unsafe_candidate:
                status, reason = "unavailable", "unsafe_audio_source"
            elif transcript.startswith("(migrated"):
                status, reason = "unavailable", "legacy_placeholder"
            elif source in {"icloud", "shortcut", "voice-memos"}:
                status, reason = "unavailable", "missing_audio_source"
            else:
                status, reason = "not_applicable", "no_raw_audio"
            record_archive_unavailable(
                transcript_id,
                availability_status=status,
                reason_code=reason,
            )
            continue
        try:
            if staged is None:
                staged = stage_audio(candidate, cfg.archive.object_root)
        except Exception as exc:
            record_archive_backfill_failure(
                transcript_id, "archive_backfill_source_error"
            )
            log.error(
                "Archive backfill failed for transcript id=%s: %s",
                transcript_id,
                type(exc).__name__,
            )
            continue
        try:
            queue_archive_delivery(
                transcript_id,
                staged,
                {
                    "source": row["source"],
                    "source_alias": candidate.name,
                    "original_name": candidate.name,
                    "captured_at": row.get("recorded_at"),
                    "ingested_at": row.get("created_at"),
                    "duration_seconds": row.get("duration_seconds"),
                    "mime_type": mimetypes.guess_type(candidate.name)[0],
                    "backend": row.get("transcription_backend"),
                    "model": row.get("transcription_model"),
                    "quality_status": row.get("quality_status"),
                },
            )
        except Exception as exc:
            record_archive_backfill_failure(
                transcript_id, "archive_backfill_queue_error"
            )
            log.error(
                "Archive backfill failed for transcript id=%s: %s",
                transcript_id,
                type(exc).__name__,
            )


def _reconcile_published_archives(limit: int) -> None:
    """Validate local mirror receipts and safely requeue missing/tampered trios."""
    for row in get_published_archive_deliveries(limit=limit):
        delivery_id = int(row["id"])
        manifest_path = Path(str(row.get("destination_manifest_path") or ""))
        mirror_root = Path(cfg.archive.mirror_root).resolve()
        destinations = [
            Path(str(row.get(key)))
            for key in (
                "destination_audio_path",
                "destination_markdown_path",
                "destination_manifest_path",
            )
            if row.get(key)
        ]
        if any(
            not path.is_absolute()
            or not path.resolve().is_relative_to(mirror_root)
            for path in destinations
        ):
            mark_archive_delivery_rebuild_needed(
                delivery_id, "local_mirror_path_outside_root"
            )
            continue
        valid = validate_local_mirror_receipt(row)
        if valid:
            mark_archive_delivery_validated(delivery_id)
            continue
        try:
            preserve_invalid_local_mirror(row, cfg.archive.mirror_root)
            reason = (
                "local_mirror_missing"
                if not manifest_path.is_file()
                else "local_mirror_validation_failed"
            )
            mark_archive_delivery_rebuild_needed(delivery_id, reason)
        except Exception as exc:
            log.error(
                "Local mirror reconciliation failed for delivery id=%s: %s",
                delivery_id,
                type(exc).__name__,
            )


def _retry_waiting_for_files(limit: int) -> None:
    waiting = get_voice_memo_recordings_waiting_for_file(limit=limit)
    if not waiting:
        return
    log.info("Retrying %s recording(s) awaiting file download", len(waiting))
    refreshed = get_recordings_by_pk([int(row["recording_pk"]) for row in waiting])
    for row in waiting:
        pk = int(row["recording_pk"])
        recording = refreshed.get(pk)
        if recording is not None:
            if not upsert_voice_memo_recording(
                pk,
                label=recording.get("ZCUSTOMLABEL") or f"Recording {pk}",
                raw_path=str(recording.get("ZPATH") or ""),
                duration_seconds=(
                    float(recording.get("ZDURATION"))
                    if recording.get("ZDURATION") is not None
                    else None
                ),
                recorded_at=_recording_timestamp_utc(recording),
            ):
                continue
        else:
            recording = {
                "Z_PK": pk,
                "ZCUSTOMLABEL": row.get("label"),
                "ZPATH": row.get("raw_path"),
                "ZDURATION": row.get("duration_seconds"),
                "recorded_at": row.get("recorded_at"),
            }
        process_recording(recording, already_upserted=True)


def _retry_voice_memo_recordings(limit: int) -> None:
    """Retry due unlinked source rows, refreshing CloudRecordings metadata first."""
    retryable = get_voice_memo_recordings_for_retry(limit=limit)
    if not retryable:
        return
    log.info("Retrying %s due Voice Memo recording(s)", len(retryable))
    refreshed = get_recordings_by_pk([int(row["recording_pk"]) for row in retryable])
    for row in retryable:
        pk = int(row["recording_pk"])
        recording = refreshed.get(pk)
        if recording is None:
            recording = {
                "Z_PK": pk,
                "ZCUSTOMLABEL": row.get("label"),
                "ZPATH": row.get("raw_path"),
                "ZDURATION": row.get("duration_seconds"),
                "recorded_at": row.get("recorded_at"),
            }
        else:
            if not upsert_voice_memo_recording(
                pk,
                label=recording.get("ZCUSTOMLABEL") or f"Recording {pk}",
                raw_path=str(recording.get("ZPATH") or ""),
                duration_seconds=(
                    float(recording.get("ZDURATION"))
                    if recording.get("ZDURATION") is not None
                    else None
                ),
                recorded_at=_recording_timestamp_utc(recording),
            ):
                continue
        process_recording(recording, already_upserted=True)


def _retry_pending_routes(limit: int) -> None:
    pending = get_pending(limit=limit)
    for row in pending:
        log.info(
            "Retrying pending transcript id=%s (source=%s)",
            row["id"],
            row["source"],
        )
        try:
            classify_and_route(
                row["transcript"],
                source=row["source"],
                row_id=row["id"],
                duration_seconds=row.get("duration_seconds"),
                allow_maya=False,
            )
            if row["source"] == "iCloud":
                mark_voice_memo_routed_for_transcript(row["id"])
        except Exception as e:
            log.error("Retry failed for id=%s: %s", row["id"], type(e).__name__)


def _process_ingest_pass() -> None:
    operations = (
        lambda: _process_db_batch(get_new_recordings()),
        lambda: _retry_voice_memo_recordings(FILE_SCAN_PROCESS_LIMIT),
        lambda: _process_disk_backlog(FILE_SCAN_PROCESS_LIMIT),
        lambda: _retry_pending_routes(limit=5),
        lambda: _reconcile_archive_backfill(cfg.archive.delivery_batch_limit),
        lambda: _reconcile_published_archives(cfg.archive.delivery_batch_limit),
        _process_archive_outbox,
        _process_slack_outbox,
        _process_maya_outbox,
    )
    for operation in operations:
        try:
            operation()
        except Exception as exc:
            log.error("Ingest pass component failed: %s", type(exc).__name__)


# ===== Main =====


def main() -> None:
    log.info("=" * 60)
    log.info("Penny iCloud Watcher starting...")
    log.info("=" * 60)

    init_db()

    errors, warnings = check_dependencies()
    if warnings:
        for warning in warnings:
            log.warning("Startup warning: %s", warning)
    if errors:
        log.error("DEPENDENCY CHECK FAILED:")
        for error in errors:
            log.error("  - %s", error)
        log.error("Service may not function properly until these are fixed.")

    if not VOICE_MEMOS_DIR.exists():
        log.error("Voice Memos directory not found: %s", VOICE_MEMOS_DIR)
        sys.exit(1)

    log.info("  Watching: %s", VOICE_MEMOS_DIR)
    log.info("  Database: %s", CLOUDRECORDINGS_DB)
    log.info("  Poll interval: %ss", POLL_INTERVAL)
    log.info("  LLM model: %s", cfg.llm.model)
    log.info("  Last seen PK: %s", get_last_seen_pk())

    log.info("Running initial scan...")
    _ensure_voicememos_running()
    time.sleep(15)  # give VoiceMemos time to sync on startup before querying DB
    _process_ingest_pass()
    update_health_check()

    log.info("Starting main polling loop...")
    last_health_check = time.time()

    while True:
        try:
            time.sleep(POLL_INTERVAL)

            if time.time() - last_health_check > HEALTH_CHECK_INTERVAL:
                update_health_check()
                log.info(
                    "Health check: OK | PK=%s | Files: %s",
                    get_last_seen_pk(),
                    len(list(VOICE_MEMOS_DIR.glob("*.m4a"))),
                )
                last_health_check = time.time()

            _ensure_voicememos_running()
            _process_ingest_pass()

        except KeyboardInterrupt:
            log.info("Shutting down...")
            break
        except Exception as e:
            log.error("Error in poll loop: %s", e, exc_info=True)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
