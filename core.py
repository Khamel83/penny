#!/usr/bin/env python3
"""
Penny Core Logic
Shared pipeline, notifications, and deduplication for all Penny services.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import logging.handlers
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import requests

from classifier import classify, detect_content_type
from config import get_config
from reminders import add_note, add_reminder
from transcript_log import (
    get_transcript,
    mark_failed,
    mark_routed,
    update_transcript_progress,
    update_transcript_stages,
)

cfg = get_config()

LOG_DIR = Path("~/.penny/logs").expanduser()

SOURCE_EMOJI = {
    "iCloud": "☁️",
    "Shortcut": "📱",
    "text": "💬",
    "HA": "🏠",
    "Google Tasks": "🗒️",
}

CATEGORY_EMOJI = {
    "groceries": "🛒",
    "errands": "🚗",
    "home": "🏠",
    "health": "🏥",
    "work": "💼",
    "kids": "👧",
    "inbox": "📝",
}

WHISPER_TOKEN_RE = re.compile(r"<\|[^>]+?\|>")


class RoutingError(RuntimeError):
    """Raised when Penny successfully transcribes/classifies but cannot persist the result."""


def setup_logging(service_name: str) -> logging.Logger:
    """Setup rotating file logging for a service."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"{service_name}.log"

    level = getattr(logging, cfg.logging.level.upper(), logging.INFO)

    logger = logging.getLogger()
    logger.setLevel(level)

    # Reset handlers so multiple imports / re-entry do not duplicate logs.
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logging.getLogger(service_name)


# ===== Hashing =====


def get_file_hash(path: Path) -> str:
    """Get MD5 hash of a file in chunks to save memory."""
    hasher = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


# ===== Telegram =====


def send_telegram(message: str, *, force: bool = False) -> bool:
    if not force and not cfg.notifications.telegram_enabled:
        return False
    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        return False

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage",
            json={"chat_id": cfg.telegram_chat_id, "text": message},
            timeout=30,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logging.getLogger("penny.core").error("Telegram send failed: %s", e)
        return False


def _notify_hermes(
    transcript_text: str,
    routed_items: List[Dict[str, Any]],
    source: str = "voice_memo",
) -> bool:
    """Best-effort Hermes webhook notification. Never blocks Penny for long."""
    hermes_url = os.getenv(
        "HERMES_WEBHOOK_URL", "http://100.126.13.70:7778/webhooks/penny"
    )
    secret = os.getenv("PENNY_WEBHOOK_SECRET", "")
    if not hermes_url or not secret:
        return False

    payload = {
        "source": source,
        "transcript": transcript_text,
        "routed_items": routed_items,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    signature = hmac.new(
        secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    request_id = hashlib.sha256(
        f"{source}\0{transcript_text}\0{body}".encode("utf-8")
    ).hexdigest()[:32]

    try:
        resp = requests.post(
            hermes_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": signature,
                "X-Request-ID": request_id,
            },
            timeout=3,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logging.getLogger("penny.core").warning("Hermes notify failed: %s", e)
        return False


def _hermes_items(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = result.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    if result.get("skip"):
        return [{"type": "skip", "reason": str(result.get("reason", ""))}]
    return []


def _finish_route(transcript: str, result: Dict[str, Any], source: str) -> Dict[str, Any]:
    try:
        _notify_hermes(transcript, _hermes_items(result), source=source)
    except Exception as e:
        logging.getLogger("penny.core").warning("Hermes notify failed: %s", e)
    return result


def build_result_message(transcript: str, result: Dict[str, Any], source: str) -> str:
    emoji = SOURCE_EMOJI.get(source, "📱")
    excerpt = transcript[:200] + ("..." if len(transcript) > 200 else "")

    if result.get("skip"):
        return f'⏭️ Not a reminder ({emoji} {source}):\n\n📋 "{excerpt}"'

    items = result.get("items", [])
    fallback = result.get("fallback", False)

    by_category: Dict[str, List[str]] = {}
    for entry in items:
        category = entry.get("category", "inbox")
        item_text = str(entry.get("item", "")).strip()
        if not item_text:
            continue
        by_category.setdefault(category, []).append(item_text)

    prefix = (
        f"⚠️ Classification failed — added to Inbox ({emoji} {source}):"
        if fallback
        else f"✅ {len(items)} item(s) added ({emoji} {source}):"
    )
    lines = [prefix, ""]
    for cat, cat_items in by_category.items():
        e = CATEGORY_EMOJI.get(cat, "📝")
        lines.append(f"  {e} {cat.capitalize()}: {', '.join(cat_items)}")
    lines += ["", f'📋 "{excerpt}"']
    return "\n".join(lines)


# ===== Pipeline =====


def normalize_transcript_text(transcript: str) -> str:
    """Strip common Whisper control-token artifacts and normalize whitespace."""
    raw = str(transcript or "")
    cleaned = WHISPER_TOKEN_RE.sub(" ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Heuristic: near-empty remnants from token-heavy output (e.g. "SE<|hr|><|hr|>").
    if "<|" in raw and len(cleaned) <= 3:
        return ""
    if cleaned and not any(ch.isalnum() for ch in cleaned):
        return ""
    return cleaned


def _target_reminders_list(category: str) -> str:
    target_list = category.capitalize()
    if target_list not in cfg.apple_reminders.lists:
        return cfg.apple_reminders.default_list
    return target_list


def _load_routing_progress(row_id: int | None) -> dict[str, Any]:
    if row_id is None:
        return {}
    row = get_transcript(row_id)
    if not row or not row.get("routing_progress"):
        return {}
    try:
        parsed = json.loads(row["routing_progress"])
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _short_excerpt(text: str, limit: int = 60) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _reference_reminder_text(transcript: str) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %-I:%M %p")
    excerpt = _short_excerpt(transcript) or "voice memo"
    return f"Review Penny note ({timestamp}): {excerpt}"


def classify_and_route(
    transcript: str,
    source: str,
    row_id: int | None = None,
    duration_seconds: float | None = None,
) -> Dict[str, Any]:
    """
    Core pipeline: Content type detection -> Classifier -> Reminders/Notes -> Telegram.

    Three-way routing:
    - action_items: extract todos via classifier -> add to Reminders
    - long_note: save to Apple Notes (no reminders)
    - unclear: save to Notes + create reference reminder in Inbox

    If row_id is provided, updates the transcript log status on success/failure.

    Raises RoutingError when Apple-side writes fail so callers do not mark items as processed.
    Returns the classifier result on success.
    """
    log = logging.getLogger("penny.core")
    transcript = normalize_transcript_text(transcript)
    progress = _load_routing_progress(row_id)

    if not transcript:
        if row_id is not None:
            mark_failed(row_id, "empty transcript after normalization")
        return {"skip": True, "reason": "empty transcript"}

    if row_id is not None:
        update_transcript_stages(
            row_id,
            ingest_state="routing",
            duration_seconds=duration_seconds,
            routing_started_at=datetime.now().isoformat(),
        )

    content_type = detect_content_type(
        transcript,
        cfg.openrouter_api_key,
        cfg.llm.model,
        duration_seconds=duration_seconds,
    )

    try:
        if content_type == "long_note":
            log.info("Routing as long note to Apple Notes")
            if not progress.get("note_created"):
                if not add_note(transcript, folder_name="Penny", source=source):
                    raise RoutingError("Failed to save long note to Apple Notes")
                if row_id is not None:
                    update_transcript_progress(
                        row_id,
                        {
                            "note_created": True,
                            "note_folder": "Penny",
                            "content_type": "long_note",
                        },
                    )
            if row_id is not None:
                mark_routed(row_id, {"type": "long_note"}, "note in Penny")
            return _finish_route(
                transcript, {"skip": True, "reason": "long_note"}, source
            )

        if content_type == "unclear":
            log.info("Unclear content — saving to Notes with reference reminder")
            if not progress.get("note_created"):
                if not add_note(transcript, folder_name="Penny", source=source):
                    raise RoutingError("Failed to save unclear note to Apple Notes")
                if row_id is not None:
                    update_transcript_progress(
                        row_id,
                        {
                            "note_created": True,
                            "note_folder": "Penny",
                            "content_type": "unclear",
                        },
                    )

            ref_text = str(
                progress.get("reference_reminder_text")
                or _reference_reminder_text(transcript)
            )
            if row_id is not None and not progress.get("reference_reminder_text"):
                update_transcript_progress(
                    row_id, {"reference_reminder_text": ref_text}
                )
            if not progress.get("reference_reminder_created"):
                if not add_reminder(
                    ref_text, "Inbox", cfg.apple_reminders.default_list
                ):
                    raise RoutingError(
                        "Failed to create reference reminder for unclear note"
                    )
                if row_id is not None:
                    update_transcript_progress(
                        row_id,
                        {
                            "reference_reminder_created": True,
                            "reference_reminder_text": ref_text,
                        },
                    )

            if row_id is not None:
                mark_routed(
                    row_id,
                    {"type": "unclear", "ref_reminder": ref_text},
                    "note + ref reminder",
                )
            result = {
                "skip": True,
                "reason": "unclear content, saved to Notes with reference",
            }
            return _finish_route(transcript, result, source)

        # action_items — use the existing item extractor
        result = classify(
            transcript,
            cfg.openrouter_api_key,
            cfg.llm.model,
            duration_seconds=duration_seconds,
        )

        if result.get("skip"):
            log.info("Skipping routing for non-reminder: %s", result.get("reason"))
            note_text = transcript or "(No intelligible speech detected.)"
            if not progress.get("note_created"):
                if not add_note(note_text, folder_name="Penny", source=source):
                    raise RoutingError("Failed to add transcript to Apple Notes")
                if row_id is not None:
                    update_transcript_progress(
                        row_id, {"note_created": True, "note_folder": "Penny"}
                    )
            if row_id is not None:
                mark_routed(row_id, result, "note in Penny")
            return _finish_route(transcript, result, source)

        items = result.get("items", [])
        if not isinstance(items, list) or not items:
            raise RoutingError("Classifier returned no routable items")

        routed_count = 0
        created_reminders = set(progress.get("created_reminders", []))
        for entry in items:
            item_text = str(entry.get("item", "")).strip()
            category = str(entry.get("category", "inbox")).strip().lower()
            if not item_text:
                continue
            target_list = _target_reminders_list(category)
            reminder_key = f"{target_list}|{item_text}"
            if reminder_key not in created_reminders:
                ok = add_reminder(
                    item_text, target_list, cfg.apple_reminders.default_list
                )
                if not ok:
                    raise RoutingError(
                        f"Failed to add reminder to '{target_list}': {item_text[:80]}"
                    )
                created_reminders.add(reminder_key)
                if row_id is not None:
                    update_transcript_progress(
                        row_id,
                        {"created_reminders": sorted(created_reminders)},
                    )
            routed_count += 1

        if cfg.notifications.telegram_enabled:
            msg = build_result_message(transcript, result, source)
            send_telegram(msg)

        if row_id is not None:
            mark_routed(row_id, result, f"{routed_count} reminder(s)")

        return _finish_route(transcript, result, source)

    except RoutingError as e:
        if row_id is not None:
            mark_failed(row_id, str(e))
        raise
