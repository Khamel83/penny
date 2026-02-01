#!/usr/bin/env python3
"""
Penny Voice Relay
Transcribes voice memos and pushes to OpenClaw.
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
OPENCLAW_URL = os.environ.get("OPENCLAW_URL", "http://100.126.13.70:18789")
OPENCLAW_TOKEN = os.environ.get("OPENCLAW_TOKEN", "")
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


def push_to_openclaw(transcript):
    """POST transcript to OpenClaw webhook."""
    log.info(f"Pushing to OpenClaw: {transcript[:50]}...")
    try:
        resp = requests.post(
            f"{OPENCLAW_URL}/hooks/agent",
            headers={"Authorization": f"Bearer {OPENCLAW_TOKEN}"},
            json={
                "message": f"Voice memo: {transcript}",
                "name": "Penny",
            },
            timeout=30
        )
        resp.raise_for_status()
        log.info("Pushed successfully")
    except Exception as e:
        log.error(f"Failed to push: {e}")


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
            push_to_openclaw(transcript)
            mark_processed(path)
        except Exception as e:
            log.error(f"Error processing {path}: {e}")


def main():
    if not VOICE_MEMOS_DIR.exists():
        log.error(f"Voice Memos directory not found: {VOICE_MEMOS_DIR}")
        sys.exit(1)

    if not OPENCLAW_TOKEN:
        log.warning("OPENCLAW_TOKEN not set - webhooks may fail")

    log.info(f"Watching: {VOICE_MEMOS_DIR}")
    log.info(f"OpenClaw: {OPENCLAW_URL}")

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
