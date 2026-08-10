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
    classify_and_route,
    setup_logging,
)
from transcript_log import (
    InsertOutcome,
    get_transcript_by_hash,
    init_db,
    insert_transcript_result,
    record_archive_unavailable,
)

log = setup_logging("tasks_poller")
HEALTH_FILE = Path("~/.penny/health_tasks.txt").expanduser()


def _safe_exception_class(exc: BaseException) -> str:
    name = type(exc).__name__
    if name and len(name) <= 48 and name[0].isalpha() and all(
        character.isalnum() or character == "_" for character in name
    ):
        return name
    return "Exception"


# ===== Google Tasks helpers =====

def get_google_service(credentials_file: Path, token_file: Path):
    """Build authenticated Google Tasks service, refreshing token if needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/tasks"]

    if not token_file.exists():
        raise RuntimeError("google_token_missing")

    creds = Credentials.from_authorized_user_file(str(token_file), scopes)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            log.info("Refreshing Google OAuth token...")
            try:
                creds.refresh(Request())
                token_file.write_text(creds.to_json(), encoding="utf-8")
                log.info("Token refreshed.")
            except Exception as e:
                raise RuntimeError("google_token_refresh_failed") from None
        else:
            raise RuntimeError("google_credentials_invalid")

    return build("tasks", "v1", credentials=creds, cache_discovery=False)


def get_tasklist_id(service, list_name: str) -> str:
    """Find the task list ID by name, falling back to @default."""
    result = service.tasklists().list().execute()
    for tasklist in result.get("items", []):
        if tasklist.get("title") == list_name:
            return tasklist["id"]
    log.warning("Google task list fallback code=default")
    return "@default"


def _mark_task_complete(service, tasklist_id: str, task: dict, task_title: str) -> bool:
    task_id = task.get("id", "")
    try:
        task["status"] = "completed"
        service.tasks().update(tasklist=tasklist_id, task=task_id, body=task).execute()
        log.info("Marked Google Task complete id=%s", task_id)
        return True
    except Exception as e:
        log.warning(
            "Could not mark Google Task complete id=%s class=%s",
            task_id,
            _safe_exception_class(e),
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
        log.debug("No pending Google Tasks count=0")
        return 0

    log.info("Fetched pending Google Tasks count=%s", len(tasks))

    processed = 0
    for task in tasks:
        task_id = str(task.get("id", "")).strip()
        task_title = str(task.get("title") or "").strip()

        if not task_id or not task_title:
            continue

        result = insert_transcript_result(
            content_hash=task_id,
            source="Google Tasks",
            transcript=task_title,
            enqueue_slack=False,
            archive_unavailable_reason="no_raw_audio",
        )

        if result.outcome is InsertOutcome.FAILED:
            log.error("Google Task persistence failed id=%s", task_id)
            continue

        if result.outcome is InsertOutcome.DUPLICATE:
            canonical = get_transcript_by_hash(task_id)
            if canonical is None:
                log.error("Google Task duplicate missing canonical row id=%s", task_id)
                continue
            row_id = int(canonical["id"])
            try:
                record_archive_unavailable(
                    row_id,
                    availability_status="not_applicable",
                    reason_code="no_raw_audio",
                )
            except Exception as exc:
                log.error(
                    "Google Task archive marker failed id=%s class=%s",
                    task_id,
                    _safe_exception_class(exc),
                )
                continue
            if canonical.get("status") in {"routed", "processed"}:
                _mark_task_complete(service, tasklist_id, task, task_id)
                processed += 1
                continue
            transcript_to_route = str(canonical["transcript"])
            source_to_route = str(canonical["source"])
        else:
            row_id = int(result.row_id)
            transcript_to_route = task_title
            source_to_route = "Google Tasks"

        try:
            classify_and_route(
                transcript_to_route,
                source=source_to_route,
                row_id=row_id,
                allow_maya=False,
            )
        except Exception as e:
            # Leave it pending in Google Tasks so the next poll can retry.
            log.error(
                "Google Task routing failed id=%s class=%s",
                task_id,
                _safe_exception_class(e),
            )
            continue

        canonical = get_transcript_by_hash(task_id)
        if canonical is None or canonical.get("status") not in {"routed", "processed"}:
            log.warning("Google Task route not durably confirmed id=%s", task_id)
            continue

        _mark_task_complete(service, tasklist_id, task, task_id)
        processed += 1

    return processed


def update_health() -> None:
    from datetime import datetime

    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(f"{datetime.now().isoformat()}|tasks_poller_ok:1\n", encoding="utf-8")


# ===== Main =====

def main() -> None:
    init_db()
    cfg = get_config()

    log.info("=" * 60)
    log.info("Penny Google Tasks Poller starting...")
    log.info("=" * 60)
    log.info("  Poll interval: %ss", cfg.google_tasks.poll_interval_seconds)

    try:
        service = get_google_service(cfg.google_credentials_file, cfg.google_token_file)
        tasklist_id = get_tasklist_id(service, cfg.google_tasks.list_name)
        log.info("Google Tasks connected")
    except Exception as e:
        log.error(
            "Google Tasks connection failed class=%s",
            _safe_exception_class(e),
        )
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
            log.error(
                "Google Tasks poll cycle failed class=%s",
                _safe_exception_class(e),
            )

        time.sleep(cfg.google_tasks.poll_interval_seconds)


if __name__ == "__main__":
    main()
