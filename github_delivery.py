"""Independent delivery stream: routes "project"-classified voice notes to
Janitor's triage command and reports the outcome as a threaded Slack reply.

Mirrors slack_delivery.py's outbox pattern: durable claim/lease, terminal
vs. retryable outcomes, receipts in the ledger. Never blocks or edits the
existing Slack delivery stream — only replies in its thread once this
stream reaches a terminal state.
"""

from __future__ import annotations

import json
import logging
import socket
import subprocess

from transcript_log import (
    claim_next_github_delivery,
    mark_github_delivery_failed,
    mark_github_delivery_no_match,
    mark_github_delivery_sent,
)
from slack_delivery import SlackTranscriptPost, _post_to_slack

log = logging.getLogger(__name__)

JANITOR_RUNNER = "/Users/macmini/.local/bin/janitor-runner"
TRIAGE_SUBPROCESS_TIMEOUT = 105
TRANSCRIPT_CHAR_CAP = 4000


def _claim_owner() -> str:
    return f"{socket.gethostname()}-{id(process_pending_github_deliveries)}"


def _run_janitor_triage(text: str, idempotency_key: str) -> dict:
    truncated = text[:TRANSCRIPT_CHAR_CAP]
    command = [
        JANITOR_RUNNER, "triage",
        "--text", truncated,
        "--idempotency-key", idempotency_key,
        "--json",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=TRIAGE_SUBPROCESS_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "reason": "triage_subprocess_timeout"}
    except OSError as exc:
        return {"status": "error", "reason": f"triage_subprocess_unavailable: {type(exc).__name__}"}

    if completed.returncode not in (0, 1):
        return {"status": "error", "reason": f"triage_unexpected_exit_{completed.returncode}"}
    try:
        parsed = json.loads(completed.stdout.strip())
    except json.JSONDecodeError:
        return {"status": "error", "reason": "triage_output_not_json"}
    if not isinstance(parsed, dict) or "status" not in parsed:
        return {"status": "error", "reason": "triage_output_missing_status"}
    return parsed


def _classify_triage_outcome(result: dict) -> str:
    status = result.get("status")
    if status == "filed":
        return "sent"
    if status == "no_match":
        return "no_match"
    return "retryable"


def _original_slack_thread(transcript_row_id: int) -> tuple[str, str] | None:
    """Return (channel_id, provider_ts) for the note's original Slack message, if sent."""
    from transcript_log import _get_conn  # module-private; matches slack_delivery.py's own access pattern

    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT channel_id, provider_ts FROM slack_deliveries "
            "WHERE transcript_row_id = ? AND provider_ts IS NOT NULL",
            (transcript_row_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return str(row["channel_id"]), str(row["provider_ts"])


def _reply_in_slack_thread(transcript_row_id: int, idempotency_key: str, text: str) -> None:
    thread = _original_slack_thread(transcript_row_id)
    if thread is None:
        log.warning(
            "No original Slack message to thread a GitHub-triage reply under (row=%s)",
            transcript_row_id,
        )
        return
    channel_id, provider_ts = thread
    message = SlackTranscriptPost(text=text, blocks=())
    _post_to_slack(
        channel_id, message, f"github-triage-{idempotency_key}", thread_ts=provider_ts,
    )


def process_pending_github_deliveries(limit: int = 20) -> int:
    owner = _claim_owner()
    processed = 0
    for _ in range(limit):
        claimed = claim_next_github_delivery(owner)
        if claimed is None:
            break
        delivery_id = claimed["id"]
        transcript_row_id = claimed["transcript_row_id"]
        idempotency_key = claimed["idempotency_key"]
        claim_token = claimed["github_claim_token"]

        result = _run_janitor_triage(claimed["transcript_text"], idempotency_key)
        outcome = _classify_triage_outcome(result)

        if outcome == "sent":
            mark_github_delivery_sent(
                delivery_id, result["repo"], result["issue_url"],
                claim_token=claim_token, claim_owner=owner,
            )
            _reply_in_slack_thread(
                transcript_row_id, idempotency_key,
                f"Filed as a GitHub issue: {result['issue_url']}",
            )
        elif outcome == "no_match":
            mark_github_delivery_no_match(delivery_id, claim_token=claim_token, claim_owner=owner)
            _reply_in_slack_thread(
                transcript_row_id, idempotency_key,
                "No confident repo match — not filed anywhere. File manually if needed.",
            )
        else:
            reason = result.get("reason", "unknown")
            mark_github_delivery_failed(
                delivery_id, reason, retry_after_seconds=60,
                claim_token=claim_token, claim_owner=owner,
            )
            # No Slack reply on a retryable failure — it may still succeed
            # on the next attempt, and a reply here would be premature noise.

        processed += 1
    return processed
