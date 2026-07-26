#!/usr/bin/env python3
"""Poll iCloud Voice Memos, transcribe new recordings, and route them through Penny."""

from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

from config import get_config
from core import classify_and_route, get_file_hash, setup_logging
from slack_delivery import process_pending_slack_deliveries
from transcript_log import (
    get_transcript_by_hash,
    get_voice_memo_health,
    get_voice_memo_recordings_waiting_for_file,
    init_db,
    insert_transcript,
    is_already_logged,
    get_pending,
    link_voice_memo_transcript,
    mark_voice_memo_failed,
    mark_voice_memo_file_seen,
    mark_voice_memo_routed,
    mark_voice_memo_routed_for_transcript,
    mark_voice_memo_waiting_for_file,
    update_transcript_stages,
    upsert_voice_memo_recording,
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


def _transcripts_pending() -> int:
    pending = get_pending(limit=1)
    return len(pending)


def update_health_check() -> None:
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat()
    vm = 1 if _voicememos_running() else 0
    pending = _transcripts_pending()
    vm_health = get_voice_memo_health()
    HEALTH_FILE.write_text(
        (
            f"{now}|db_records:{_db_recordings_count()}|watcher_ok:1|voicememos:{vm}|"
            f"pending:{pending}|latest_recording_pk:{vm_health['latest_recording_pk']}|"
            f"awaiting_file:{vm_health['awaiting_file_count']}|"
            f"voice_memo_failed:{vm_health['failed_count']}\n"
        ),
        encoding="utf-8",
    )


# ===== State (last seen DB primary key) =====


def get_last_seen_pk() -> int:
    if not STATE_FILE.exists():
        return 0
    try:
        return int(STATE_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def set_last_seen_pk(pk: int) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(str(pk), encoding="utf-8")


# ===== Transcription =====


def transcribe(path: Path) -> str:
    import mlx_whisper

    log.info("Transcribing: %s", path)
    result = mlx_whisper.transcribe(
        str(path),
        path_or_hf_repo=cfg.voice_memos.whisper_model,
    )
    return str(result.get("text", "")).strip()


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

        if not is_already_logged(file_hash):
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
) -> bool:
    if file_hash is None:
        file_hash = get_file_hash(audio_path)

    file_size = audio_path.stat().st_size
    if file_size > MAX_FILE_SIZE:
        log.warning(
            "Skipping %s (%.1fMB) — too large",
            audio_path.name,
            file_size / (1024 * 1024),
        )
        insert_transcript(
            content_hash=file_hash,
            source="iCloud",
            transcript="(skipped: file too large)",
            audio_path=str(audio_path),
            duration_seconds=duration_seconds,
            ingest_state="skipped_too_large",
            file_seen_at=datetime.now().isoformat(),
        )
        if recording_pk is not None:
            mark_voice_memo_failed(recording_pk, "file too large")
        return True

    existing = get_transcript_by_hash(file_hash)
    if existing is not None:
        log.info("Already logged: %s", audio_path.name)
        if recording_pk is not None:
            mark_voice_memo_file_seen(recording_pk, str(audio_path))
            link_voice_memo_transcript(
                recording_pk,
                transcript_row_id=int(existing["id"]),
                content_hash=file_hash,
                audio_path=str(audio_path),
                routed=existing.get("status") == "routed",
            )
        return True

    file_seen_at = datetime.now().isoformat()
    transcription_started_at = datetime.now().isoformat()
    transcript = transcribe(audio_path)
    transcription_completed_at = datetime.now().isoformat()

    row_id = insert_transcript(
        content_hash=file_hash,
        source="iCloud",
        transcript=transcript,
        audio_path=str(audio_path),
        duration_seconds=duration_seconds,
        ingest_state="transcribed",
        file_seen_at=file_seen_at,
        transcription_started_at=transcription_started_at,
        transcription_completed_at=transcription_completed_at,
    )
    if row_id is not None:
        if recording_pk is not None:
            link_voice_memo_transcript(
                recording_pk,
                transcript_row_id=row_id,
                content_hash=file_hash,
                audio_path=str(audio_path),
            )
        _process_slack_outbox()
        classify_and_route(
            transcript,
            source="iCloud",
            row_id=row_id,
            duration_seconds=duration_seconds,
        )
        update_transcript_stages(row_id, ingest_state="routed")
        if recording_pk is not None:
            mark_voice_memo_routed(recording_pk)
    return True


def process_recording(recording: Dict[str, Any]) -> bool:
    pk = int(recording["Z_PK"])
    label = recording.get("ZCUSTOMLABEL") or f"Recording {pk}"
    raw_path = str(recording.get("ZPATH") or "")
    duration_seconds = (
        float(recording.get("ZDURATION"))
        if recording.get("ZDURATION") is not None
        else None
    )
    upsert_voice_memo_recording(
        pk,
        label=label,
        raw_path=raw_path,
        duration_seconds=duration_seconds,
    )
    log.info("Processing %s (PK=%s)", label, pk)

    audio_path = _find_audio_path_for_recording(recording)
    if not audio_path or not audio_path.exists():
        log.error(
            "File not found for %s (PK=%s); will retry via later DB poll or disk scan",
            label,
            pk,
        )
        mark_voice_memo_waiting_for_file(pk, "file not downloaded yet")
        return False

    try:
        mark_voice_memo_file_seen(pk, str(audio_path))
        _process_audio_file(
            audio_path,
            duration_seconds=duration_seconds,
            recording_pk=pk,
        )
        return True
    except Exception as e:
        mark_voice_memo_failed(pk, str(e))
        log.error("Error processing %s (PK=%s): %s", label, pk, e, exc_info=True)
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
    """Check if VoiceMemos is running; launch it if not (required for CloudKit sync)."""
    try:
        result = subprocess.run(
            ["pgrep", "-x", "VoiceMemos"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return
        log.warning("VoiceMemos not running — launching for CloudKit sync")
        subprocess.run(
            ["open", "-g", "-a", "VoiceMemos"],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except Exception as e:
        log.warning("Could not check/launch VoiceMemos: %s", e)


def _process_db_batch(recordings: List[Dict[str, Any]]) -> None:
    if not recordings:
        return
    log.info("Found %s new recording(s)", len(recordings))
    max_registered_pk = get_last_seen_pk()
    for recording in recordings[:FILE_SCAN_PROCESS_LIMIT]:
        pk = int(recording["Z_PK"])
        upsert_voice_memo_recording(
            pk,
            label=recording.get("ZCUSTOMLABEL") or f"Recording {pk}",
            raw_path=str(recording.get("ZPATH") or ""),
            duration_seconds=(
                float(recording.get("ZDURATION"))
                if recording.get("ZDURATION") is not None
                else None
            ),
        )
        max_registered_pk = max(max_registered_pk, pk)
        process_recording(recording)
    if max_registered_pk > get_last_seen_pk():
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
        delivered = process_pending_slack_deliveries(limit=20)
        if delivered:
            log.info("Delivered %s transcript(s) to Slack", delivered)
    except Exception as e:
        log.error("Slack outbox processing failed: %s", e, exc_info=True)


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
            upsert_voice_memo_recording(
                pk,
                label=recording.get("ZCUSTOMLABEL") or f"Recording {pk}",
                raw_path=str(recording.get("ZPATH") or ""),
                duration_seconds=(
                    float(recording.get("ZDURATION"))
                    if recording.get("ZDURATION") is not None
                    else None
                ),
            )
        else:
            recording = {
                "Z_PK": pk,
                "ZCUSTOMLABEL": row.get("label"),
                "ZPATH": row.get("raw_path"),
                "ZDURATION": row.get("duration_seconds"),
            }
        process_recording(
            recording
        )


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
    _process_db_batch(get_new_recordings())
    _retry_waiting_for_files(FILE_SCAN_PROCESS_LIMIT)
    _process_disk_backlog(FILE_SCAN_PROCESS_LIMIT)
    _process_slack_outbox()
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
            _process_db_batch(get_new_recordings())
            _retry_waiting_for_files(FILE_SCAN_PROCESS_LIMIT)
            _process_disk_backlog(FILE_SCAN_PROCESS_LIMIT)
            _process_slack_outbox()

            # Retry any transcripts that failed routing
            pending = get_pending(limit=5)
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
                    )
                    update_transcript_stages(row["id"], ingest_state="routed")
                    if row["source"] == "iCloud":
                        mark_voice_memo_routed_for_transcript(row["id"])
                except Exception as e:
                    log.error("Retry failed for id=%s: %s", row["id"], e)
            _process_slack_outbox()

        except KeyboardInterrupt:
            log.info("Shutting down...")
            break
        except Exception as e:
            log.error("Error in poll loop: %s", e, exc_info=True)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
