import sys
import time
import logging
from pathlib import Path

# Allow imports from this directory
sys.path.insert(0, str(Path(__file__).parent))

from config import get_config
from core import (
    setup_logging,
    is_processed,
    mark_processed,
    classify_and_route,
    send_telegram,
    SYNCED_TASKS_FILE
)

log = setup_logging("tasks_poller")

HEALTH_FILE = Path("~/.penny/health_tasks.txt").expanduser()


# ===== Google Tasks helpers =====

def get_google_service(credentials_file: Path, token_file: Path):
    """Build authenticated Google Tasks service, refreshing token if needed."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    SCOPES = ["https://www.googleapis.com/auth/tasks"]

    if not token_file.exists():
        msg = f"No Google token found at {token_file}. Run scripts/google_auth.py first."
        send_telegram(f"❌ Penny Auth Error: {msg}")
        raise RuntimeError(msg)

    creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            log.info("Refreshing Google OAuth token...")
            try:
                creds.refresh(Request())
                token_file.write_text(creds.to_json())
                log.info("Token refreshed.")
            except Exception as e:
                msg = f"Google token refresh failed: {e}. Run scripts/google_auth.py again."
                send_telegram(f"❌ Penny Auth Error: {msg}")
                raise RuntimeError(msg)
        else:
            msg = "Google credentials invalid and cannot be refreshed. Run scripts/google_auth.py again."
            send_telegram(f"❌ Penny Auth Error: {msg}")
            raise RuntimeError(msg)

    return build("tasks", "v1", credentials=creds, cache_discovery=False)


def get_tasklist_id(service, list_name: str) -> str:
    """Find the task list ID by name, falling back to @default."""
    result = service.tasklists().list().execute()
    for tl in result.get("items", []):
        if tl["title"] == list_name:
            return tl["id"]
    log.warning(f"Task list '{list_name}' not found, using @default")
    return "@default"


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

        if is_processed(task_id, SYNCED_TASKS_FILE):
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

        # Process through core pipeline
        classify_and_route(task_title, source="Google Tasks")

        # Record as synced before marking complete (so a Tasks API failure
        # doesn't cause us to re-process on the next poll)
        mark_processed(task_id, SYNCED_TASKS_FILE)

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
    cfg = get_config()

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
