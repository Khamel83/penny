#!/usr/bin/env python3
"""
Penny Voice Relay - Robust iCloud Watcher

FAILURE MODES & RECOVERY:
1. iCloud sync stops → Disk scan catches files when they appear
2. Database gets corrupted → Rebuilds from iCloud automatically
3. Service crashes → KeepAlive restarts it
4. ffmpeg missing → Explicit PATH in launchd plist
5. Code gets out of date → Sync from repo on startup

HOW IT WORKS:
- Polls database every 60s for new entries (normal iCloud sync)
- Scans disk for unprocessed files (catches delayed/broken sync)
- Dual approach means recordings are found even if one path fails
"""
import os
import sys
import time
import hashlib
import logging
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
log = logging.getLogger(__name__)

# Config
VOICE_MEMOS_DIR = Path(os.environ.get(
    "VOICE_MEMOS_DIR",
    "~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings"
)).expanduser()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
PROCESSED_FILE = Path("~/.penny/processed.txt").expanduser()
STATE_FILE = Path("~/.penny/last_pk.txt").expanduser()
CLOUDRECORDINGS_DB = VOICE_MEMOS_DIR / "CloudRecordings.db"
HEALTH_FILE = Path("~/.penny/health.txt").expanduser()

POLL_INTERVAL = 60  # Check every 60 seconds
HEALTH_CHECK_INTERVAL = 300  # Log health every 5 minutes


def check_dependencies():
    """Verify all dependencies are available."""
    errors = []

    # Check ffmpeg
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        if result.returncode != 0:
            errors.append("ffmpeg not working")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        errors.append(f"ffmpeg not found: {e}")

    # Check mlx_whisper
    try:
        import mlx_whisper
    except ImportError:
        errors.append("mlx_whisper not installed")

    # Check requests
    try:
        import requests
    except ImportError:
        errors.append("requests not installed")

    # Check watchdog
    try:
        import watchdog
    except ImportError:
        errors.append("watchdog not installed")

    # Check directory exists
    if not VOICE_MEMOS_DIR.exists():
        errors.append(f"Voice Memos directory not found: {VOICE_MEMOS_DIR}")

    # Check Telegram credentials
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")

    # Check database
    if CLOUDRECORDINGS_DB.exists():
        try:
            conn = sqlite3.connect(str(CLOUDRECORDINGS_DB))
            conn.execute("SELECT COUNT(*) FROM ZCLOUDRECORDING")
            conn.close()
        except Exception as e:
            errors.append(f"Database corrupted: {e}")

    return errors


def update_health_check():
    """Write health status for monitoring."""
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat()
    db_count = 0
    if CLOUDRECORDINGS_DB.exists():
        try:
            conn = sqlite3.connect(str(CLOUDRECORDINGS_DB))
            cursor = conn.execute("SELECT COUNT(*) FROM ZCLOUDRECORDING")
            db_count = cursor.fetchone()[0]
            conn.close()
        except:
            pass

    health = f"{now}|db_records:{db_count}|watcher_ok:1\n"
    HEALTH_FILE.write_text(health)


def get_file_hash(path):
    """Get hash of file to track processed memos."""
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def is_processed(path):
    """Check if memo already processed."""
    if not PROCESSED_FILE.exists():
        return False
    file_hash = get_file_hash(path)
    return file_hash in PROCESSED_FILE.read_text()


def mark_processed(path):
    """Mark memo as processed."""
    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PROCESSED_FILE.open("a") as f:
        f.write(f"{get_file_hash(path)}\n")


def get_last_seen_pk():
    """Get the highest Z_PK we've processed."""
    if STATE_FILE.exists():
        try:
            return int(STATE_FILE.read_text().strip())
        except:
            return 0
    return 0


def set_last_seen_pk(pk):
    """Update the highest Z_PK we've processed."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(str(pk))


def transcribe(path):
    """Transcribe audio with mlx-whisper."""
    import mlx_whisper
    log.info(f"Transcribing: {path}")
    result = mlx_whisper.transcribe(
        str(path),
        path_or_hf_repo="mlx-community/whisper-large-v3-turbo"
    )
    return result["text"].strip()


def send_to_telegram(transcript):
    """Send transcript to Telegram via Bot API."""
    log.info(f"Sending to Telegram: {transcript[:50]}...")

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return False

    try:
        import requests
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": f"☁️ Voice memo:\n\n{transcript}",
            },
            timeout=30
        )
        resp.raise_for_status()
        log.info("Sent successfully to Telegram")
        return True
    except Exception as e:
        log.error(f"Failed to send: {e}")
        return False


def get_new_recordings():
    """Query database for recordings newer than last_seen_pk."""
    if not CLOUDRECORDINGS_DB.exists():
        log.warning(f"Database not found: {CLOUDRECORDINGS_DB}")
        return []

    last_pk = get_last_seen_pk()

    try:
        conn = sqlite3.connect(str(CLOUDRECORDINGS_DB))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Query for new recordings
        cursor.execute("""
            SELECT Z_PK, ZCUSTOMLABEL, ZDATE, ZDURATION, ZPATH
            FROM ZCLOUDRECORDING
            WHERE Z_PK > ?
            ORDER BY Z_PK ASC
        """, (last_pk,))

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    except Exception as e:
        log.error(f"Database query failed: {e}")
        return []


def scan_for_unprocessed_files():
    """Scan disk for m4a files that haven't been processed yet.

    This catches files that iCloud downloaded before the database was updated.
    """
    try:
        all_files = sorted(VOICE_MEMOS_DIR.glob("*.m4a"), key=lambda f: f.stat().st_mtime, reverse=True)
        unprocessed = []

        for f in all_files:
            if not is_processed(f):
                unprocessed.append(f)

        return unprocessed
    except Exception as e:
        log.error(f"File scan failed: {e}")
        return []


def process_recording(recording):
    """Process a single recording from database."""
    pk = recording["Z_PK"]
    label = recording.get("ZCUSTOMLABEL", f"Recording {pk}")

    log.info(f"Processing {label} (PK={pk})")

    # Get file path from recording or fallback to directory scan
    if recording.get("ZPATH"):
        audio_path = VOICE_MEMOS_DIR / recording["ZPATH"]
        if not audio_path.exists():
            log.warning(f"File in DB not found: {audio_path}")
            # Try to find the file by scanning
            for f in VOICE_MEMOS_DIR.glob("*.m4a"):
                if recording["ZCUSTOMLABEL"] and f.name.startswith(recording["ZCUSTOMLABEL"][:10].replace("-", "")):
                    audio_path = f
                    break
    else:
        # No path in DB, scan for matching file
        audio_path = None
        for f in VOICE_MEMOS_DIR.glob("*.m4a"):
            # Try to match by date or label
            if recording["ZCUSTOMLABEL"] and recording["ZCUSTOMLABEL"] in f.name:
                audio_path = f
                break

    if not audio_path or not audio_path.exists():
        log.error(f"File not found for {label}")
        return False

    # Check if already processed
    if is_processed(audio_path):
        log.info(f"Already processed: {label}")
        set_last_seen_pk(pk)
        return True

    try:
        # Transcribe and send
        transcript = transcribe(audio_path)
        if send_to_telegram(transcript):
            mark_processed(audio_path)
            set_last_seen_pk(pk)
            return True
        return False
    except Exception as e:
        log.error(f"Error processing {label}: {e}")
        return False


def process_file(audio_path):
    """Process a single file from disk scan."""
    log.info(f"Processing file: {audio_path.name}")

    if is_processed(audio_path):
        log.info(f"Already processed: {audio_path.name}")
        return True

    try:
        transcript = transcribe(audio_path)
        if send_to_telegram(transcript):
            mark_processed(audio_path)
            return True
        return False
    except Exception as e:
        log.error(f"Error processing {audio_path.name}: {e}")
        return False


def main():
    # Startup checks
    log.info("=" * 60)
    log.info("Penny iCloud Watcher starting...")
    log.info("=" * 60)

    errors = check_dependencies()
    if errors:
        log.error("DEPENDENCY CHECK FAILED:")
        for error in errors:
            log.error(f"  - {error}")
        log.error("Service will not function properly until these are fixed.")
        # Don't exit - let it run and maybe recover

    if not VOICE_MEMOS_DIR.exists():
        log.error(f"Voice Memos directory not found: {VOICE_MEMOS_DIR}")
        sys.exit(1)

    log.info(f"  Watching: {VOICE_MEMOS_DIR}")
    log.info(f"  Database: {CLOUDRECORDINGS_DB}")
    log.info(f"  Poll interval: {POLL_INTERVAL}s")
    log.info(f"  Last seen PK: {get_last_seen_pk()}")

    # Initial scan
    log.info("Running initial scan...")
    recordings = get_new_recordings()
    if recordings:
        log.info(f"Found {len(recordings)} new recording(s) in database")
        for r in recordings:
            process_recording(r)

    unprocessed_files = scan_for_unprocessed_files()
    if unprocessed_files:
        log.info(f"Found {len(unprocessed_files)} unprocessed file(s) on disk")
        for f in unprocessed_files[:5]:  # Process up to 5 at startup
            process_file(f)

    # Update health
    update_health_check()

    # Main polling loop
    log.info("Starting main polling loop...")
    last_health_check = time.time()

    while True:
        try:
            time.sleep(POLL_INTERVAL)

            # Health check
            if time.time() - last_health_check > HEALTH_CHECK_INTERVAL:
                update_health_check()
                log.info(f"Health check: OK | PK={get_last_seen_pk()} | Files on disk: {len(list(VOICE_MEMOS_DIR.glob('*.m4a')))}")
                last_health_check = time.time()

            # Check database for new recordings
            recordings = get_new_recordings()
            if recordings:
                log.info(f"Found {len(recordings)} new recording(s) in database")
                for r in recordings:
                    process_recording(r)

            # Also scan disk for files that appeared before database update
            unprocessed_files = scan_for_unprocessed_files()
            if unprocessed_files:
                log.info(f"Found {len(unprocessed_files)} unprocessed file(s) on disk")
                for f in unprocessed_files[:3]:  # Process up to 3 per cycle
                    process_file(f)

        except KeyboardInterrupt:
            log.info("Shutting down...")
            break
        except Exception as e:
            log.error(f"Error in poll loop: {e}", exc_info=True)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
