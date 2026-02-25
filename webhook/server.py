#!/usr/bin/env python3
"""
Penny Server - Hybrid Approach

Handles BOTH:
1. iCloud sync: watches Voice Memos directory for new files
2. Webhook: accepts direct uploads from iOS Shortcuts

This way if iCloud sync fails, the webhook still works.
Run as a launchd service on macmini.
"""
import os
import sys
import time
import hashlib
import tempfile
import logging
import threading
from pathlib import Path
from flask import Flask, request, jsonify
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# Config
VOICE_MEMOS_DIR = Path(os.environ.get(
    "VOICE_MEMOS_DIR",
    "~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings"
)).expanduser()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
PROCESSED_FILE = Path("~/.penny/processed.txt").expanduser()
WEBHOOK_PROCESSED_FILE = Path("~/.penny/processed_webhook.txt").expanduser()


def get_file_hash(path):
    """Get hash of file to track processed memos."""
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def is_processed(path, processed_file=PROCESSED_FILE):
    """Check if memo already processed."""
    if not processed_file.exists():
        return False
    file_hash = get_file_hash(path)
    return file_hash in processed_file.read_text()


def mark_processed(path, processed_file=PROCESSED_FILE):
    """Mark memo as processed."""
    processed_file.parent.mkdir(parents=True, exist_ok=True)
    with processed_file.open("a") as f:
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


def send_to_telegram(transcript, source="iCloud"):
    """Send transcript to Telegram via Bot API."""
    log.info(f"Sending to Telegram ({source}): {transcript[:50]}...")

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return

    try:
        emoji = "☁️" if source == "iCloud" else "📱"
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": f"{emoji} Voice memo ({source}):\n\n{transcript}",
            },
            timeout=30
        )
        resp.raise_for_status()
        log.info("Sent successfully to Telegram")
    except Exception as e:
        log.error(f"Failed to send: {e}")


# ===== Flask Webhook Routes =====

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "service": "penny-hybrid",
        "iCloud_watching": str(VOICE_MEMOS_DIR),
        "telegram_configured": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
    })


@app.route('/upload', methods=['POST'])
def upload():
    """Receive audio file from iOS Shortcut, transcribe, send to Telegram."""
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file"}), 400

    audio_file = request.files['audio']
    log.info(f"Webhook: Received audio: {audio_file.filename}")

    with tempfile.NamedTemporaryFile(suffix='.m4a', delete=False) as f:
        audio_file.save(f.name)
        temp_path = f.name

    try:
        # Check if already processed (webhook tracking)
        file_hash = get_file_hash(temp_path)
        if is_processed(temp_path, WEBHOOK_PROCESSED_FILE):
            log.info("Webhook: Already processed this file")
            return jsonify({"status": "ok", "message": "already processed"})

        # Transcribe
        transcript = transcribe(temp_path)
        log.info(f"Webhook: Transcript: {transcript[:100]}...")

        # Send to Telegram
        send_to_telegram(transcript, source="Shortcut")

        # Mark as processed
        mark_processed(temp_path, WEBHOOK_PROCESSED_FILE)

        return jsonify({
            "status": "ok",
            "transcript": transcript[:200],
            "transcript_length": len(transcript)
        })

    except Exception as e:
        log.error(f"Webhook: Error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        os.unlink(temp_path)


# ===== iCloud Watcher =====

class VoiceMemoHandler(FileSystemEventHandler):
    """Handles new voice memos from iCloud sync."""

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
            log.info(f"iCloud: Already processed: {path}")
            return
        try:
            log.info(f"iCloud: New file detected: {path}")
            transcript = transcribe(path)
            send_to_telegram(transcript, source="iCloud")
            mark_processed(path)
        except Exception as e:
            log.error(f"iCloud: Error processing {path}: {e}")


def start_icloud_watcher():
    """Start watching for iCloud voice memos."""
    if not VOICE_MEMOS_DIR.exists():
        log.error(f"iCloud: Voice Memos directory not found: {VOICE_MEMOS_DIR}")
        return

    log.info(f"iCloud: Watching: {VOICE_MEMOS_DIR}")
    observer = Observer()
    observer.schedule(VoiceMemoHandler(), str(VOICE_MEMOS_DIR), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


# ===== Main =====

def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")

    log.info(f"Starting Penny Hybrid Server")
    log.info(f"  iCloud watching: {VOICE_MEMOS_DIR}")
    log.info(f"  Telegram chat: {TELEGRAM_CHAT_ID}")

    # Start iCloud watcher in background thread
    if VOICE_MEMOS_DIR.exists():
        watcher_thread = threading.Thread(target=start_icloud_watcher, daemon=True)
        watcher_thread.start()
    else:
        log.warning(f"iCloud directory not found, only webhook will work")

    # Run Flask server (blocking)
    app.run(host='0.0.0.0', port=5678)


if __name__ == '__main__':
    main()
