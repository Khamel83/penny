#!/usr/bin/env python3
"""
Penny Google Tasks Poller

Polls Google Tasks every N minutes for new items, classifies them with
the LLM, adds them to Apple Reminders, and marks them complete in Tasks.

Run as a launchd service alongside watcher.py and webhook/server.py.

One-time setup required: python3 scripts/google_auth.py
"""
import sys
import time
import logging
from pathlib import Path

# Allow imports from this directory
sys.path.insert(0, str(Path(__file__).parent))

from config import get_config
from classifier import classify
from reminders import add_reminder, add_note

log = logging.getLogger(__name__)

SYNCED_TASKS_FILE = Path("~/.penny/synced_tasks.txt").expanduser()
HEALTH_FILE = Path("~/.penny/health_tasks.txt").expanduser()

CATEGORY_EMOJI = {
    "groceries": "🛒",
    "errands": "🚗",
    "home": "🏠",
    "health": "🏥",
    "work": "💼",
    "kids": "👧",
    "inbox": "📝",
}


# ===== Google Tasks helpers =====

def get_google_service(credentials_file: Path, token_file: Path):
    """Build authenticated Google Tasks service, refreshing token if needed."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    SCOPES = ["https://www.googleapis.com/auth/tasks"]

    if not token_file.exists():
        raise RuntimeError(
            f"No Google token found at {token_file}. "
            "Run scripts/google_auth.py first."
        )

    creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            log.info("Refreshing Google OAuth token...")
            creds.refresh(Request())
            token_file.write_text(creds.to_json())
            log.info("Token refreshed.")
        else:
            raise RuntimeError(
                "Google credentials invalid and cannot be refreshed. "
                "Run scripts/google_auth.py again."
            )

    return build("tasks", "v1", credentials=creds, cache_discovery=False)


def get_tasklist_id(service, list_name: str) -> str:
    """Find the task list ID by name, falling back to @default."""
    result = service.tasklists().list().execute()
    for tl in result.get("items", []):
        if tl["title"] == list_name:
            return tl["id"]
    log.warning(f"Task list '{list_name}' not found, using @default")
    return "@default"


# ===== Deduplication =====

def is_task_synced(task_id: str) -> bool:
    if not SYNCED_TASKS_FILE.exists():
        return False
    return task_id in SYNCED_TASKS_FILE.read_text().splitlines()


def mark_task_synced(task_id: str):
    SYNCED_TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SYNCED_TASKS_FILE.open("a") as f:
        f.write(f"{task_id}\n")


# ===== Notification =====

def send_telegram(message: str, bot_token: str, chat_id: str):
    import requests as req
    try:
        resp = req.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        log.error(f"Telegram send failed: {e}")


def build_result_message(task_title: str, result: dict) -> str:
    excerpt = task_title[:200] + ("..." if len(task_title) > 200 else "")

    if result.get("skip"):
        return f"⏭️ Not a reminder (🗒️ Google Tasks):\n\n📋 \"{excerpt}\""

    items = result.get("items", [])
    fallback = result.get("fallback", False)

    by_category: dict = {}
    for entry in items:
        by_category.setdefault(entry["category"], []).append(entry["item"])

    prefix = (
        f"⚠️ Classification failed — added to Inbox (🗒️ Google Tasks):"
        if fallback
        else f"✅ {len(items)} item(s) added (🗒️ Google Tasks):"
    )
    lines = [prefix, ""]
    for cat, cat_items in by_category.items():
        e = CATEGORY_EMOJI.get(cat, "📝")
        lines.append(f"  {e} {cat.capitalize()}: {', '.join(cat_items)}")
    lines += ["", f"📋 \"{excerpt}\""]
    return "\n".join(lines)


# ===== Core poll logic =====

def poll_once(service, tasklist_id: str, cfg) -> int:
    """
    Poll for new tasks, classify and route them, mark complete in Tasks.
    Returns count of tasks processed.
    """
    tasks_result = service.tasks().list(
        tasklist=tasklist_id,
        showCompleted=False,
        showHidden=False,
        maxResults=100,
    ).execute()

    tasks = tasks_result.get("items", [])
    if not tasks:
        log.debug("No pending tasks.")
        return 0

    processed = 0
    for task in tasks:
        task_id = task.get("id", "")
        task_title = (task.get("title") or "").strip()

        if not task_title:
            continue

        if is_task_synced(task_id):
            # Already synced to Reminders — retry marking complete in Tasks
            try:
                task["status"] = "completed"
                service.tasks().update(
                    tasklist=tasklist_id, task=task_id, body=task
                ).execute()
                log.debug(f"Retried mark-complete for: '{task_title}'")
            except Exception as e:
                log.warning(f"Retry mark-complete failed for '{task_title}': {e}")
            continue

        log.info(f"New task: '{task_title}'")

        # Classify
        result = classify(task_title, cfg.openrouter_api_key, cfg.llm.model)

        # Route result
        if result.get("skip"):
            # Not a reminder — save to Apple Notes Penny folder, no Telegram
            add_note(task_title, folder_name="Penny", source="Google Tasks")
        else:
            for entry in result.get("items", []):
                target_list = entry["category"].capitalize()
                if target_list not in cfg.apple_reminders.lists:
                    target_list = cfg.apple_reminders.default_list
                add_reminder(entry["item"], target_list, cfg.apple_reminders.default_list)
            msg = build_result_message(task_title, result)
            send_telegram(msg, cfg.telegram_bot_token, cfg.telegram_chat_id)

        # Record as synced before marking complete (so a Tasks API failure
        # doesn't cause us to re-process on the next poll)
        mark_task_synced(task_id)

        # Mark complete in Google Tasks
        try:
            task["status"] = "completed"
            service.tasks().update(
                tasklist=tasklist_id, task=task_id, body=task
            ).execute()
            log.info(f"Marked complete in Google Tasks: '{task_title}'")
        except Exception as e:
            log.warning(
                f"Could not mark '{task_title}' complete in Tasks: {e}. "
                "Will retry next poll."
            )

        processed += 1

    return processed


def update_health():
    from datetime import datetime
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(f"{datetime.now().isoformat()}|tasks_poller_ok:1\n")


# ===== Main =====

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(message)s",
    )

    cfg = get_config()

    # Override log level from config
    logging.getLogger().setLevel(
        getattr(logging, cfg.logging.level.upper(), logging.INFO)
    )

    log.info("=" * 60)
    log.info("Penny Google Tasks Poller starting...")
    log.info("=" * 60)
    log.info(f"  Task list: {cfg.google_tasks.list_name}")
    log.info(f"  Poll interval: {cfg.google_tasks.poll_interval_seconds}s")
    log.info(f"  LLM model: {cfg.llm.model}")

    # Verify Google credentials on startup
    try:
        service = get_google_service(cfg.google_credentials_file, cfg.google_token_file)
        tasklist_id = get_tasklist_id(service, cfg.google_tasks.list_name)
        log.info(f"  Google Tasks connected. List ID: {tasklist_id}")
    except Exception as e:
        log.error(f"Failed to connect to Google Tasks: {e}")
        sys.exit(1)

    # Main poll loop
    while True:
        try:
            # Re-create service each cycle to pick up token refreshes
            service = get_google_service(cfg.google_credentials_file, cfg.google_token_file)
            count = poll_once(service, tasklist_id, cfg)
            if count > 0:
                log.info(f"Processed {count} new task(s)")
            update_health()
        except Exception as e:
            log.error(f"Poll cycle failed: {e}", exc_info=True)

        time.sleep(cfg.google_tasks.poll_interval_seconds)


if __name__ == "__main__":
    main()
