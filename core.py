#!/usr/bin/env python3
"""
Penny Core Logic
Shared pipeline, notifications, and deduplication for all Penny services.
"""
import hashlib
import logging
import logging.handlers
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

import requests

from config import get_config
from classifier import classify
from reminders import add_reminder, add_note

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

def setup_logging(service_name: str):
    """Setup rotating file logging for a service."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"{service_name}.log"
    
    level = getattr(logging, cfg.logging.level.upper(), logging.INFO)
    
    # Root logger setup
    logger = logging.getLogger()
    logger.setLevel(level)
    
    # Remove existing handlers to avoid duplicates
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    # Rotating file handler (5 files, 5MB each)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5*1024*1024, backupCount=5
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logging.getLogger(service_name)

# ===== Deduplication =====

def get_file_hash(path: Path) -> str:
    """Get MD5 hash of a file in chunks to save memory."""
    hasher = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def is_processed(identifier: str, state_file: Path = PROCESSED_FILE) -> bool:
    """Check if a file hash or task ID has already been processed."""
    if not state_file.exists():
        return False
    # Using a set for O(1) lookups if the file grows large
    with state_file.open("r") as f:
        processed = {line.strip() for line in f}
    return identifier in processed

def mark_processed(identifier: str, state_file: Path = PROCESSED_FILE):
    """Record an identifier as processed atomically."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    # Atomic-ish write: append and flush
    with state_file.open("a") as f:
        f.write(f"{identifier}
")

# ===== Telegram =====

def send_telegram(message: str) -> bool:
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
        logging.getLogger("penny.core").error(f"Telegram send failed: {e}")
        return False

def build_result_message(transcript: str, result: Dict[str, Any], source: str) -> str:
    emoji = SOURCE_EMOJI.get(source, "📱")
    excerpt = transcript[:200] + ("..." if len(transcript) > 200 else "")

    if result.get("skip"):
        return f"⏭️ Not a reminder ({emoji} {source}):

📋 "{excerpt}""

    items = result.get("items", [])
    fallback = result.get("fallback", False)

    by_category: Dict[str, List[str]] = {}
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
    lines += ["", f"📋 "{excerpt}""]
    return "
".join(lines)

# ===== Pipeline =====

def classify_and_route(transcript: str, source: str) -> Dict[str, Any]:
    """
    Core pipeline: Text -> Classifier -> Reminders/Notes -> Telegram.
    Returns the classification result.
    """
    log = logging.getLogger("penny.core")
    result = classify(transcript, cfg.openrouter_api_key, cfg.llm.model)

    if result.get("skip"):
        log.info(f"Skipping routing for non-reminder: {result.get('reason')}")
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
