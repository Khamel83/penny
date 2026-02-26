#!/usr/bin/env python3
"""
Penny Webhook Server

Endpoints:
  POST /upload  — audio file from iOS Shortcuts → transcribe → classify → Reminders
  POST /ingest  — pre-transcribed text (HA Voice PE, etc.) → classify → Reminders
  GET  /health  — health check

Also runs a background iCloud filesystem watcher (watchdog) as a complement
to the DB-polling in watcher.py — catches files the moment they appear on disk.
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
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import requests as req

# Allow imports from repo root (config, classifier, reminders)
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import get_config
from classifier import classify
from reminders import add_reminder, add_note

cfg = get_config()

app = Flask(__name__)
logging.basicConfig(
    level=getattr(logging, cfg.logging.level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger(__name__)

# Paths
VOICE_MEMOS_DIR = Path(os.environ.get(
    "VOICE_MEMOS_DIR",
    "~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings"
)).expanduser()
PROCESSED_FILE = Path("~/.penny/processed.txt").expanduser()
WEBHOOK_PROCESSED_FILE = Path("~/.penny/processed_webhook.txt").expanduser()

SOURCE_EMOJI = {"iCloud": "☁️", "Shortcut": "📱", "text": "💬", "HA": "🏠"}
CATEGORY_EMOJI = {
    "groceries": "🛒",
    "errands": "🚗",
    "home": "🏠",
    "health": "🏥",
    "work": "💼",
    "kids": "👧",
    "inbox": "📝",
}


# ===== Deduplication =====

def get_file_hash(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def is_processed(path, processed_file=None):
    pf = processed_file or PROCESSED_FILE
    if not pf.exists():
        return False
    return get_file_hash(path) in pf.read_text()


def mark_processed(path, processed_file=None):
    pf = processed_file or PROCESSED_FILE
    pf.parent.mkdir(parents=True, exist_ok=True)
    with pf.open("a") as f:
        f.write(f"{get_file_hash(path)}\n")


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

def send_telegram(message: str):
    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        return
    try:
        resp = req.post(
            f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage",
            json={"chat_id": cfg.telegram_chat_id, "text": message},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        log.error(f"Telegram send failed: {e}")


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

def classify_and_route(transcript: str, source: str) -> dict:
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
        if cfg.notifications.telegram_enabled:
            msg = build_result_message(transcript, result, source)
            send_telegram(msg)

    return result


# ===== Flask routes =====

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "penny-webhook",
        "icloud_watching": str(VOICE_MEMOS_DIR),
        "telegram_configured": bool(cfg.telegram_bot_token and cfg.telegram_chat_id),
        "llm_model": cfg.llm.model,
    })


@app.route("/upload", methods=["POST"])
def upload():
    """Receive audio file from iOS Shortcut, transcribe, classify, add to Reminders."""
    if "audio" not in request.files:
        return jsonify({"error": "No audio file — expected form field 'audio'"}), 400

    audio_file = request.files["audio"]
    log.info(f"Upload received: {audio_file.filename}")

    with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as f:
        audio_file.save(f.name)
        temp_path = Path(f.name)

    try:
        if is_processed(temp_path, WEBHOOK_PROCESSED_FILE):
            log.info("Already processed this file")
            return jsonify({"status": "ok", "message": "already processed"})

        transcript = transcribe(temp_path)
        log.info(f"Transcript: {transcript[:100]}...")

        result = classify_and_route(transcript, source="Shortcut")
        mark_processed(temp_path, WEBHOOK_PROCESSED_FILE)

        return jsonify({
            "status": "ok",
            "transcript": transcript[:200],
            "items_added": len(result.get("items", [])),
            "skipped": result.get("skip", False),
        })

    except Exception as e:
        log.error(f"Upload error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        temp_path.unlink(missing_ok=True)


@app.route("/ingest", methods=["POST"])
def ingest():
    """
    Accept pre-transcribed text from any source (HA Voice PE, integrations, etc.).

    JSON body: {"text": "buy milk and call the dentist", "source": "HA"}
    The 'source' field is optional (defaults to "text") and used only for
    labelling the Telegram notification.
    """
    data = request.get_json(silent=True)
    if not data or "text" not in data:
        return jsonify({"error": "Missing 'text' field in JSON body"}), 400

    text = data["text"].strip()
    if not text:
        return jsonify({"error": "Empty text"}), 400

    source = data.get("source", "text")
    log.info(f"Ingest ({source}): {text[:100]}...")

    result = classify_and_route(text, source=source)

    return jsonify({
        "status": "ok",
        "items_added": len(result.get("items", [])),
        "skipped": result.get("skip", False),
    })


# ===== Background iCloud watcher (watchdog filesystem events) =====

class VoiceMemoHandler(FileSystemEventHandler):
    """
    Watches the Voice Memos directory for new files via filesystem events.
    Complements the DB-polling approach in watcher.py.
    """

    def on_created(self, event):
        if event.is_directory:
            return
        if not event.src_path.endswith((".m4a", ".wav", ".mp3")):
            return
        time.sleep(2)  # Wait for file write to complete
        self._process(event.src_path)

    def _process(self, path):
        if is_processed(path):
            return
        try:
            log.info(f"iCloud event: new file {path}")
            transcript = transcribe(path)
            classify_and_route(transcript, source="iCloud")
            mark_processed(path)
        except Exception as e:
            log.error(f"iCloud handler error for {path}: {e}")


def start_icloud_watcher():
    if not VOICE_MEMOS_DIR.exists():
        log.warning(f"Voice Memos dir not found, iCloud watcher disabled: {VOICE_MEMOS_DIR}")
        return
    log.info(f"iCloud watcher started: {VOICE_MEMOS_DIR}")
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
    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        log.warning("Telegram credentials not set")
    if not cfg.openrouter_api_key:
        log.warning("OPENROUTER_API_KEY not set — classification will fall back to Inbox")

    log.info("Starting Penny Webhook Server")
    log.info(f"  Port: {cfg.webhook.port}")
    log.info(f"  iCloud watching: {VOICE_MEMOS_DIR}")
    log.info(f"  LLM model: {cfg.llm.model}")

    if VOICE_MEMOS_DIR.exists():
        watcher_thread = threading.Thread(target=start_icloud_watcher, daemon=True)
        watcher_thread.start()
    else:
        log.warning("iCloud directory not found — only webhook endpoints will work")

    app.run(host=cfg.webhook.host, port=cfg.webhook.port)


if __name__ == "__main__":
    main()
