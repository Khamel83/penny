#!/usr/bin/env python3
"""
Penny Voice Relay - Robust iCloud Watcher

POLLING APPROACH for reliability:
- Polls CloudRecordings database every 60 seconds for new entries
- Does NOT rely on filesystem events (unreliable with iCloud)
- Works with native Voice Memos app on Apple Watch/iPhone

The filesystem watch approach fails because:
1. iCloud writes files before syncing metadata
2. Files can appear hours after the database entry
3. The bird daemon can stall and not push updates

Database polling works because:
1. Database entry is created when iCloud acknowledges the recording
2. We can check for new Z_PK entries (recording IDs)
3. We track the highest Z_PK we've seen
"""
import os
import sys
import time
import hashlib
import logging
import sqlite3
from pathlib import Path

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

POLL_INTERVAL = 60  # Check every 60 seconds


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
        return int(STATE_FILE.read_text().strip())
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
        return

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
    except Exception as e:
        log.error(f"Failed to send: {e}")


def get_new_recordings():
    """Query database for recordings newer than last_seen_pk."""
    if not CLOUDRECORDINGS_DB.exists():
        log.error(f"Database not found: {CLOUDRECORDINGS_DB}")
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


def wait_for_file(recording, timeout=300):
    """Wait for the actual audio file to appear (can be delayed after DB entry)."""
    if not recording.get("ZPATH"):
        return None

    audio_path = VOICE_MEMOS_DIR / recording["ZPATH"]

    start = time.time()
    while time.time() - start < timeout:
        if audio_path.exists():
            # Wait for file to finish writing (check size stability)
            size1 = audio_path.stat().st_size
            time.sleep(2)
            size2 = audio_path.stat().st_size
            if size1 == size2 and size2 > 0:
                return audio_path
        time.sleep(5)

    log.warning(f"Timeout waiting for file: {audio_path}")
    return None


def process_recording(recording):
    """Process a single recording."""
    pk = recording["Z_PK"]
    label = recording.get("ZCUSTOMLABEL", f"Recording {pk}")

    log.info(f"Processing {label} (PK={pk})")

    # Wait for file to appear
    audio_path = wait_for_file(recording)
    if not audio_path:
        log.error(f"File never appeared for {label}")
        return False

    # Check if already processed
    if is_processed(audio_path):
        log.info(f"Already processed: {label}")
        set_last_seen_pk(pk)
        return True

    try:
        # Transcribe and send
        transcript = transcribe(audio_path)
        send_to_telegram(transcript)
        mark_processed(audio_path)
        set_last_seen_pk(pk)
        return True
    except Exception as e:
        log.error(f"Error processing {label}: {e}")
        return False


def main():
    if not VOICE_MEMOS_DIR.exists():
        log.error(f"Voice Memos directory not found: {VOICE_MEMOS_DIR}")
        sys.exit(1)

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set - messages will fail")

    log.info(f"Penny iCloud Watcher (polling mode)")
    log.info(f"  Watching: {VOICE_MEMOS_DIR}")
    log.info(f"  Database: {CLOUDRECORDINGS_DB}")
    log.info(f"  Poll interval: {POLL_INTERVAL}s")
    log.info(f"  Last seen PK: {get_last_seen_pk()}")

    # Initial query to see current state
    recordings = get_new_recordings()
    if recordings:
        log.info(f"Found {len(recordings)} recordings not yet processed")
        for r in recordings:
            process_recording(r)

    # Main polling loop
    while True:
        try:
            time.sleep(POLL_INTERVAL)
            recordings = get_new_recordings()

            if recordings:
                log.info(f"Found {len(recordings)} new recording(s)")
                for r in recordings:
                    process_recording(r)
            else:
                log.debug("No new recordings")

        except KeyboardInterrupt:
            log.info("Shutting down...")
            break
        except Exception as e:
            log.error(f"Error in poll loop: {e}")
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
