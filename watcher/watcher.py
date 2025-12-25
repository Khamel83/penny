#!/usr/bin/env python3
"""
Penny Watcher - Watches for Voice Memos and sends them to Penny.

This script runs on the Mac mini, watching for new Voice Memos synced via iCloud,
transcribes them using mlx-whisper, and sends the transcription to Penny.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import urllib3
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# Suppress SSL warnings for self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuration
VOICE_MEMOS_PATH = Path.home() / "Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings"
PROCESSED_PATH = Path.home() / "penny/processed"
FAILED_PATH = Path.home() / "penny/failed"
PENNY_URL = os.environ.get("PENNY_URL", "http://${PENNY_URL:-localhost:8000}")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "mlx-community/whisper-large-v3-mlx")

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path.home() / "penny/watcher.log"),
    ],
)
logger = logging.getLogger(__name__)


def transcribe(audio_path: Path) -> str:
    """Transcribe an audio file using mlx-whisper."""
    logger.info(f"Transcribing: {audio_path.name}")

    try:
        # Use mlx_whisper Python API
        import mlx_whisper

        result = mlx_whisper.transcribe(
            str(audio_path),
            path_or_hf_repo=WHISPER_MODEL,
        )
        text = result.get("text", "").strip()
        logger.info(f"Transcription complete: {len(text)} characters")
        return text

    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        raise


def send_to_penny(text: str, source_file: str, timestamp: datetime) -> bool:
    """Send transcribed text to Penny."""
    logger.info(f"Sending to Penny: {source_file}")

    try:
        response = requests.post(
            f"{PENNY_URL}/api/ingest",
            json={
                "text": text,
                "source_file": source_file,
                "timestamp": timestamp.isoformat(),
            },
            timeout=30,
            verify=False,  # Skip SSL verification for self-signed certs
        )
        response.raise_for_status()

        result = response.json()
        classification = result.get("item", {}).get("classification", "unknown")
        logger.info(f"Sent successfully, classified as: {classification}")
        return True

    except requests.RequestException as e:
        logger.error(f"Failed to send to Penny: {e}")
        return False


def process_file(file_path: Path) -> bool:
    """Process a single audio file."""
    logger.info(f"Processing: {file_path.name}")

    try:
        # Get file creation time
        stat = file_path.stat()
        timestamp = datetime.fromtimestamp(stat.st_ctime)

        # Transcribe
        text = transcribe(file_path)
        if not text:
            logger.warning(f"Empty transcription for {file_path.name}")
            return False

        # Send to Penny
        if send_to_penny(text, file_path.name, timestamp):
            # Move to processed folder
            PROCESSED_PATH.mkdir(parents=True, exist_ok=True)
            dest = PROCESSED_PATH / file_path.name
            shutil.move(str(file_path), str(dest))
            logger.info(f"Moved to processed: {dest}")
            return True
        else:
            # Move to failed folder for retry
            FAILED_PATH.mkdir(parents=True, exist_ok=True)
            dest = FAILED_PATH / file_path.name
            shutil.move(str(file_path), str(dest))
            logger.warning(f"Moved to failed: {dest}")
            return False

    except Exception as e:
        logger.error(f"Error processing {file_path.name}: {e}")
        return False


class VoiceMemoHandler(FileSystemEventHandler):
    """Handle new Voice Memo files."""

    def __init__(self):
        self.processing = set()

    def on_created(self, event):
        """Called when a file is created."""
        if event.is_directory:
            return

        file_path = Path(event.src_path)

        # Only process audio files
        if file_path.suffix.lower() not in {".m4a", ".mp3", ".wav", ".caf"}:
            return

        # Avoid processing the same file multiple times
        if file_path in self.processing:
            return

        self.processing.add(file_path)

        try:
            # Wait a moment for file to finish writing
            time.sleep(2)

            # Check if file still exists and is complete
            if not file_path.exists():
                return

            process_file(file_path)

        finally:
            self.processing.discard(file_path)


def process_existing():
    """Process any existing files in the watch folder."""
    if not VOICE_MEMOS_PATH.exists():
        logger.warning(f"Voice Memos folder not found: {VOICE_MEMOS_PATH}")
        logger.info("Make sure iCloud Voice Memos sync is enabled")
        return

    for file_path in VOICE_MEMOS_PATH.glob("*.m4a"):
        process_file(file_path)


def retry_failed():
    """Retry any files in the failed folder."""
    failed_files = list(FAILED_PATH.glob("*.m4a"))
    if not failed_files:
        return

    logger.info(f"Retrying {len(failed_files)} failed files...")

    for file_path in failed_files:
        try:
            stat = file_path.stat()
            timestamp = datetime.fromtimestamp(stat.st_ctime)

            text = transcribe(file_path)
            if not text:
                continue

            if send_to_penny(text, file_path.name, timestamp):
                dest = PROCESSED_PATH / file_path.name
                shutil.move(str(file_path), str(dest))
                logger.info(f"Retry succeeded: {file_path.name}")
            else:
                logger.warning(f"Retry still failing: {file_path.name}")
        except Exception as e:
            logger.error(f"Retry error for {file_path.name}: {e}")


def main():
    """Main entry point."""
    logger.info("=" * 50)
    logger.info("Penny Watcher starting")
    logger.info(f"Watching: {VOICE_MEMOS_PATH}")
    logger.info(f"Penny URL: {PENNY_URL}")
    logger.info(f"Whisper model: {WHISPER_MODEL}")
    logger.info("=" * 50)

    # Ensure directories exist
    PROCESSED_PATH.mkdir(parents=True, exist_ok=True)
    FAILED_PATH.mkdir(parents=True, exist_ok=True)

    # Process any existing files first
    logger.info("Checking for existing files...")
    process_existing()

    # Check if watch folder exists
    if not VOICE_MEMOS_PATH.exists():
        logger.error(f"Voice Memos folder does not exist: {VOICE_MEMOS_PATH}")
        logger.error("Please enable iCloud Voice Memos sync in System Settings")
        sys.exit(1)

    # Start watching for new files
    event_handler = VoiceMemoHandler()
    observer = Observer()
    observer.schedule(event_handler, str(VOICE_MEMOS_PATH), recursive=False)
    observer.start()

    logger.info("Watching for new Voice Memos... Press Ctrl+C to stop")

    RETRY_INTERVAL = 300  # Retry failed files every 5 minutes
    last_retry = time.time()

    try:
        while True:
            time.sleep(1)

            # Periodically retry failed files
            if time.time() - last_retry >= RETRY_INTERVAL:
                retry_failed()
                last_retry = time.time()

    except KeyboardInterrupt:
        logger.info("Stopping watcher...")
        observer.stop()

    observer.join()
    logger.info("Watcher stopped")


if __name__ == "__main__":
    main()
