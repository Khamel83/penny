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
