#!/usr/bin/env python3
"""
Penny Webhook Server

Endpoints:
  POST /upload  — audio file from iOS Shortcuts → transcribe → classify → Reminders
  POST /ingest  — pre-transcribed text → classify → Reminders
  GET  /health  — health check
"""
import sys
import tempfile
import logging
from pathlib import Path

from flask import Flask, request, jsonify

# Allow imports from repo root (config, classifier, reminders, core)
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import get_config
from core import (
    setup_logging,
    get_file_hash,
    classify_and_route,
)
from transcript_log import init_db, insert_transcript, is_already_logged

cfg = get_config()
log = setup_logging("webhook")

app = Flask(__name__)

MAX_FILE_SIZE = cfg.voice_memos.max_file_size_mb * 1024 * 1024

# ===== Transcription =====

def transcribe(path):
    import mlx_whisper
    log.info("Transcribing: %s", path)
    result = mlx_whisper.transcribe(
        str(path),
        path_or_hf_repo=cfg.voice_memos.whisper_model,
    )
    return result["text"].strip()


# ===== Flask routes =====

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "penny-webhook",
        "telegram_configured": bool(cfg.telegram_bot_token and cfg.telegram_chat_id),
        "llm_model": cfg.llm.model,
    })


@app.route("/upload", methods=["POST"])
def upload():
    """Receive audio file from iOS Shortcut, transcribe, classify, add to Reminders."""
    if "audio" not in request.files:
        return jsonify({"error": "No audio file — expected form field 'audio'"}), 400

    audio_file = request.files["audio"]
    log.info("Upload received: %s", audio_file.filename)

    temp_path = None
    with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as f:
        audio_file.save(f.name)
        temp_path = Path(f.name)

    try:
        file_size = temp_path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            size_mb = file_size / (1024 * 1024)
            max_mb = cfg.voice_memos.max_file_size_mb
            log.warning("Rejected upload %s (%.1fMB > %sMB)", audio_file.filename, size_mb, max_mb)
            return jsonify({"error": f"Audio file too large ({size_mb:.1f}MB > {max_mb}MB)"}), 413

        file_hash = get_file_hash(temp_path)
        if is_already_logged(file_hash):
            log.info("Already logged this file")
            return jsonify({"status": "ok", "message": "already processed"})

        transcript = transcribe(temp_path)
        log.info("Transcript: %s...", transcript[:100])

        row_id = insert_transcript(
            content_hash=file_hash,
            source="Shortcut",
            transcript=transcript,
        )
        if row_id is not None:
            result = classify_and_route(transcript, source="Shortcut", row_id=row_id)
        else:
            result = {"skip": True, "reason": "duplicate"}

        return jsonify({
            "status": "ok",
            "transcript": transcript[:200],
            "items_added": len(result.get("items", [])),
            "skipped": result.get("skip", False),
        })

    except Exception as e:
        log.error("Upload error: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


@app.route("/ingest", methods=["POST"])
def ingest():
    """
    Accept pre-transcribed text from any source.
    JSON body: {"text": "buy milk", "source": "HA"}
    """
    data = request.get_json(silent=True)
    if not data or "text" not in data:
        return jsonify({"error": "Missing 'text' field in JSON body"}), 400

    text = data["text"].strip()
    if not text:
        return jsonify({"error": "Empty text"}), 400

    source = data.get("source", "text")
    log.info("Ingest (%s): %s...", source, text[:100])

    import hashlib as _hashlib

    content_hash = _hashlib.md5(text.encode("utf-8")).hexdigest()

    if is_already_logged(content_hash):
        return jsonify({"status": "ok", "message": "already processed"})

    try:
        row_id = insert_transcript(
            content_hash=content_hash,
            source=source,
            transcript=text,
        )
        if row_id is not None:
            result = classify_and_route(text, source=source, row_id=row_id)
        else:
            result = {"skip": True, "reason": "duplicate"}
    except Exception as e:
        log.error("Ingest error: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "status": "ok",
        "items_added": len(result.get("items", [])),
        "skipped": result.get("skip", False),
    })


# ===== Main =====

def main():
    init_db()
    log.info("Starting Penny Webhook Server")
    log.info("  Port: %s", cfg.webhook.port)
    log.info("  LLM model: %s", cfg.llm.model)

    app.run(host=cfg.webhook.host, port=cfg.webhook.port, use_reloader=False)


if __name__ == "__main__":
    main()
