#!/usr/bin/env python3
"""
Penny Voice Relay
Transcribes voice memos from iCloud and sends to Telegram.
"""
import os
import sys
import time
import hashlib
import logging
import requests
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

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
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": f"🎤 Voice memo:\n\n{transcript}",
                "parse_mode": "HTML"
            },
            timeout=30
        )
        resp.raise_for_status()
        log.info("Sent successfully to Telegram")
    except Exception as e:
        log.error(f"Failed to send: {e}")


class VoiceMemoHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        if not event.src_path.endswith(('.m4a', '.wav', '.mp3')):
            return
        # Wait for file to finish writing
        time.sleep(2)
        self.process(event.src_path)

    def process(self, path):
        if is_processed(path):
            log.info(f"Already processed: {path}")
            return
        try:
            transcript = transcribe(path)
            send_to_telegram(transcript)
            mark_processed(path)
        except Exception as e:
            log.error(f"Error processing {path}: {e}")


def main():
    if not VOICE_MEMOS_DIR.exists():
        log.error(f"Voice Memos directory not found: {VOICE_MEMOS_DIR}")
        sys.exit(1)

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set - messages will fail")

    log.info(f"Watching: {VOICE_MEMOS_DIR}")
    log.info(f"Telegram chat: {TELEGRAM_CHAT_ID}")

    observer = Observer()
    observer.schedule(VoiceMemoHandler(), str(VOICE_MEMOS_DIR), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
