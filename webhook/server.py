#!/usr/bin/env python3
"""
Penny Webhook Server

Endpoints:
  POST /upload  — audio file from iOS Shortcuts → transcribe → classify → Reminders
  POST /ingest  — pre-transcribed text → classify → Reminders
  GET  /health  — health check
"""
import hashlib
import os
import sys
import tempfile
import logging
from pathlib import Path

from flask import Flask, request, jsonify
from werkzeug.exceptions import RequestEntityTooLarge

# Allow imports from repo root (config, classifier, reminders, core)
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import get_config
from ingress_auth import MAX_INGEST_TEXT_BYTES, authorize_bearer
from core import (
    setup_logging,
    get_file_hash,
    classify_and_route,
)
from transcript_quality import TranscriptionResult, transcribe_with_quality
from transcript_log import (
    InsertOutcome,
    get_transcript_by_hash,
    init_db,
    insert_transcript_result,
)

cfg = get_config()
log = setup_logging("webhook")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = cfg.webhook.max_request_bytes

MAX_FILE_SIZE = cfg.voice_memos.max_file_size_mb * 1024 * 1024

# ===== Transcription =====

def transcribe(path: Path) -> TranscriptionResult:
    import subprocess as _sp

    # Normalize to 16kHz mono WAV before Whisper to handle CAF, AMR, and other
    # iOS formats that ffmpeg may misidentify when given an .m4a extension.
    wav_path = path.with_suffix(".wav")
    try:
        _sp.run(
            ["ffmpeg", "-y", "-i", str(path), "-ar", "16000", "-ac", "1", str(wav_path)],
            check=True, capture_output=True,
        )
        transcribe_path = wav_path
    except _sp.CalledProcessError as e:
        log.warning("ffmpeg conversion failed, passing original to Whisper: %s", e.stderr.decode()[-200:])
        transcribe_path = path

    log.info("Transcribing: %s", transcribe_path)
    try:
        return transcribe_with_quality(
            transcribe_path,
            model=cfg.voice_memos.whisper_model,
        )
    finally:
        if wav_path.exists():
            wav_path.unlink(missing_ok=True)


# ===== Flask routes =====


def _require_ingest_auth():
    if not authorize_bearer(request, cfg.webhook.ingest_token):
        return jsonify({"error": "unauthorized"}), 401
    if (
        request.content_length is not None
        and request.content_length > cfg.webhook.max_request_bytes
    ):
        return jsonify({"error": "request too large"}), 413
    return None


@app.errorhandler(RequestEntityTooLarge)
def request_too_large(_error):
    return jsonify({"error": "request too large"}), 413

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
    auth_error = _require_ingest_auth()
    if auth_error is not None:
        return auth_error

    # iOS Shortcuts sends multipart files under varying field names; accept any file field
    # or fall back to raw request body (when Shortcuts sends audio as binary body).
    audio_file = request.files.get("audio") or (request.files and next(iter(request.files.values()), None))
    raw_body = request.data if not audio_file else None

    if not audio_file and not raw_body:
        log.warning("Upload rejected — no audio. Files: %s, Content-Type: %s", list(request.files.keys()), request.content_type)
        return jsonify({"error": "No audio file — expected multipart field or raw audio body"}), 400
    if raw_body and len(raw_body) > MAX_FILE_SIZE:
        log.warning("Raw upload exceeds configured size limit")
        return jsonify({"error": "Audio file too large"}), 413

    suffix = ".tmp"
    if audio_file:
        fname = audio_file.filename or ""
        if "." in fname:
            suffix = "." + fname.rsplit(".", 1)[-1]
        log.info("Upload received: %s (field=%s, content-type=%s)", fname, next((k for k, v in request.files.items() if v == audio_file), "?"), request.content_type)
    else:
        log.info("Upload received: raw body %d bytes, content-type=%s", len(raw_body), request.content_type)

    temp_path = None
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        if audio_file:
            audio_file.save(f.name)
        else:
            f.write(raw_body)
        temp_path = Path(f.name)

    try:
        file_size = temp_path.stat().st_size
        with open(temp_path, "rb") as _f:
            magic = _f.read(12).hex()
        log.info("File saved: %d bytes, magic=%s, path=%s", file_size, magic, temp_path)
        if file_size > MAX_FILE_SIZE:
            size_mb = file_size / (1024 * 1024)
            max_mb = cfg.voice_memos.max_file_size_mb
            log.warning("Rejected upload %s (%.1fMB > %sMB)", audio_file.filename, size_mb, max_mb)
            return jsonify({"error": f"Audio file too large ({size_mb:.1f}MB > {max_mb}MB)"}), 413

        file_hash = get_file_hash(temp_path)
        transcription = transcribe(temp_path)
        if not transcription.quality.passed:
            quality_detail = transcription.quality_detail or (
                f"attempt_{transcription.attempts}="
                f"{transcription.quality.reason or 'unknown_quality_failure'}"
            )
            log.warning(
                "Upload transcript needs review (reason=%s)",
                transcription.quality.reason,
            )
            result = insert_transcript_result(
                content_hash=file_hash,
                source="Shortcut",
                transcript=transcription.text,
                ingest_state="needs_review",
                error_message=transcription.quality.reason,
                quality_status="needs_review",
                quality_detail=quality_detail,
                enqueue_slack=False,
            )
            if result.outcome is InsertOutcome.FAILED:
                log.error("Upload persistence unavailable")
                return jsonify({"error": "upload unavailable"}), 503
            if result.outcome is InsertOutcome.DUPLICATE and get_transcript_by_hash(file_hash) is None:
                log.error("Upload duplicate has no canonical row")
                return jsonify({"error": "upload unavailable"}), 503
            return jsonify({"error": "Transcript needs review"}), 422

        transcript = transcription.text
        log.info("Upload transcript accepted (%d characters)", len(transcript))

        result = insert_transcript_result(
            content_hash=file_hash,
            source="Shortcut",
            transcript=transcript,
            enqueue_slack=False,
        )
        if result.outcome is InsertOutcome.FAILED:
            log.error("Upload persistence unavailable")
            return jsonify({"error": "upload unavailable"}), 503
        if result.outcome is InsertOutcome.DUPLICATE:
            existing = get_transcript_by_hash(file_hash)
            if existing is None:
                log.error("Upload duplicate has no canonical row")
                return jsonify({"error": "upload unavailable"}), 503
            row_id = int(existing["id"])
            if existing.get("status") in {"routed", "processed"}:
                route_result = {"skip": True, "reason": "duplicate"}
            else:
                route_result = classify_and_route(
                    str(existing["transcript"]),
                    source=str(existing["source"]),
                    row_id=row_id,
                    allow_maya=False,
                )
        else:
            row_id = int(result.row_id)
            route_result = classify_and_route(
                transcript,
                source="Shortcut",
                row_id=row_id,
                allow_maya=False,
            )

        return jsonify({
            "status": "ok",
            "transcript": transcript[:200],
            "items_added": len(route_result.get("items", [])),
            "skipped": route_result.get("skip", False),
        })

    except Exception as error:
        log.error("Upload processing failed (%s)", type(error).__name__)
        return jsonify({"error": "upload processing failed"}), 500
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


@app.route("/ingest", methods=["POST"])
def ingest():
    """
    Accept pre-transcribed text from any source.
    JSON body: {"text": "buy milk", "source": "HA"}
    """
    auth_error = _require_ingest_auth()
    if auth_error is not None:
        return auth_error

    data = request.get_json(silent=True)
    if not data or "text" not in data:
        return jsonify({"error": "Missing 'text' field in JSON body"}), 400

    text = data["text"].strip()
    if not text:
        return jsonify({"error": "Empty text"}), 400
    if len(text.encode("utf-8")) > MAX_INGEST_TEXT_BYTES:
        return jsonify({"error": "text too large"}), 413

    source = data.get("source", "text")
    log.info("Ingest accepted (%d characters)", len(text))

    import hashlib as _hashlib

    content_hash = _hashlib.md5(text.encode("utf-8")).hexdigest()

    try:
        result = insert_transcript_result(
            content_hash=content_hash,
            source=source,
            transcript=text,
            enqueue_slack=False,
        )
        if result.outcome is InsertOutcome.FAILED:
            log.error("Ingest persistence unavailable")
            return jsonify({"error": "ingest unavailable"}), 503
        if result.outcome is InsertOutcome.DUPLICATE:
            existing = get_transcript_by_hash(content_hash)
            if existing is None:
                log.error("Ingest duplicate has no canonical row")
                return jsonify({"error": "ingest unavailable"}), 503
            row_id = int(existing["id"])
            if existing.get("status") in {"routed", "processed"}:
                route_result = {"skip": True, "reason": "duplicate"}
            else:
                route_result = classify_and_route(
                    str(existing["transcript"]),
                    source=str(existing["source"]),
                    row_id=row_id,
                    allow_maya=False,
                )
        else:
            row_id = int(result.row_id)
            route_result = classify_and_route(
                text,
                source=source,
                row_id=row_id,
                allow_maya=False,
            )
    except Exception as error:
        log.error("Ingest processing failed (%s)", type(error).__name__)
        return jsonify({"error": "ingest processing failed"}), 500

    return jsonify({
        "status": "ok",
        "items_added": len(route_result.get("items", [])),
        "skipped": route_result.get("skip", False),
    })


@app.route("/deliver", methods=["POST"])
def deliver():
    """Receive a transcript back from Maya for local Apple-side delivery.

    Maya classifies voice transcripts and sends reminder-type ones here.
    Routing runs with allow_maya=False — re-sending to Maya would loop.
    """
    secret = os.environ.get("PENNY_WEBHOOK_SECRET", "")
    provided = request.headers.get("Authorization", "")
    if not secret or provided != f"Bearer {secret}":
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    text = (body.get("transcript") or "").strip()
    if not text:
        return jsonify({"error": "transcript is required and must be non-empty"}), 422

    source = (body.get("source") or "maya").strip()
    duration = body.get("duration_seconds")

    content_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
    try:
        result = insert_transcript_result(
            content_hash=content_hash,
            source=f"maya:{source}",
            transcript=text,
            duration_seconds=duration,
            enqueue_slack=False,
        )
    except Exception as error:
        log.error("/deliver persistence failed (%s)", type(error).__name__)
        return jsonify({"error": "delivery unavailable"}), 503
    if result.outcome is InsertOutcome.FAILED:
        log.error("/deliver persistence unavailable")
        return jsonify({"error": "delivery unavailable"}), 503
    if result.outcome is InsertOutcome.DUPLICATE:
        existing = get_transcript_by_hash(content_hash)
        if existing is None:
            log.error("/deliver duplicate has no canonical row")
            return jsonify({"error": "delivery unavailable"}), 503
        row_id = int(existing["id"])
        if existing.get("status") in {"routed", "processed"}:
            log.info("/deliver: duplicate transcript (hash=%s)", content_hash[:12])
            return jsonify({"status": "duplicate"})
        try:
            classify_and_route(
                str(existing["transcript"]),
                str(existing["source"]),
                row_id=row_id,
                duration_seconds=duration,
                allow_maya=False,
            )
        except Exception as error:
            log.error("/deliver retry routing failed (%s)", type(error).__name__)
            return jsonify({"error": "delivery processing failed"}), 500
        confirmed = get_transcript_by_hash(content_hash)
        if confirmed is None or confirmed.get("status") not in {"routed", "processed"}:
            log.error("/deliver retry routing is not durably confirmed")
            return jsonify({"error": "delivery unavailable"}), 503
        return jsonify({"status": "delivered", "id": row_id})

    row_id = int(result.row_id)
    log.info("/deliver: received %d chars from Maya (source=%s, row=%s)",
             len(text), source, row_id)

    try:
        classify_and_route(
            text, f"maya:{source}",
            row_id=row_id,
            duration_seconds=duration,
            allow_maya=False,
        )
    except Exception as error:
        log.error("/deliver routing failed (%s)", type(error).__name__)
        return jsonify({"error": "delivery processing failed"}), 500

    return jsonify({"status": "delivered", "id": row_id})


# ===== Main =====

def main():
    init_db()
    log.info("Starting Penny Webhook Server")
    log.info("  Port: %s", cfg.webhook.port)
    log.info("  LLM model: %s", cfg.llm.model)

    app.run(host=cfg.webhook.host, port=cfg.webhook.port, use_reloader=False)


if __name__ == "__main__":
    main()
