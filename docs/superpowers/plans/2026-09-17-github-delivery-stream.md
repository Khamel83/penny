# Penny `github_delivery` Stream Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new independent delivery stream that, for voice notes classified `project`, calls Janitor's `triage` command locally to file a GitHub issue in the right fleet repo, and posts a threaded Slack reply reporting the outcome — without ever touching or delaying the existing Slack delivery stream.

**Architecture:** Mirrors `slack_delivery.py`'s existing outbox pattern exactly: a new `github_deliveries` SQLite table with the same claim-token/lease/optimistic-concurrency shape as `slack_deliveries`, drained by the same kind of bounded per-tick call from `watcher.py`'s ingest pass. On drain, it shells out to `janitor-runner triage` as a local subprocess (absolute path, no PATH dependency), classifies the result as terminal-sent / terminal-no-match / retryable-failure, and posts a Slack thread reply using the existing `_post_to_slack` (which already supports `thread_ts`).

**Tech Stack:** Python 3, existing Penny modules (`transcript_log.py`, `slack_delivery.py`, `core.py`, `classifier.py`, `doctor.py`, `watcher.py`), stdlib `subprocess`/`json`/`secrets`, `pytest`/`unittest`.

**Spec:** `/Volumes/2TB_SSD/GitHub/janitor/docs/superpowers/specs/2026-09-17-penny-github-issue-triage-design.md` (Penny-side portions: classifier category, outbox/lease/receipt stream, Slack threaded-reply signal, Doctor probe, launchd env).

**Depends on:** `/Volumes/2TB_SSD/GitHub/janitor/docs/superpowers/plans/2026-09-17-janitor-triage-command.md` for the actual `janitor triage` CLI contract this plan calls. This plan's own tests mock that subprocess call, so it can be implemented and tested independently, but a real end-to-end delivery needs the Janitor-side plan done first (or at minimum, `janitor triage` returning the documented `{"status": ...}` JSON shapes).

## Global Constraints

- `GITHUB_CLAIM_LEASE_SECONDS = 180`. Subprocess timeout for the `janitor-runner triage` call: 105s (strictly inside the lease, leaving ~75s margin — matches Janitor's own internal 75s worst-case budget from the sibling plan).
- Transcript text passed to `janitor triage` is truncated to 4000 characters — the same cap `classifier.py` already applies before its own LLM call.
- Terminal outcomes: `sent` (issue filed or found via idempotency) and `terminal_no_match` (Stage 1/2 found nothing) — neither is retried. `retryable_failure` (subprocess crash, timeout, non-JSON output, or `{"status": "error"}`) retries with backoff, capped at `GITHUB_MAX_ATTEMPTS = 5` (matches `SLACK_MAX_ATTEMPTS`'s existing convention), after which it becomes terminal `failed`.
- Slack delivery is never blocked, gated, or edited by this stream. The only Slack interaction is a **threaded reply** to the original message, posted only after `github_delivery` reaches a terminal state.
- `janitor-runner` is invoked by absolute path (`/Users/macmini/.local/bin/janitor-runner`), the same wrapper the SSH/systemd layer already uses — never a bare `janitor`/`g2k` PATH lookup, since `com.penny.watcher`'s launchd `PATH` does not include `~/.local/bin`.

---

## Task 1: `classifier.py` — add the `project` category

**Files:**
- Modify: `classifier.py`
- Test: existing classifier test file (find it first — likely `tests/test_classifier.py`; match its exact style)

- [ ] **Step 1: Write the failing test**

Add to the existing classifier test file:

```python
def test_project_is_a_valid_category(self):
    self.assertIn("project", CATEGORIES)
```

This is deliberately a single, minimal test: the change itself is a one-line addition to an allowlist, and `classify()`'s existing unknown-category-falls-back-to-inbox behavior (`tests/test_core_and_classifier.py`) is pre-existing logic this change doesn't touch — it doesn't need a new test to re-prove it still works for categories other than `project`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/2TB_SSD/GitHub/penny && venv/bin/python -m pytest tests/test_classifier.py -k project -v`
Expected: FAIL — `project` not in `CATEGORIES`

- [ ] **Step 3: Add the category and its prompt guidance**

In `classifier.py`, change:

```python
CATEGORIES = ["groceries", "errands", "home", "health", "work", "kids", "inbox"]
```

to:

```python
CATEGORIES = ["groceries", "errands", "home", "health", "work", "kids", "inbox", "project"]
```

And extend `SYSTEM_PROMPT`'s category list (the block starting `Categories (pick exactly one per item):`) by adding, after the `kids:` line:

```
- project: a software/code task, bug, or idea for one of the user's own software projects or repositories — something that belongs in a GitHub issue, not a personal to-do
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Volumes/2TB_SSD/GitHub/penny && venv/bin/python -m pytest tests/test_classifier.py -v`
Expected: PASS, no regressions

- [ ] **Step 5: Commit**

```bash
git add classifier.py tests/test_classifier.py
git commit -m "feat: add project category to voice-note classifier"
```

---

## Task 2: `transcript_log.py` — `github_deliveries` table and claim/mark functions

**Files:**
- Modify: `transcript_log.py`
- Test: `tests/test_github_delivery_ledger.py` (new file — mirrors whatever pattern the existing Slack claim/lease tests use; find and read them first, e.g. search for `claim_next_slack_delivery` in `tests/`)

**Interfaces:**
- Produces: `queue_github_delivery(transcript_id: int, idempotency_key: str) -> None`
- Produces: `claim_next_github_delivery(claim_owner: str, *, lease_seconds: int = GITHUB_CLAIM_LEASE_SECONDS) -> dict[str, Any] | None`
- Produces: `mark_github_delivery_sent(delivery_id: int, repo: str, issue_url: str, *, claim_token: str, claim_owner: str) -> None`
- Produces: `mark_github_delivery_no_match(delivery_id: int, *, claim_token: str, claim_owner: str) -> None`
- Produces: `mark_github_delivery_failed(delivery_id: int, error_message: str, retry_after_seconds: int = 60, *, claim_token: str, claim_owner: str) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_github_delivery_ledger.py
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import transcript_log as tl


class GithubDeliveryLedgerTestCase(unittest.TestCase):
    def setUp(self):
        self.db_dir = tempfile.mkdtemp()
        self.db_path = Path(self.db_dir) / "test_transcripts.db"
        patch.object(tl, "TRANSCRIPT_DB_PATH", self.db_path).start()
        patch.object(
            tl, "LEGACY_VOICE_MEMO_CURSOR_PATH", Path(self.db_dir) / "legacy_last_pk.txt"
        ).start()
        tl.init_db()
        self.addCleanup(patch.stopall)
        conn = tl._get_conn()
        conn.execute(
            "INSERT INTO transcripts (source, transcript, ingest_state, quality_status) "
            "VALUES ('voice_memo', 'fix the widget sync bug', 'complete', 'passed')"
        )
        conn.commit()
        self.transcript_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

    def test_queue_then_claim_returns_row(self):
        tl.queue_github_delivery(self.transcript_id, "abc123")
        claimed = tl.claim_next_github_delivery("worker-1")
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["transcript_row_id"], self.transcript_id)
        self.assertEqual(claimed["idempotency_key"], "abc123")
        self.assertEqual(claimed["status"], "delivering")

    def test_second_claim_before_lease_expiry_returns_none(self):
        tl.queue_github_delivery(self.transcript_id, "abc123")
        tl.claim_next_github_delivery("worker-1", lease_seconds=180)
        second = tl.claim_next_github_delivery("worker-2", lease_seconds=180)
        self.assertIsNone(second)

    def test_mark_sent_is_terminal_and_idempotent_on_same_url(self):
        tl.queue_github_delivery(self.transcript_id, "abc123")
        claimed = tl.claim_next_github_delivery("worker-1")
        tl.mark_github_delivery_sent(
            claimed["id"], "Khamel83/widget-tool", "https://github.com/Khamel83/widget-tool/issues/9",
            claim_token=claimed["github_claim_token"], claim_owner="worker-1",
        )
        # A retried call with the same outcome must not raise.
        tl.mark_github_delivery_sent(
            claimed["id"], "Khamel83/widget-tool", "https://github.com/Khamel83/widget-tool/issues/9",
            claim_token=claimed["github_claim_token"], claim_owner="worker-1",
        )
        self.assertIsNone(tl.claim_next_github_delivery("worker-2"))

    def test_mark_no_match_is_terminal(self):
        tl.queue_github_delivery(self.transcript_id, "abc123")
        claimed = tl.claim_next_github_delivery("worker-1")
        tl.mark_github_delivery_no_match(
            claimed["id"], claim_token=claimed["github_claim_token"], claim_owner="worker-1"
        )
        self.assertIsNone(tl.claim_next_github_delivery("worker-2"))

    def test_mark_failed_retries_until_max_attempts_then_becomes_terminal(self):
        tl.queue_github_delivery(self.transcript_id, "abc123")
        for _ in range(tl.GITHUB_MAX_ATTEMPTS):
            claimed = tl.claim_next_github_delivery("worker-1", lease_seconds=180)
            self.assertIsNotNone(claimed)
            tl.mark_github_delivery_failed(
                claimed["id"], "boom", retry_after_seconds=0,
                claim_token=claimed["github_claim_token"], claim_owner="worker-1",
            )
        self.assertIsNone(tl.claim_next_github_delivery("worker-2"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Volumes/2TB_SSD/GitHub/penny && venv/bin/python -m pytest tests/test_github_delivery_ledger.py -v`
Expected: FAIL — `AttributeError: module 'transcript_log' has no attribute 'queue_github_delivery'`

- [ ] **Step 3: Add the constants and schema**

Near `SLACK_CLAIM_LEASE_SECONDS`/`MAYA_CLAIM_LEASE_SECONDS` (around line 34-46):

```python
GITHUB_CLAIM_LEASE_SECONDS = 180
GITHUB_MAX_ATTEMPTS = 5
```

In `init_db()`, right after the existing `slack_deliveries` table/index creation block (after the `idx_slack_deliveries_due` index, before the `quality_failure_slack_deliveries` table):

```python
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS github_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_row_id INTEGER NOT NULL,
                idempotency_key TEXT NOT NULL,
                transcript_text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT,
                last_error TEXT,
                repo TEXT,
                issue_url TEXT,
                github_claim_token TEXT,
                github_claim_owner TEXT,
                github_claimed_at TEXT,
                github_claim_expires_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT,
                UNIQUE(transcript_row_id),
                UNIQUE(idempotency_key),
                FOREIGN KEY(transcript_row_id) REFERENCES transcripts(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_github_deliveries_due "
            "ON github_deliveries(status, next_attempt_at)"
        )
```

- [ ] **Step 4: Add the queue/claim/mark functions**

Place these near the Slack equivalents (after `claim_next_slack_delivery`, before `get_pending_quality_failure_deliveries`), following the exact same atomic-claim/optimistic-concurrency shape:

```python
def queue_github_delivery(transcript_id: int, idempotency_key: str) -> None:
    conn = None
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT transcript FROM transcripts WHERE id = ?",
            (transcript_id,),
        ).fetchone()
        if row is None:
            return
        conn.execute(
            """INSERT OR IGNORE INTO github_deliveries (
                   transcript_row_id, idempotency_key, transcript_text
               ) VALUES (?, ?, ?)""",
            (transcript_id, idempotency_key, str(row["transcript"])),
        )
        conn.commit()
    except Exception as e:
        log.error("Failed to queue GitHub delivery transcript=%s: %s", transcript_id, e)
    finally:
        if conn:
            conn.close()


def claim_next_github_delivery(
    claim_owner: str,
    *,
    lease_seconds: int = GITHUB_CLAIM_LEASE_SECONDS,
) -> dict[str, Any] | None:
    """Atomically lease one due GitHub-delivery row, including an expired prior lease."""
    owner = str(claim_owner).strip()
    if not owner:
        raise ValueError("GitHub claim owner is required")
    lease = max(GITHUB_CLAIM_LEASE_SECONDS, min(int(lease_seconds), 3600))
    claim_token = secrets.token_hex(16)
    conn = None
    try:
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT deliveries.id
            FROM github_deliveries AS deliveries
            LEFT JOIN transcripts
              ON transcripts.id = deliveries.transcript_row_id
            WHERE transcripts.quality_status = 'passed'
              AND (
                    (
                        deliveries.status = 'pending'
                        AND (
                            deliveries.next_attempt_at IS NULL
                            OR deliveries.next_attempt_at <= datetime('now')
                        )
                    )
                    OR (
                        deliveries.status = 'delivering'
                        AND (
                            deliveries.github_claim_expires_at IS NULL
                            OR julianday(deliveries.github_claim_expires_at) IS NULL
                            OR julianday(deliveries.github_claim_expires_at)
                               <= julianday('now')
                        )
                    )
                  )
            ORDER BY deliveries.created_at ASC, deliveries.id ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            conn.rollback()
            return None
        delivery_id = int(row["id"])
        cursor = conn.execute(
            """
            UPDATE github_deliveries
            SET status = 'delivering',
                github_claim_token = ?,
                github_claim_owner = ?,
                github_claimed_at = datetime('now'),
                github_claim_expires_at = datetime('now', '+' || ? || ' seconds'),
                updated_at = datetime('now')
            WHERE id = ?
              AND (
                    (
                        status = 'pending'
                        AND (next_attempt_at IS NULL OR next_attempt_at <= datetime('now'))
                    )
                    OR (
                        status = 'delivering'
                        AND (
                            github_claim_expires_at IS NULL
                            OR julianday(github_claim_expires_at) IS NULL
                            OR julianday(github_claim_expires_at) <= julianday('now')
                        )
                    )
                  )
            """,
            (claim_token, owner, lease, delivery_id),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return None
        claimed = conn.execute(
            """
            SELECT id, transcript_row_id, idempotency_key, transcript_text, status,
                   attempt_count, next_attempt_at, last_error, repo, issue_url,
                   github_claim_token, github_claim_owner, github_claimed_at,
                   github_claim_expires_at, created_at, updated_at, completed_at
            FROM github_deliveries
            WHERE id = ?
            """,
            (delivery_id,),
        ).fetchone()
        conn.commit()
        return dict(claimed) if claimed is not None else None
    except Exception as e:
        if conn:
            conn.rollback()
        log.error("Failed to claim GitHub delivery: %s", _safe_exception_class(e))
        raise
    finally:
        if conn:
            conn.close()


def _validate_github_claim_arguments(claim_token: str | None, claim_owner: str | None) -> None:
    if (claim_token is None) != (claim_owner is None):
        raise ValueError("GitHub claim token and owner must be provided together")
    if claim_token is not None and (
        not str(claim_token).strip() or not str(claim_owner).strip()
    ):
        raise ValueError("GitHub claim token and owner must be nonempty")


def _github_claim_matches(row, claim_token: str | None, claim_owner: str | None) -> bool:
    return (
        claim_token is not None
        and claim_owner is not None
        and row["github_claim_token"] == claim_token
        and row["github_claim_owner"] == claim_owner
    )


def mark_github_delivery_sent(
    delivery_id: int,
    repo: str,
    issue_url: str,
    *,
    claim_token: str | None = None,
    claim_owner: str | None = None,
) -> None:
    _validate_github_claim_arguments(claim_token, claim_owner)
    conn = None
    try:
        conn = _get_conn()
        current = conn.execute(
            "SELECT status, issue_url, github_claim_token, github_claim_owner "
            "FROM github_deliveries WHERE id = ?",
            (delivery_id,),
        ).fetchone()
        if current is None:
            raise LookupError("GitHub delivery row does not exist")
        if current["status"] == "sent":
            if current["issue_url"] == issue_url:
                return
            raise ValueError("GitHub sent receipt conflicts with terminal state")
        if current["status"] == "delivering" and not _github_claim_matches(
            current, claim_token, claim_owner
        ):
            raise ValueError("GitHub claim owner mismatch")
        cursor = conn.execute(
            """UPDATE github_deliveries
               SET status = 'sent',
                   repo = ?,
                   issue_url = ?,
                   last_error = NULL,
                   next_attempt_at = NULL,
                   github_claim_token = NULL,
                   github_claim_owner = NULL,
                   github_claimed_at = NULL,
                   github_claim_expires_at = NULL,
                   completed_at = datetime('now'),
                   updated_at = datetime('now')
               WHERE id = ?
                 AND status IN ('pending', 'delivering')
                 AND (
                       status != 'delivering'
                       OR (github_claim_token = ? AND github_claim_owner = ?)
                     )""",
            (repo, issue_url, delivery_id, claim_token, claim_owner),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            raise ValueError("GitHub sent receipt conflicts with terminal state")
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        log.error("Failed to mark GitHub delivery sent id=%s: %s", delivery_id, _safe_exception_class(e))
        raise
    finally:
        if conn:
            conn.close()


def mark_github_delivery_no_match(
    delivery_id: int,
    *,
    claim_token: str | None = None,
    claim_owner: str | None = None,
) -> None:
    _validate_github_claim_arguments(claim_token, claim_owner)
    conn = None
    try:
        conn = _get_conn()
        current = conn.execute(
            "SELECT status, github_claim_token, github_claim_owner "
            "FROM github_deliveries WHERE id = ?",
            (delivery_id,),
        ).fetchone()
        if current is None:
            raise LookupError("GitHub delivery row does not exist")
        if current["status"] == "delivering" and not _github_claim_matches(
            current, claim_token, claim_owner
        ):
            raise ValueError("GitHub claim owner mismatch")
        cursor = conn.execute(
            """UPDATE github_deliveries
               SET status = 'terminal_no_match',
                   last_error = NULL,
                   next_attempt_at = NULL,
                   github_claim_token = NULL,
                   github_claim_owner = NULL,
                   github_claimed_at = NULL,
                   github_claim_expires_at = NULL,
                   completed_at = datetime('now'),
                   updated_at = datetime('now')
               WHERE id = ?
                 AND status IN ('pending', 'delivering')
                 AND (
                       status != 'delivering'
                       OR (github_claim_token = ? AND github_claim_owner = ?)
                     )""",
            (delivery_id, claim_token, claim_owner),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            raise ValueError("GitHub no-match receipt conflicts with terminal state")
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        log.error("Failed to mark GitHub delivery no_match id=%s: %s", delivery_id, _safe_exception_class(e))
        raise
    finally:
        if conn:
            conn.close()


def mark_github_delivery_failed(
    delivery_id: int,
    error_message: str,
    retry_after_seconds: int = 60,
    *,
    claim_token: str | None = None,
    claim_owner: str | None = None,
) -> None:
    _validate_github_claim_arguments(claim_token, claim_owner)
    conn = None
    try:
        conn = _get_conn()
        safe_error = _safe_delivery_error(error_message)
        delay = max(0, min(int(retry_after_seconds), 3600))
        current = conn.execute(
            "SELECT status, attempt_count, github_claim_token, github_claim_owner "
            "FROM github_deliveries WHERE id = ?",
            (delivery_id,),
        ).fetchone()
        if current is None:
            raise LookupError("GitHub delivery row does not exist")
        if current["status"] == "delivering" and not _github_claim_matches(
            current, claim_token, claim_owner
        ):
            raise ValueError("GitHub claim owner mismatch")
        cursor = conn.execute(
            """UPDATE github_deliveries
               SET status = CASE
                       WHEN COALESCE(attempt_count, 0) + 1 >= ? THEN 'failed'
                       ELSE 'pending'
                   END,
                   attempt_count = COALESCE(attempt_count, 0) + 1,
                   last_error = ?,
                   next_attempt_at = CASE
                       WHEN COALESCE(attempt_count, 0) + 1 >= ? THEN NULL
                       ELSE datetime('now', '+' || ? || ' seconds')
                   END,
                   github_claim_token = NULL,
                   github_claim_owner = NULL,
                   github_claimed_at = NULL,
                   github_claim_expires_at = NULL,
                   completed_at = CASE
                       WHEN COALESCE(attempt_count, 0) + 1 >= ? THEN datetime('now')
                       ELSE NULL
                   END,
                   updated_at = datetime('now')
               WHERE id = ?
                 AND status IN ('pending', 'delivering')
                 AND (
                       status != 'delivering'
                       OR (github_claim_token = ? AND github_claim_owner = ?)
                     )""",
            (
                GITHUB_MAX_ATTEMPTS, safe_error, GITHUB_MAX_ATTEMPTS, delay,
                GITHUB_MAX_ATTEMPTS, delivery_id, claim_token, claim_owner,
            ),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            raise ValueError("GitHub failure receipt conflicts with terminal state")
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        log.error("Failed to mark GitHub delivery failed id=%s: %s", delivery_id, _safe_exception_class(e))
        raise
    finally:
        if conn:
            conn.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Volumes/2TB_SSD/GitHub/penny && venv/bin/python -m pytest tests/test_github_delivery_ledger.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Run the full transcript_log test suite, then commit**

Run: `cd /Volumes/2TB_SSD/GitHub/penny && venv/bin/python -m pytest tests/test_transcript_log.py tests/test_github_delivery_ledger.py -v`
Expected: PASS, no regressions to existing Slack/Maya ledger tests

```bash
git add transcript_log.py tests/test_github_delivery_ledger.py
git commit -m "feat: add github_deliveries ledger table and claim/mark functions"
```

---

## Task 3: `github_delivery.py` — drain loop, subprocess call, Slack thread reply

**Files:**
- Create: `github_delivery.py`
- Test: `tests/test_github_delivery.py`

**Interfaces:**
- Consumes: `transcript_log.claim_next_github_delivery`, `mark_github_delivery_sent`, `mark_github_delivery_no_match`, `mark_github_delivery_failed` (Task 2).
- Consumes: `slack_delivery._post_to_slack(channel_id, message, client_msg_id, *, thread_ts=None) -> str` and `slack_delivery.SlackTranscriptPost` (existing).
- Produces: `process_pending_github_deliveries(limit: int = 20) -> int` — returns count of deliveries reaching a terminal state this pass.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_github_delivery.py
import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from github_delivery import (
    _classify_triage_outcome,
    _run_janitor_triage,
    process_pending_github_deliveries,
)


class RunJanitorTriageTestCase(unittest.TestCase):
    def test_parses_filed_json_from_stdout(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"status": "filed", "repo": "Khamel83/x", "issue_url": "https://x/1"}\n',
            stderr="",
        )
        with patch("github_delivery.subprocess.run", return_value=completed):
            result = _run_janitor_triage("some note", "key123")
        self.assertEqual(result, {"status": "filed", "repo": "Khamel83/x", "issue_url": "https://x/1"})

    def test_timeout_returns_error_status(self):
        with patch("github_delivery.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[], timeout=105)):
            result = _run_janitor_triage("some note", "key123")
        self.assertEqual(result["status"], "error")

    def test_nonzero_exit_returns_error_status(self):
        completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
        with patch("github_delivery.subprocess.run", return_value=completed):
            result = _run_janitor_triage("some note", "key123")
        self.assertEqual(result["status"], "error")

    def test_invokes_janitor_runner_by_absolute_path(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout='{"status": "no_match"}', stderr="")
        with patch("github_delivery.subprocess.run", return_value=completed) as run:
            _run_janitor_triage("some note", "key123")
        command = run.call_args.args[0]
        self.assertEqual(command[0], "/Users/macmini/.local/bin/janitor-runner")
        self.assertIn("triage", command)


class ClassifyTriageOutcomeTestCase(unittest.TestCase):
    def test_filed_is_sent(self):
        self.assertEqual(_classify_triage_outcome({"status": "filed"}), "sent")

    def test_no_match_is_terminal_no_match(self):
        self.assertEqual(_classify_triage_outcome({"status": "no_match"}), "no_match")

    def test_error_is_retryable(self):
        self.assertEqual(_classify_triage_outcome({"status": "error", "reason": "x"}), "retryable")

    def test_unrecognized_shape_is_retryable(self):
        self.assertEqual(_classify_triage_outcome({"unexpected": True}), "retryable")


class ProcessPendingGithubDeliveriesTestCase(unittest.TestCase):
    def test_filed_outcome_marks_sent_and_posts_thread_reply(self):
        claimed = {
            "id": 1, "transcript_row_id": 42, "idempotency_key": "key123",
            "transcript_text": "fix the widget bug", "github_claim_token": "tok",
        }
        with (
            patch("github_delivery.claim_next_github_delivery", side_effect=[claimed, None]),
            patch(
                "github_delivery._run_janitor_triage",
                return_value={"status": "filed", "repo": "Khamel83/x", "issue_url": "https://x/1"},
            ),
            patch("github_delivery.mark_github_delivery_sent") as mark_sent,
            patch("github_delivery._reply_in_slack_thread") as reply,
        ):
            count = process_pending_github_deliveries(limit=20)
        self.assertEqual(count, 1)
        mark_sent.assert_called_once_with(
            1, "Khamel83/x", "https://x/1", claim_token="tok", claim_owner=unittest.mock.ANY,
        )
        reply.assert_called_once()
        self.assertIn("https://x/1", reply.call_args.args[-1])

    def test_no_match_outcome_marks_no_match_and_posts_thread_reply(self):
        claimed = {
            "id": 1, "transcript_row_id": 42, "idempotency_key": "key123",
            "transcript_text": "buy milk", "github_claim_token": "tok",
        }
        with (
            patch("github_delivery.claim_next_github_delivery", side_effect=[claimed, None]),
            patch("github_delivery._run_janitor_triage", return_value={"status": "no_match"}),
            patch("github_delivery.mark_github_delivery_no_match") as mark_no_match,
            patch("github_delivery._reply_in_slack_thread") as reply,
        ):
            process_pending_github_deliveries(limit=20)
        mark_no_match.assert_called_once()
        reply.assert_called_once()

    def test_error_outcome_marks_failed_and_does_not_post_thread_reply(self):
        claimed = {
            "id": 1, "transcript_row_id": 42, "idempotency_key": "key123",
            "transcript_text": "fix the widget bug", "github_claim_token": "tok",
        }
        with (
            patch("github_delivery.claim_next_github_delivery", side_effect=[claimed, None]),
            patch("github_delivery._run_janitor_triage", return_value={"status": "error", "reason": "boom"}),
            patch("github_delivery.mark_github_delivery_failed") as mark_failed,
            patch("github_delivery._reply_in_slack_thread") as reply,
        ):
            process_pending_github_deliveries(limit=20)
        mark_failed.assert_called_once()
        reply.assert_not_called()

    def test_nothing_pending_returns_zero(self):
        with patch("github_delivery.claim_next_github_delivery", return_value=None):
            count = process_pending_github_deliveries(limit=20)
        self.assertEqual(count, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Volumes/2TB_SSD/GitHub/penny && venv/bin/python -m pytest tests/test_github_delivery.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'github_delivery'`

- [ ] **Step 3: Write the implementation**

```python
# github_delivery.py
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
```

Note on `get_conn_for_read` in the import block: if `transcript_log.py` has no such helper (likely — the codebase mostly uses `_get_conn()` directly per-call, as shown in `_original_slack_thread` below), remove that import line; it's listed only as a signpost to check. `_original_slack_thread` already does the correct thing by importing `_get_conn` directly, matching the rest of the module's pattern.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Volumes/2TB_SSD/GitHub/penny && venv/bin/python -m pytest tests/test_github_delivery.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add github_delivery.py tests/test_github_delivery.py
git commit -m "feat: add github_delivery outbox stream with Slack thread-reply signal"
```

---

## Task 4: Wire into `core.py`, `watcher.py`, `doctor.py`, and the launchd template

**Files:**
- Modify: `core.py` (queue on `project`-classified notes)
- Modify: `watcher.py` (drain the new outbox each ingest pass)
- Modify: `doctor.py` (local-only readiness probe)
- Modify: `launchd/com.penny.watcher.plist.template` (document the `gh` credential requirement)
- Test: extend existing test files for each (`tests/test_core.py` or equivalent, `tests/test_doctor.py`)

- [ ] **Step 1: Write the failing test for the `core.py` queueing hook**

The routing entrypoint is `core.classify_and_route(transcript, source, row_id=None, duration_seconds=None, allow_maya=False)`, tested in `tests/test_core_and_classifier.py`. Add, matching that file's exact `patch.object(core, ...)` style (see its existing `test_duplicate_classifier_items_have_one_effect`):

```python
def test_project_item_queues_github_delivery(self) -> None:
    receipt = AppleEffectReceipt("e" * 64, "reminder", "rem-id", "succeeded", actual_target="Project", transcript_id=46)
    with (
        patch.object(core, "detect_content_type", return_value="action_items"),
        patch.object(core, "classify", return_value={"items": [
            {"item": "fix the widget sync bug", "category": "project"},
        ]}),
        patch.object(core, "ensure_reminder", return_value=receipt),
        patch.object(core, "update_transcript_progress", return_value=True),
        patch.object(core, "mark_routed", return_value=True),
        patch.object(core, "queue_github_delivery") as queue_github,
    ):
        core.classify_and_route("fix the widget sync bug", source="iCloud", row_id=46)
    queue_github.assert_called_once_with(46, idempotency_key="penny-row-46")


def test_non_project_item_does_not_queue_github_delivery(self) -> None:
    receipt = AppleEffectReceipt("f" * 64, "reminder", "rem-id", "succeeded", actual_target="Groceries", transcript_id=47)
    with (
        patch.object(core, "detect_content_type", return_value="action_items"),
        patch.object(core, "classify", return_value={"items": [{"item": "buy milk", "category": "groceries"}]}),
        patch.object(core, "ensure_reminder", return_value=receipt),
        patch.object(core, "update_transcript_progress", return_value=True),
        patch.object(core, "mark_routed", return_value=True),
        patch.object(core, "queue_github_delivery") as queue_github,
    ):
        core.classify_and_route("buy milk", source="iCloud", row_id=47)
    queue_github.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Volumes/2TB_SSD/GitHub/penny && venv/bin/python -m pytest tests/test_core_and_classifier.py -k queues_github_delivery -v`
Expected: FAIL — `AttributeError: <module 'core'> does not have the attribute 'queue_github_delivery'` (nothing to patch yet)

- [ ] **Step 3: Add the hook in `core.py`**

Add the import near `core.py`'s other `transcript_log` imports (alongside wherever `mark_routed`/`update_transcript_progress` are already imported from `transcript_log`):

```python
from transcript_log import queue_github_delivery
```

In `classify_and_route`, right after the `for entry in items:` loop finishes (after `routed_count += 1`, before the `effect_row_id = _require_effect_row(row_id)` / `mark_routed(effect_row_id, result, f"{routed_count} reminder(s)")` lines), add:

```python
        if any(str(entry.get("category", "")).strip().lower() == "project" for entry in items):
            queue_github_delivery(row_id, idempotency_key=f"penny-row-{row_id}")
```

The idempotency key is deterministic from `row_id` rather than a random token — `github_deliveries.transcript_row_id` already has a `UNIQUE` constraint (Task 2), so a second call for the same row is naturally a no-op via `INSERT OR IGNORE` in `queue_github_delivery`, and a deterministic key means nothing needs to be threaded through beyond `row_id` itself.

- [ ] **Step 4: Run tests to verify they pass, then commit**

Run: `cd /Volumes/2TB_SSD/GitHub/penny && venv/bin/python -m pytest tests/test_core_and_classifier.py -v`
Expected: PASS, no regressions

```bash
git add core.py tests/test_core_and_classifier.py
git commit -m "feat: queue github_delivery for project-classified notes"
```

- [ ] **Step 5: Wire the drain into `watcher.py`'s ingest pass**

In `watcher.py`, add the import near the existing `from slack_delivery import process_pending_slack` line:

```python
from github_delivery import process_pending_github_deliveries
```

Add a wrapper mirroring `_process_slack_outbox`/`_process_maya_outbox` (near those functions):

```python
def _process_github_outbox() -> None:
    try:
        delivered = process_pending_github_deliveries(limit=1)
        if delivered:
            log.info("Processed %s GitHub triage delivery(ies)", delivered)
    except Exception as e:
        log.error("GitHub outbox processing failed (class=%s)", type(e).__name__)
```

Add it to `_process_ingest_pass()`'s `operations` tuple, alongside the other outbox processors:

```python
    operations = (
        lambda: reconcile_linked_voice_memo_terminal_states(limit=100),
        lambda: _process_db_batch(get_new_recordings()),
        lambda: _retry_voice_memo_recordings(FILE_SCAN_PROCESS_LIMIT),
        lambda: _process_disk_backlog(FILE_SCAN_PROCESS_LIMIT),
        lambda: _retry_pending_routes(limit=5),
        lambda: _reconcile_archive_backfill(cfg.archive.delivery_batch_limit),
        lambda: _reconcile_published_archives(cfg.archive.delivery_batch_limit),
        _process_archive_outbox,
        _process_slack_outbox,
        _process_maya_outbox,
        _process_github_outbox,
    )
```

- [ ] **Step 6: Manual smoke test (no automated test for a `while True` loop — verify by direct call)**

Run: `cd /Volumes/2TB_SSD/GitHub/penny && venv/bin/python -c "from watcher import _process_github_outbox; _process_github_outbox()"`
Expected: runs without raising (an empty outbox is a valid, silent no-op)

```bash
git add watcher.py
git commit -m "feat: drain github_delivery outbox in the watcher ingest pass"
```

- [ ] **Step 7: Write the failing test for Doctor's local-only readiness probe**

Add to `tests/test_doctor.py` (match its existing probe-test pattern — look at how `_default_probe_slack` or `_default_probe_maya` are tested):

```python
def test_github_triage_probe_ready_when_gh_binary_and_token_present(self):
    with (
        patch("doctor.shutil.which", return_value="/opt/homebrew/bin/gh"),
        patch("doctor.subprocess.run") as run,
        patch("doctor._launchd_environment_keys", return_value=set()),
    ):
        run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="token123\n", stderr="")
        data = _default_probe_github_triage()
    self.assertTrue(data.get("gh_binary_present"))
    self.assertTrue(data.get("gh_auth_token_present"))

def test_github_triage_probe_does_not_hit_network(self):
    # gh auth token (local keychain/hosts-file read) must be used, never
    # gh auth status (which calls api.github.com) — Doctor is a metadata
    # boundary that never contacts a provider.
    with (
        patch("doctor.shutil.which", return_value="/opt/homebrew/bin/gh"),
        patch("doctor.subprocess.run") as run,
        patch("doctor._launchd_environment_keys", return_value=set()),
    ):
        run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="token123\n", stderr="")
        _default_probe_github_triage()
    command = run.call_args.args[0]
    self.assertIn("auth", command)
    self.assertIn("token", command)
    self.assertNotIn("status", command)

def test_github_triage_probe_degraded_when_gh_binary_missing(self):
    with patch("doctor.shutil.which", return_value=None):
        data = _default_probe_github_triage()
    self.assertFalse(data.get("gh_binary_present"))
```

- [ ] **Step 8: Run tests to verify they fail**

Run: `cd /Volumes/2TB_SSD/GitHub/penny && venv/bin/python -m pytest tests/test_doctor.py -k github_triage -v`
Expected: FAIL — `_default_probe_github_triage` does not exist

- [ ] **Step 9: Implement the probe and register it as optional**

Add near `_default_probe_slack` in `doctor.py`:

```python
def _default_probe_github_triage(_config: Any = None, *, now: datetime | None = None, **_kwargs: Any) -> dict[str, Any]:
    """Local-only readiness check: gh binary present, auth token reachable
    from local keychain/hosts (no network call — Doctor never contacts a
    provider), and com.penny.watcher's launchd environment carries whatever
    credential gh needs.
    """
    gh_path = shutil.which("gh")
    if gh_path is None:
        return {"gh_binary_present": False, "gh_auth_token_present": False}
    try:
        result = subprocess.run(
            ["gh", "auth", "token", "-h", "github.com"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {"gh_binary_present": True, "gh_auth_token_present": False}
    token_present = result.returncode == 0 and bool(result.stdout.strip())
    launchd_keys = _launchd_environment_keys("com.penny.watcher", ("GH_TOKEN",))
    return {
        "gh_binary_present": True,
        "gh_auth_token_present": token_present,
        "launchd_gh_token_configured": "GH_TOKEN" in launchd_keys,
    }
```

Add its status inference. Find `_infer_status`'s existing per-component branches (it dispatches on `name`) and add a `github_triage` branch modeled on `_default_probe_slack`'s — `ready` when `gh_binary_present` and `gh_auth_token_present`, else `degraded`.

Register it in the `probe_functions` dict (alongside `"slack": _default_probe_slack`):

```python
        "github_triage": _default_probe_github_triage,
```

Add `"github_triage"` to `_PROBE_NAMES`, and add it to `_OPTIONAL_COMPONENTS` (alongside `"maya"`) — this feature being unconfigured must not make all of Penny report `unready`:

```python
_OPTIONAL_COMPONENTS = frozenset({"maya", "github_triage"})
```

- [ ] **Step 10: Run tests to verify they pass, then commit**

Run: `cd /Volumes/2TB_SSD/GitHub/penny && venv/bin/python -m pytest tests/test_doctor.py -v`
Expected: PASS, no regressions

```bash
git add doctor.py tests/test_doctor.py
git commit -m "feat: add local-only github-triage readiness probe to Doctor"
```

- [ ] **Step 11: Add `GH_TOKEN` to the launchd plist template**

In `launchd/com.penny.watcher.plist.template`, inside `<dict>` under `EnvironmentVariables`, add (near the other credential placeholders like `PENNY_SLACK_BOT_TOKEN`):

```xml
        <!-- Required for github_delivery.py's janitor-triage subprocess to
             authenticate `gh api` calls. com.penny.watcher's PATH above
             does not include ~/.local/bin, so janitor-runner is invoked by
             absolute path — this token is what makes that subprocess's
             own `gh` calls authenticate once it runs. -->
        <key>GH_TOKEN</key>
        <string>YOUR_GH_TOKEN_HERE</string>
```

This is a template file (placeholder values, deployment injects real ones) — no test applies. Note in the commit message that live deployment still needs the real token injected via whatever mechanism populates the other `YOUR_..._HERE` placeholders in this template today (check `docs/macmini-deployment.md` for that mechanism before deploying — this plan only changes the template, not the deployment step).

```bash
git add launchd/com.penny.watcher.plist.template
git commit -m "docs: add GH_TOKEN placeholder to watcher launchd template"
```

---

## Self-review notes (for whoever executes this plan)

- Task 4's `core.py` hook targets `classify_and_route` (confirmed name/signature, confirmed `row_id` is guaranteed a valid positive int by the time the hook runs — `_require_effect_row` would already have raised `RoutingError` earlier in the same call otherwise) and `tests/test_core_and_classifier.py` (confirmed real file, confirmed `patch.object(core, ...)` mocking style from its existing `test_duplicate_classifier_items_have_one_effect`). This one was verified against the real file, not guessed.
- This plan depends on the sibling Janitor-repo plan (`docs/superpowers/plans/2026-09-17-janitor-triage-command.md`) for `janitor triage`'s actual behavior; Task 3's tests mock that boundary, so this plan can be implemented first, but end-to-end delivery needs both done.
