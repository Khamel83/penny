#!/usr/bin/env python3
"""
Penny Voice Relay - Robust iCloud Watcher

FAILURE MODES & RECOVERY:
1. iCloud sync stops → Disk scan catches files when they appear
2. Database gets corrupted → Rebuilds from iCloud automatically
3. Service crashes → KeepAlive restarts it
4. ffmpeg missing → Explicit PATH in launchd plist
5. Classifier API fails → Falls back to Inbox with raw transcript

HOW IT WORKS:
- Polls database every 60s for new entries (normal iCloud sync)
- Scans disk for unprocessed files (catches delayed/broken sync)
- Transcribes audio with Whisper (local, on-device)
- Classifies transcript with LLM → routes items to Apple Reminders lists
- Notifies via Telegram with categorized summary
"""
import os
import sys
import time
import hashlib
import logging
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from config import get_config
from classifier import classify
from reminders import add_reminder, add_note

cfg = get_config()

logging.basicConfig(
    level=getattr(logging, cfg.logging.level.upper(), logging.INFO),
    format="%(asctime)s - %(message)s",
)
log = logging.getLogger(__name__)

# Paths
VOICE_MEMOS_DIR = Path(os.environ.get(
    "VOICE_MEMOS_DIR",
    "~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings"
)).expanduser()
PROCESSED_FILE = Path("~/.penny/processed.txt").expanduser()
STATE_FILE = Path("~/.penny/last_pk.txt").expanduser()
CLOUDRECORDINGS_DB = VOICE_MEMOS_DIR / "CloudRecordings.db"
HEALTH_FILE = Path("~/.penny/health.txt").expanduser()

POLL_INTERVAL = cfg.voice_memos.poll_interval_seconds
HEALTH_CHECK_INTERVAL = 300
MAX_FILE_SIZE = cfg.voice_memos.max_file_size_mb * 1024 * 1024

SOURCE_EMOJI = {"iCloud": "☁️", "Shortcut": "📱"}
CATEGORY_EMOJI = {
    "groceries": "🛒",
    "errands": "🚗",
    "home": "🏠",
    "health": "🏥",
    "work": "💼",
    "kids": "👧",
    "inbox": "📝",
}


# ===== Dependencies =====

def check_dependencies():
    errors = []
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        if result.returncode != 0:
            errors.append("ffmpeg not working")
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
    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        errors.append("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
    if not cfg.openrouter_api_key:
        errors.append("OPENROUTER_API_KEY not set — items will fall back to Inbox")
    if CLOUDRECORDINGS_DB.exists():
        try:
            conn = sqlite3.connect(str(CLOUDRECORDINGS_DB))
            conn.execute("SELECT COUNT(*) FROM ZCLOUDRECORDING")
            conn.close()
        except Exception as e:
            errors.append(f"Database corrupted: {e}")
    return errors


# ===== Health =====

def update_health_check():
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat()
    db_count = 0
    if CLOUDRECORDINGS_DB.exists():
        try:
            conn = sqlite3.connect(str(CLOUDRECORDINGS_DB))
            cursor = conn.execute("SELECT COUNT(*) FROM ZCLOUDRECORDING")
            db_count = cursor.fetchone()[0]
            conn.close()
        except Exception:
            pass
    HEALTH_FILE.write_text(f"{now}|db_records:{db_count}|watcher_ok:1\n")


# ===== Deduplication =====

def get_file_hash(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def is_processed(path):
    if not PROCESSED_FILE.exists():
        return False
    return get_file_hash(path) in PROCESSED_FILE.read_text()


def mark_processed(path):
    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PROCESSED_FILE.open("a") as f:
        f.write(f"{get_file_hash(path)}\n")


# ===== State (last seen DB primary key) =====

def get_last_seen_pk():
    if STATE_FILE.exists():
        try:
            return int(STATE_FILE.read_text().strip())
        except Exception:
            return 0
    return 0


def set_last_seen_pk(pk):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(str(pk))


# ===== Transcription =====

def transcribe(path):
    import mlx_whisper
    log.info(f"Transcribing: {path}")
    result = mlx_whisper.transcribe(
        str(path),
        path_or_hf_repo=cfg.voice_memos.whisper_model,
    )
    return result["text"].strip()


# ===== Telegram =====

def send_telegram(message: str) -> bool:
    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        log.error("Telegram credentials not set")
        return False
    try:
        import requests
        resp = requests.post(
            f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage",
            json={"chat_id": cfg.telegram_chat_id, "text": message},
            timeout=30,
        )
        resp.raise_for_status()
        log.info("Telegram notification sent")
        return True
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False


def build_result_message(transcript: str, result: dict, source: str) -> str:
    emoji = SOURCE_EMOJI.get(source, "📱")
    excerpt = transcript[:200] + ("..." if len(transcript) > 200 else "")

    if result.get("skip"):
        return f"⏭️ Not a reminder ({emoji} {source}):\n\n📋 \"{excerpt}\""

    items = result.get("items", [])
    fallback = result.get("fallback", False)

    by_category: dict = {}
    for entry in items:
        by_category.setdefault(entry["category"], []).append(entry["item"])

    prefix = (
        f"⚠️ Classification failed — added to Inbox ({emoji} {source}):"
        if fallback
        else f"✅ {len(items)} item(s) added ({emoji} {source}):"
    )
    lines = [prefix, ""]
    for cat, cat_items in by_category.items():
        e = CATEGORY_EMOJI.get(cat, "📝")
        lines.append(f"  {e} {cat.capitalize()}: {', '.join(cat_items)}")
    lines += ["", f"📋 \"{excerpt}\""]
    return "\n".join(lines)


# ===== Pipeline =====

def classify_and_route(transcript: str, source: str = "iCloud") -> bool:
    """Classify transcript, add items to Reminders or Notes, send Telegram for reminders."""
    result = classify(transcript, cfg.openrouter_api_key, cfg.llm.model)

    if result.get("skip"):
        # Not a reminder — save to Apple Notes Penny folder, no Telegram
        add_note(transcript, folder_name="Penny", source=source)
    else:
        for entry in result.get("items", []):
            target_list = entry["category"].capitalize()
            if target_list not in cfg.apple_reminders.lists:
                target_list = cfg.apple_reminders.default_list
            add_reminder(entry["item"], target_list, cfg.apple_reminders.default_list)
        msg = build_result_message(transcript, result, source)
        send_telegram(msg)

    return True


# ===== Database polling =====

def get_new_recordings():
    if not CLOUDRECORDINGS_DB.exists():
        log.warning(f"Database not found: {CLOUDRECORDINGS_DB}")
        return []

    last_pk = get_last_seen_pk()
    try:
        conn = sqlite3.connect(str(CLOUDRECORDINGS_DB))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
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
    try:
        all_files = sorted(
            VOICE_MEMOS_DIR.glob("*.m4a"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        return [f for f in all_files if not is_processed(f)]
    except Exception as e:
        log.error(f"File scan failed: {e}")
        return []


# ===== Processing =====

def process_recording(recording):
    pk = recording["Z_PK"]
    label = recording.get("ZCUSTOMLABEL") or f"Recording {pk}"
    log.info(f"Processing {label} (PK={pk})")

    if recording.get("ZPATH"):
        audio_path = VOICE_MEMOS_DIR / recording["ZPATH"]
        if not audio_path.exists():
            log.warning(f"File in DB not found: {audio_path}")
            for f in VOICE_MEMOS_DIR.glob("*.m4a"):
                if recording["ZCUSTOMLABEL"] and f.name.startswith(
                    recording["ZCUSTOMLABEL"][:10].replace("-", "")
                ):
                    audio_path = f
                    break
    else:
        audio_path = None
        for f in VOICE_MEMOS_DIR.glob("*.m4a"):
            if recording["ZCUSTOMLABEL"] and recording["ZCUSTOMLABEL"] in f.name:
                audio_path = f
                break

    if not audio_path or not audio_path.exists():
        log.error(f"File not found for {label}")
        return False

    file_size = audio_path.stat().st_size
    if file_size > MAX_FILE_SIZE:
        log.warning(f"Skipping {label} ({file_size / (1024*1024):.1f}MB) — too large")
        mark_processed(audio_path)
        set_last_seen_pk(pk)
        return True

    if is_processed(audio_path):
        log.info(f"Already processed: {label}")
        set_last_seen_pk(pk)
        return True

    try:
        transcript = transcribe(audio_path)
        classify_and_route(transcript, source="iCloud")
        mark_processed(audio_path)
        set_last_seen_pk(pk)
        return True
    except Exception as e:
        log.error(f"Error processing {label}: {e}")
        return False


def process_file(audio_path):
    file_size = audio_path.stat().st_size
    if file_size > MAX_FILE_SIZE:
        log.warning(f"Skipping {audio_path.name} ({file_size / (1024*1024):.1f}MB) — too large")
        mark_processed(audio_path)
        return True

    log.info(f"Processing file: {audio_path.name} ({file_size / (1024*1024):.1f}MB)")

    if is_processed(audio_path):
        log.info(f"Already processed: {audio_path.name}")
        return True

    try:
        transcript = transcribe(audio_path)
        classify_and_route(transcript, source="iCloud")
        mark_processed(audio_path)
        return True
    except Exception as e:
        log.error(f"Error processing {audio_path.name}: {e}")
        return False


# ===== Main =====

def main():
    log.info("=" * 60)
    log.info("Penny iCloud Watcher starting...")
    log.info("=" * 60)

    errors = check_dependencies()
    if errors:
        log.error("DEPENDENCY CHECK FAILED:")
        for error in errors:
            log.error(f"  - {error}")
        log.error("Service will not function properly until these are fixed.")

    if not VOICE_MEMOS_DIR.exists():
        log.error(f"Voice Memos directory not found: {VOICE_MEMOS_DIR}")
        sys.exit(1)

    log.info(f"  Watching: {VOICE_MEMOS_DIR}")
    log.info(f"  Database: {CLOUDRECORDINGS_DB}")
    log.info(f"  Poll interval: {POLL_INTERVAL}s")
    log.info(f"  LLM model: {cfg.llm.model}")
    log.info(f"  Last seen PK: {get_last_seen_pk()}")

    # Initial scan
    log.info("Running initial scan...")
    recordings = get_new_recordings()
    if recordings:
        log.info(f"Found {len(recordings)} new recording(s) in database")
        for r in recordings:
            process_recording(r)

    unprocessed = scan_for_unprocessed_files()
    if unprocessed:
        log.info(f"Found {len(unprocessed)} unprocessed file(s) on disk")
        for f in unprocessed[: cfg.voice_memos.startup_process_limit]:
            process_file(f)

    update_health_check()

    # Main polling loop
    log.info("Starting main polling loop...")
    last_health_check = time.time()

    while True:
        try:
            time.sleep(POLL_INTERVAL)

            if time.time() - last_health_check > HEALTH_CHECK_INTERVAL:
                update_health_check()
                log.info(
                    f"Health check: OK | PK={get_last_seen_pk()} "
                    f"| Files: {len(list(VOICE_MEMOS_DIR.glob('*.m4a')))}"
                )
                last_health_check = time.time()

            recordings = get_new_recordings()
            if recordings:
                log.info(f"Found {len(recordings)} new recording(s)")
                for r in recordings:
                    process_recording(r)

            unprocessed = scan_for_unprocessed_files()
            if unprocessed:
                log.info(f"Found {len(unprocessed)} unprocessed file(s) on disk")
                for f in unprocessed[:3]:
                    process_file(f)

        except KeyboardInterrupt:
            log.info("Shutting down...")
            break
        except Exception as e:
            log.error(f"Error in poll loop: {e}", exc_info=True)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
