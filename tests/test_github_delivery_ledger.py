import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import github_delivery
import transcript_log as tl


class GithubDeliveryLedgerTestCase(unittest.TestCase):
    def setUp(self):
        self.db_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.db_dir, ignore_errors=True)
        self.db_path = Path(self.db_dir) / "test_transcripts.db"
        patch.object(tl, "TRANSCRIPT_DB_PATH", self.db_path).start()
        patch.object(
            tl, "LEGACY_VOICE_MEMO_CURSOR_PATH", Path(self.db_dir) / "legacy_last_pk.txt"
        ).start()
        tl.init_db()
        self.addCleanup(patch.stopall)
        conn = tl._get_conn()
        conn.execute(
            "INSERT INTO transcripts (content_hash, source, transcript, ingest_state, quality_status) "
            "VALUES ('github-ledger-test-hash', 'voice_memo', 'fix the widget sync bug', 'complete', 'passed')"
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

    def test_expired_lease_recovers_with_new_claim_token(self):
        tl.queue_github_delivery(self.transcript_id, "abc123")

        first = tl.claim_next_github_delivery("worker-a", lease_seconds=60)
        self.assertIsNotNone(first)
        self.assertEqual(first["transcript_row_id"], self.transcript_id)
        self.assertEqual(first["github_claim_owner"], "worker-a")
        self.assertIsNone(tl.claim_next_github_delivery("worker-b"))

        conn = tl._get_conn()
        try:
            conn.execute(
                "UPDATE github_deliveries "
                "SET github_claim_expires_at = datetime('now', '-1 second') "
                "WHERE id = ?",
                (first["id"],),
            )
            conn.commit()
        finally:
            conn.close()

        recovered = tl.claim_next_github_delivery("worker-b", lease_seconds=60)
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered["id"], first["id"])
        self.assertEqual(recovered["github_claim_owner"], "worker-b")
        self.assertNotEqual(recovered["github_claim_token"], first["github_claim_token"])

    def test_mark_functions_reject_claim_owner_mismatch(self):
        tl.queue_github_delivery(self.transcript_id, "abc123")
        claimed = tl.claim_next_github_delivery("worker-a")
        self.assertIsNotNone(claimed)

        with self.assertRaisesRegex(ValueError, "GitHub claim owner mismatch"):
            tl.mark_github_delivery_sent(
                int(claimed["id"]),
                "Khamel83/widget-tool",
                "https://github.com/Khamel83/widget-tool/issues/9",
                claim_token=claimed["github_claim_token"],
                claim_owner="worker-b",
            )
        with self.assertRaisesRegex(ValueError, "GitHub claim owner mismatch"):
            tl.mark_github_delivery_no_match(
                int(claimed["id"]),
                claim_token=claimed["github_claim_token"],
                claim_owner="worker-b",
            )
        with self.assertRaisesRegex(ValueError, "GitHub claim owner mismatch"):
            tl.mark_github_delivery_failed(
                int(claimed["id"]),
                "boom",
                claim_token=claimed["github_claim_token"],
                claim_owner="worker-b",
            )

        # The row is still claimed by worker-a and unaffected by the rejected calls.
        self.assertIsNone(tl.claim_next_github_delivery("worker-c"))


class GithubDeliveryDrainIntegrationTestCase(unittest.TestCase):
    """Cross-repo smoke test: the real ledger (queue/claim/mark) driven by the
    real drain loop, with only the `janitor triage` subprocess and the Slack
    post stubbed out.
    """

    setUp = GithubDeliveryLedgerTestCase.setUp

    def _row(self) -> dict:
        conn = tl._get_conn()
        try:
            row = conn.execute(
                "SELECT status, attempt_count, repo, issue_url, last_error, "
                "github_claim_token FROM github_deliveries WHERE transcript_row_id = ?",
                (self.transcript_id,),
            ).fetchone()
        finally:
            conn.close()
        return dict(row)

    def test_queued_delivery_drains_to_sent_with_persisted_repo_and_issue_url(self):
        tl.queue_github_delivery(self.transcript_id, "penny-row-int-1")

        with (
            patch.object(
                github_delivery,
                "_run_janitor_triage",
                return_value={
                    "status": "filed",
                    "repo": "Khamel83/widget-tool",
                    "issue_url": "https://github.com/Khamel83/widget-tool/issues/9",
                },
            ) as triage,
            patch.object(github_delivery, "_reply_in_slack_thread") as reply,
        ):
            processed = github_delivery.process_pending_github_deliveries(limit=5)

        self.assertEqual(processed, 1)
        triage.assert_called_once()
        # The drain passes the persisted transcript text and idempotency key
        # through to the triage CLI.
        self.assertEqual(triage.call_args.args[0], "fix the widget sync bug")
        self.assertEqual(triage.call_args.args[1], "penny-row-int-1")
        reply.assert_called_once()

        row = self._row()
        self.assertEqual(row["status"], "sent")
        self.assertEqual(row["repo"], "Khamel83/widget-tool")
        self.assertEqual(row["issue_url"], "https://github.com/Khamel83/widget-tool/issues/9")
        # Terminal: nothing left to claim.
        self.assertIsNone(tl.claim_next_github_delivery("worker-after"))

    def test_malformed_filed_response_retries_instead_of_wedging_the_stream(self):
        """Regression: a `{"status": "filed"}` with no repo/issue_url used to
        raise KeyError inside the drain loop BEFORE any mark_* call, leaving
        the row at status='delivering' with attempt_count=0 — reclaimed first
        on every later pass (oldest-first) and starving the whole stream."""
        tl.queue_github_delivery(self.transcript_id, "penny-row-int-2")

        # Drive the real _run_janitor_triage validation by stubbing only the
        # subprocess, so the malformed CLI response is handled end to end.
        import subprocess as _subprocess

        completed = _subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"status": "filed"}', stderr="",
        )
        with (
            patch.object(github_delivery.subprocess, "run", return_value=completed),
            patch.object(github_delivery, "_reply_in_slack_thread") as reply,
        ):
            processed = github_delivery.process_pending_github_deliveries(limit=5)

        # It is a retryable failure, not a terminal delivery and not a crash.
        self.assertEqual(processed, 1)
        reply.assert_not_called()

        row = self._row()
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["attempt_count"], 1)
        self.assertIsNone(row["github_claim_token"])
        # last_error is redacted to the ledger's allowlisted vocabulary, but a
        # failure must be recorded (the wedge left no trace at all).
        self.assertTrue(row["last_error"])
        self.assertIsNone(row["repo"])
        self.assertIsNone(row["issue_url"])

    def test_repeated_malformed_filed_responses_dead_letter_and_never_wedge(self):
        tl.queue_github_delivery(self.transcript_id, "penny-row-int-3")
        import subprocess as _subprocess

        completed = _subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"status": "filed", "repo": "Khamel83/x"}', stderr="",
        )
        for attempt in range(1, tl.GITHUB_MAX_ATTEMPTS + 1):
            with (
                patch.object(github_delivery.subprocess, "run", return_value=completed),
                patch.object(github_delivery, "_reply_in_slack_thread"),
                # retry_after_seconds is clamped at 0 minimum; make the row
                # immediately due again so the loop can observe every attempt.
                patch.object(
                    github_delivery, "mark_github_delivery_failed",
                    side_effect=lambda delivery_id, reason, retry_after_seconds=60, **kw:
                        tl.mark_github_delivery_failed(
                            delivery_id, reason, retry_after_seconds=0, **kw
                        ),
                ),
            ):
                github_delivery.process_pending_github_deliveries(limit=1)
            row = self._row()
            self.assertEqual(row["attempt_count"], attempt)
            self.assertNotEqual(row["status"], "delivering")

        self.assertEqual(self._row()["status"], "failed")
        self.assertIsNone(tl.claim_next_github_delivery("worker-after"))
