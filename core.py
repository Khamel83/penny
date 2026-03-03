#!/usr/bin/env python3
"""
Penny Core Logic
Shared pipeline, notifications, and deduplication for all Penny services.
"""
from __future__ import annotations

import hashlib
import logging
import logging.handlers
import os
import re
from pathlib import Path
from typing import Any, Dict, List

import requests

from classifier import classify
from config import get_config
from reminders import add_note, add_reminder

cfg = get_config()

# Shared state paths
PROCESSED_FILE = Path("~/.penny/processed.txt").expanduser()
SYNCED_TASKS_FILE = Path("~/.penny/synced_tasks.txt").expanduser()
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

# Phrases that, when they appear at the start of a transcript, force routing to
# Apple Notes regardless of what the LLM would otherwise decide.
_NOTE_TRIGGER_RE = re.compile(
    r"^\s*(note[:\-]\s*|note to self\b|save\s+(this\s+)?as\s+(a\s+)?note\b|this\s+is\s+a\s+note\b)",
    re.IGNORECASE,
)


def _strip_note_trigger(transcript: str) -> str:
    """Remove a leading note-trigger phrase so it doesn't pollute the saved note."""
    return _NOTE_TRIGGER_RE.sub("", transcript).strip()


def _is_repetitive_garbage(text: str) -> bool:
    """Return True if text is a Whisper hallucination made of a repeated substring.

    Whisper sometimes fills silence or noise with a short token repeated hundreds
    of times (e.g. "strstrstrstr..."). There's nothing useful to route.
    """
    stripped = re.sub(r"\s+", "", text.lower())
    if len(stripped) < 20:
        return False
    for n in range(2, 8):
        prefix = stripped[:n]
        expected = (prefix * ((len(stripped) // n) + 1))[:len(stripped)]
        match_ratio = sum(a == b for a, b in zip(stripped, expected)) / len(stripped)
        if match_ratio >= 0.9:
            return True
    return False


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

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

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


# ===== Deduplication =====

def _normalize_identifier(identifier: str | Path) -> str:
    return str(identifier)


def get_file_hash(path: Path) -> str:
    """Get MD5 hash of a file in chunks to save memory."""
    hasher = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def is_processed(identifier: str | Path, state_file: Path = PROCESSED_FILE) -> bool:
    """Check if a file hash or task ID has already been processed."""
    token = _normalize_identifier(identifier)
    if not state_file.exists():
        return False

    with state_file.open("r", encoding="utf-8") as f:
        processed = {line.strip() for line in f if line.strip()}
    return token in processed


def mark_processed(identifier: str | Path, state_file: Path = PROCESSED_FILE) -> None:
    """Record an identifier as processed, flushing to disk before returning."""
    token = _normalize_identifier(identifier)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with state_file.open("a", encoding="utf-8") as f:
        f.write(f"{token}\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            # Some filesystems do not support fsync on this handle; best effort is enough.
            pass


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
    if _is_repetitive_garbage(cleaned):
        logging.getLogger("penny.core").warning(
            "Dropping repetitive-garbage transcript (Whisper hallucination): %r…", cleaned[:40]
        )
        return ""
    return cleaned


def _target_reminders_list(category: str) -> str:
    target_list = category.capitalize()
    if target_list not in cfg.apple_reminders.lists:
        return cfg.apple_reminders.default_list
    return target_list


def classify_and_route(transcript: str, source: str) -> Dict[str, Any]:
    """
    Core pipeline: Text -> Classifier -> Reminders/Notes -> Telegram.

    Raises RoutingError when Apple-side writes fail so callers do not mark items as processed.
    Returns the classifier result on success.
    """
    log = logging.getLogger("penny.core")
    transcript = normalize_transcript_text(transcript)

    if _NOTE_TRIGGER_RE.match(transcript):
        log.info("Note trigger detected — routing directly to Apple Notes")
        note_text = _strip_note_trigger(transcript) or transcript
        if not add_note(note_text, folder_name="Penny", source=source):
            raise RoutingError("Failed to add transcript to Apple Notes")
        result: Dict[str, Any] = {"skip": True, "reason": "explicit note trigger"}
        if cfg.notifications.telegram_enabled:
            send_telegram(build_result_message(transcript, result, source))
        return result

    result = classify(transcript, cfg.openrouter_api_key, cfg.llm.model)

    if result.get("skip"):
        log.info("Skipping routing for non-reminder: %s", result.get("reason"))
        note_text = transcript or "(No intelligible speech detected.)"
        if not add_note(note_text, folder_name="Penny", source=source):
            raise RoutingError("Failed to add transcript to Apple Notes")
        return result

    items = result.get("items", [])
    if not isinstance(items, list) or not items:
        raise RoutingError("Classifier returned no routable items")

    for entry in items:
        item_text = str(entry.get("item", "")).strip()
        category = str(entry.get("category", "inbox")).strip().lower()
        if not item_text:
            continue
        target_list = _target_reminders_list(category)
        ok = add_reminder(item_text, target_list, cfg.apple_reminders.default_list)
        if not ok:
            raise RoutingError(f"Failed to add reminder to '{target_list}': {item_text[:80]}")

    if cfg.notifications.telegram_enabled:
        msg = build_result_message(transcript, result, source)
        send_telegram(msg)

    return result
