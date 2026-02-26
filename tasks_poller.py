#!/usr/bin/env python3
"""Poll Google Tasks and route items into Apple Reminders/Notes via Penny core."""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

# Allow imports from this directory
sys.path.insert(0, str(Path(__file__).parent))

from config import get_config
from core import (
    SYNCED_TASKS_FILE,
    classify_and_route,
    is_processed,
    mark_processed,
    send_telegram,
    setup_logging,
)

log = setup_logging("tasks_poller")
HEALTH_FILE = Path("~/.penny/health_tasks.txt").expanduser()


# ===== Google Tasks helpers =====

def get_google_service(credentials_file: Path, token_file: Path):
    """Build authenticated Google Tasks service, refreshing token if needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/tasks"]

    if not token_file.exists():
        msg = f"No Google token found at {token_file}. Run scripts/google_auth.py first."
        send_telegram(f"❌ Penny Auth Error: {msg}")
        raise RuntimeError(msg)

    creds = Credentials.from_authorized_user_file(str(token_file), scopes)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            log.info("Refreshing Google OAuth token...")
            try:
                creds.refresh(Request())
                token_file.write_text(creds.to_json(), encoding="utf-8")
                log.info("Token refreshed.")
            except Exception as e:
                msg = f"Google token refresh failed: {e}. Run scripts/google_auth.py again."
                send_telegram(f"❌ Penny Auth Error: {msg}")
                raise RuntimeError(msg) from e
        else:
            msg = "Google credentials invalid and cannot be refreshed. Run scripts/google_auth.py again."
            send_telegram(f"❌ Penny Auth Error: {msg}")
            raise RuntimeError(msg)

    return build("tasks", "v1", credentials=creds, cache_discovery=False)


def get_tasklist_id(service, list_name: str) -> str:
    """Find the task list ID by name, falling back to @default."""
    result = service.tasklists().list().execute()
    for tasklist in result.get("items", []):
        if tasklist.get("title") == list_name:
            return tasklist["id"]
    log.warning("Task list '%s' not found, using @default", list_name)
    return "@default"


def _mark_task_complete(service, tasklist_id: str, task: dict, task_title: str) -> bool:
    task_id = task.get("id", "")
    try:
        task["status"] = "completed"
        service.tasks().update(tasklist=tasklist_id, task=task_id, body=task).execute()
        log.info("Marked complete in Google Tasks: '%s'", task_title)
        return True
    except Exception as e:
        log.warning(
            "Could not mark '%s' complete in Tasks: %s. Will retry next poll.",
            task_title,
            e,
        )
        return False


# ===== Core poll logic =====

def poll_once(service, tasklist_id: str) -> int:
    """
    Poll for new tasks, classify and route them, mark complete in Tasks.
    Returns count of tasks successfully routed (whether or not complete-mark succeeded).
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
        task_id = str(task.get("id", "")).strip()
        task_title = str(task.get("title") or "").strip()

        if not task_id or not task_title:
            continue

        if is_processed(task_id, SYNCED_TASKS_FILE):
            # Already synced to Reminders/Notes — keep retrying completion in Tasks.
            try:
                task["status"] = "completed"
                service.tasks().update(tasklist=tasklist_id, task=task_id, body=task).execute()
                log.debug("Retried mark-complete for: '%s'", task_title)
            except Exception as e:
                log.warning("Retry mark-complete failed for '%s': %s", task_title, e)
            continue

        log.info("New task: '%s'", task_title)

        try:
            classify_and_route(task_title, source="Google Tasks")
        except Exception as e:
            # Leave it pending in Google Tasks so the next poll can retry.
            log.error("Routing failed for Google Task '%s': %s", task_title, e, exc_info=True)
            continue

        try:
            # Record as synced before marking complete so a Tasks API failure does not
            # duplicate work on the next poll.
            mark_processed(task_id, SYNCED_TASKS_FILE)
        except Exception as e:
            log.error("Failed to persist sync state for task '%s': %s", task_title, e, exc_info=True)
            # Routing already succeeded; still attempt completion to avoid duplicates.

        _mark_task_complete(service, tasklist_id, task, task_title)
        processed += 1

    return processed


def update_health() -> None:
    from datetime import datetime

    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(f"{datetime.now().isoformat()}|tasks_poller_ok:1\n", encoding="utf-8")


# ===== Main =====

def main() -> None:
    cfg = get_config()

    log.info("=" * 60)
    log.info("Penny Google Tasks Poller starting...")
    log.info("=" * 60)
    log.info("  Task list: %s", cfg.google_tasks.list_name)
    log.info("  Poll interval: %ss", cfg.google_tasks.poll_interval_seconds)
    log.info("  LLM model: %s", cfg.llm.model)

    try:
        service = get_google_service(cfg.google_credentials_file, cfg.google_token_file)
        tasklist_id = get_tasklist_id(service, cfg.google_tasks.list_name)
        log.info("  Google Tasks connected. List ID: %s", tasklist_id)
    except Exception as e:
        log.error("Failed to connect to Google Tasks: %s", e)
        sys.exit(1)

    while True:
        try:
            # Re-create service each cycle to pick up token refreshes.
            service = get_google_service(cfg.google_credentials_file, cfg.google_token_file)
            count = poll_once(service, tasklist_id)
            if count > 0:
                log.info("Processed %s new task(s)", count)
            update_health()
        except Exception as e:
            log.error("Poll cycle failed: %s", e, exc_info=True)

        time.sleep(cfg.google_tasks.poll_interval_seconds)


if __name__ == "__main__":
    main()
