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
from core import classify_and_route, get_file_hash, is_processed, mark_processed, setup_logging

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
        errors.append("Telegram is enabled but TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID is missing")

    if not cfg.openrouter_api_key:
        warnings.append("OPENROUTER_API_KEY not set — classification falls back to Inbox")

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


def update_health_check() -> None:
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat()
    HEALTH_FILE.write_text(
        f"{now}|db_records:{_db_recordings_count()}|watcher_ok:1\n",
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


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def scan_for_unprocessed_files() -> List[Path]:
    try:
        all_files = list(VOICE_MEMOS_DIR.glob("*.m4a"))
    except Exception as e:
        log.error("File scan failed: %s", e)
        return []

    all_files.sort(key=_safe_mtime, reverse=True)
    unprocessed: List[Path] = []
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

        if not is_processed(file_hash):
            unprocessed.append(audio_file)

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
            if label in name or (normalized_prefix and name.startswith(normalized_prefix)):
                return candidate

    return None


def _process_audio_file(audio_path: Path) -> bool:
    file_size = audio_path.stat().st_size
    if file_size > MAX_FILE_SIZE:
        log.warning(
            "Skipping %s (%.1fMB) — too large",
            audio_path.name,
            file_size / (1024 * 1024),
        )
        mark_processed(get_file_hash(audio_path))
        return True

    file_hash = get_file_hash(audio_path)
    if is_processed(file_hash):
        log.info("Already processed: %s", audio_path.name)
        return True

    transcript = transcribe(audio_path)
    classify_and_route(transcript, source="iCloud")
    mark_processed(file_hash)
    return True


def process_recording(recording: Dict[str, Any]) -> bool:
    pk = int(recording["Z_PK"])
    label = recording.get("ZCUSTOMLABEL") or f"Recording {pk}"
    log.info("Processing %s (PK=%s)", label, pk)

    audio_path = _find_audio_path_for_recording(recording)
    if not audio_path or not audio_path.exists():
        log.error("File not found for %s (PK=%s); will retry via later DB poll or disk scan", label, pk)
        return False

    try:
        _process_audio_file(audio_path)
        set_last_seen_pk(pk)
        return True
    except Exception as e:
        log.error("Error processing %s (PK=%s): %s", label, pk, e, exc_info=True)
        return False


def process_file(audio_path: Path) -> bool:
    try:
        log.info(
            "Processing file: %s (%.1fMB)",
            audio_path.name,
            audio_path.stat().st_size / (1024 * 1024),
        )
        return _process_audio_file(audio_path)
    except FileNotFoundError:
        log.warning("File disappeared before processing: %s", audio_path)
        return False
    except Exception as e:
        log.error("Error processing %s: %s", audio_path.name, e, exc_info=True)
        return False


def _trigger_icloud_sync() -> None:
    """Open VoiceMemos in the background to force iCloud to sync new recordings."""
    try:
        subprocess.run(
            ["open", "-g", "-a", "VoiceMemos"],
            check=False,
            capture_output=True,
        )
    except Exception as e:
        log.warning("Could not trigger VoiceMemos sync: %s", e)


def _process_db_batch(recordings: List[Dict[str, Any]]) -> None:
    if not recordings:
        return
    log.info("Found %s new recording(s)", len(recordings))
    for recording in recordings[:FILE_SCAN_PROCESS_LIMIT]:
        process_recording(recording)
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
    for audio_file in unprocessed[:limit]:
        process_file(audio_file)


# ===== Main =====

def main() -> None:
    log.info("=" * 60)
    log.info("Penny iCloud Watcher starting...")
    log.info("=" * 60)

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
    _trigger_icloud_sync()
    time.sleep(15)  # give VoiceMemos time to sync on startup before querying DB
    _process_db_batch(get_new_recordings())
    _process_disk_backlog(FILE_SCAN_PROCESS_LIMIT)
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

            _trigger_icloud_sync()
            _process_db_batch(get_new_recordings())
            _process_disk_backlog(FILE_SCAN_PROCESS_LIMIT)

        except KeyboardInterrupt:
            log.info("Shutting down...")
            break
        except Exception as e:
            log.error("Error in poll loop: %s", e, exc_info=True)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
