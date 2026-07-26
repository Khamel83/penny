from __future__ import annotations

import importlib
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Keep any test-created runtime files inside /tmp (sandbox-writable).
os.environ["HOME"] = "/tmp/penny_test_home"
os.environ["OPENROUTER_API_KEY"] = "test-key"
os.environ["TELEGRAM_BOT_TOKEN"] = "test-bot"
os.environ["TELEGRAM_CHAT_ID"] = "12345"
os.environ["GOOGLE_CREDENTIALS_FILE"] = (
    "/tmp/penny_test_home/.penny/google_credentials.json"
)
os.environ["GOOGLE_TOKEN_FILE"] = "/tmp/penny_test_home/.penny/google_token.json"
logging.disable(logging.CRITICAL)

import transcript_log  # noqa: E402


class TranscriptLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_dir = tempfile.mkdtemp()
        self.db_path = Path(self.db_dir) / "test_transcripts.db"
        patch.object(transcript_log, "TRANSCRIPT_DB_PATH", self.db_path).start()
        transcript_log.init_db()
        self.addCleanup(patch.stopall)

    def test_insert_and_retrieve(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="abc123",
            source="iCloud",
            transcript="buy milk",
            duration_seconds=12.5,
            ingest_state="transcribed",
        )
        self.assertIsNotNone(row_id)
        self.assertTrue(transcript_log.is_already_logged("abc123"))
        row = transcript_log.get_transcript(row_id)
        self.assertEqual(row["duration_seconds"], 12.5)
        self.assertEqual(row["ingest_state"], "transcribed")

    def test_voice_memo_insert_queues_verbatim_slack_delivery(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="slack1",
            source="iCloud",
            transcript="First line\nSecond line exactly.",
        )
        replay_id = transcript_log.insert_transcript(
            content_hash="slack1",
            source="iCloud",
            transcript="First line\nSecond line exactly.",
        )

        pending = transcript_log.get_pending_slack_deliveries()

        self.assertIsNotNone(row_id)
        self.assertIsNone(replay_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["transcript_row_id"], row_id)
        self.assertEqual(pending[0]["message_text"], "First line\nSecond line exactly.")
        self.assertEqual(pending[0]["status"], "pending")

    def test_oversized_file_placeholder_does_not_queue_slack_delivery(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="oversized1",
            source="iCloud",
            transcript="(skipped: file too large)",
            ingest_state="skipped_too_large",
            enqueue_slack=False,
        )

        self.assertIsNotNone(row_id)
        self.assertEqual(
            transcript_log.get_transcript(row_id)["transcript"],
            "(skipped: file too large)",
        )
        self.assertEqual(
            transcript_log.get_pending_slack_deliveries(transcript_id=row_id),
            [],
        )

    def test_non_voice_sources_do_not_queue_slack_delivery(self) -> None:
        transcript_log.insert_transcript(
            content_hash="slack2",
            source="Google Tasks",
            transcript="buy milk",
            enqueue_slack=False,
        )

        self.assertEqual(transcript_log.get_pending_slack_deliveries(), [])

    def test_icloud_transcript_uses_default_slack_channel_without_telegram_dependency(
        self,
    ) -> None:
        os.environ.pop("PENNY_SLACK_CHANNEL_ID", None)
        row_id = transcript_log.insert_transcript(
            content_hash="slack-default-channel",
            source="iCloud",
            transcript="voice memo transcript",
        )

        pending = transcript_log.get_pending_slack_deliveries(transcript_id=row_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(
            pending[0]["channel_id"],
            transcript_log.DEFAULT_SLACK_CHANNEL_ID,
        )

    def test_queue_slack_delivery_is_idempotent_for_existing_transcript(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="slack-requeue",
            source="iCloud",
            transcript="retry only once",
        )

        transcript_log.queue_slack_delivery(row_id)
        transcript_log.queue_slack_delivery(row_id)

        pending = transcript_log.get_pending_slack_deliveries(transcript_id=row_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["transcript_row_id"], row_id)

    def test_mark_slack_delivery_sent_persists_provider_timestamp(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="provider-ts",
            source="iCloud",
            transcript="capture slack ts",
        )
        delivery_id = transcript_log.get_pending_slack_deliveries(transcript_id=row_id)[0][
            "id"
        ]

        transcript_log.mark_slack_delivery_sent(delivery_id, provider_ts="123.456")

        health = transcript_log.get_slack_delivery_health()
        self.assertEqual(health["pending_count"], 0)
        self.assertEqual(health["sent_count"], 1)
        self.assertEqual(health["failed_count"], 0)

        conn = transcript_log._get_conn()
        try:
            row = conn.execute(
                "SELECT status, provider_ts FROM slack_deliveries WHERE id = ?",
                (delivery_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(dict(row)["status"], "sent")
        self.assertEqual(dict(row)["provider_ts"], "123.456")

    def test_mark_slack_delivery_failed_schedules_retry_and_hides_until_due(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="retry-later",
            source="iCloud",
            transcript="back off",
        )
        delivery_id = transcript_log.get_pending_slack_deliveries(transcript_id=row_id)[0][
            "id"
        ]

        transcript_log.mark_slack_delivery_failed(
            delivery_id,
            "ratelimited",
            retry_after_seconds=120,
        )

        self.assertEqual(
            transcript_log.get_pending_slack_deliveries(transcript_id=row_id),
            [],
        )
        health = transcript_log.get_slack_delivery_health()
        self.assertEqual(health["pending_count"], 1)
        self.assertEqual(health["failed_count"], 0)

        conn = transcript_log._get_conn()
        try:
            row = conn.execute(
                "SELECT status, attempt_count, next_attempt_at, last_error "
                "FROM slack_deliveries WHERE id = ?",
                (delivery_id,),
            ).fetchone()
        finally:
            conn.close()
        stored = dict(row)
        self.assertEqual(stored["status"], "pending")
        self.assertEqual(stored["attempt_count"], 1)
        self.assertEqual(stored["last_error"], "ratelimited")
        self.assertIsNotNone(stored["next_attempt_at"])

    def test_terminal_failed_delivery_remains_visible_in_health(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="retry-terminal",
            source="iCloud",
            transcript="give up eventually",
        )
        delivery_id = transcript_log.get_pending_slack_deliveries(transcript_id=row_id)[0][
            "id"
        ]

        for _ in range(5):
            transcript_log.mark_slack_delivery_failed(
                delivery_id,
                "slack_api_error",
                retry_after_seconds=1,
            )
            conn = transcript_log._get_conn()
            try:
                conn.execute(
                    "UPDATE slack_deliveries SET next_attempt_at = datetime('now', '-1 second') "
                    "WHERE id = ?",
                    (delivery_id,),
                )
                conn.commit()
            finally:
                conn.close()

        pending = transcript_log.get_pending_slack_deliveries(transcript_id=row_id)
        self.assertEqual(pending, [])
        health = transcript_log.get_slack_delivery_health()
        self.assertEqual(health["pending_count"], 0)
        self.assertEqual(health["failed_count"], 1)

    def test_mark_slack_delivery_sent_raises_write_failure(self) -> None:
        conn = Mock()
        conn.execute.side_effect = OSError("database is locked")

        with patch.object(transcript_log, "_get_conn", return_value=conn):
            with self.assertRaisesRegex(OSError, "database is locked"):
                transcript_log.mark_slack_delivery_sent(1)

        conn.close.assert_called_once()

    def test_mark_slack_delivery_failed_raises_write_failure(self) -> None:
        conn = Mock()
        conn.execute.side_effect = OSError("database is locked")

        with patch.object(transcript_log, "_get_conn", return_value=conn):
            with self.assertRaisesRegex(OSError, "database is locked"):
                transcript_log.mark_slack_delivery_failed(1, "ratelimited")

        conn.close.assert_called_once()

    def test_slack_acknowledgement_helpers_do_not_log_exception_text(self) -> None:
        conn = Mock()
        secret = "xoxb-" + "private-test-value"
        conn.execute.side_effect = OSError("database included bearer " + secret)

        with (
            patch.object(transcript_log, "_get_conn", return_value=conn),
            patch.object(transcript_log.log, "error") as error_mock,
        ):
            with self.assertRaises(OSError):
                transcript_log.mark_slack_delivery_sent(1)

        message, *args = error_mock.call_args.args
        rendered_log = str(message) % tuple(args)
        if secret in rendered_log:
            self.fail("acknowledgement helper log contained sensitive material")

    def test_mark_slack_delivery_failed_rejects_untrusted_error_text(self) -> None:
        transcript_log.insert_transcript(
            content_hash="slack-error-boundary",
            source="iCloud",
            transcript="sanitize persistence boundary",
        )
        transcript_log.mark_slack_delivery_failed(
            1,
            "unexpectedsecretvalue",
        )

        conn = transcript_log._get_conn()
        try:
            row = conn.execute(
                "SELECT status, last_error FROM slack_deliveries WHERE id = 1"
            ).fetchone()
        finally:
            conn.close()
        stored = dict(row)
        if stored["last_error"] != "delivery_error":
            self.fail("delivery error persistence accepted untrusted text")
        self.assertEqual(stored["status"], "pending")

    def test_dedup_rejects_duplicate(self) -> None:
        rid1 = transcript_log.insert_transcript(
            content_hash="dup1", source="iCloud", transcript="first"
        )
        self.assertIsNotNone(rid1)
        rid2 = transcript_log.insert_transcript(
            content_hash="dup1", source="Shortcut", transcript="second"
        )
        self.assertIsNone(rid2)

    def test_is_already_logged_false_for_unknown(self) -> None:
        self.assertFalse(transcript_log.is_already_logged("nonexistent"))

    def test_get_transcript_by_hash(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="lookup1", source="iCloud", transcript="test"
        )
        row = transcript_log.get_transcript_by_hash("lookup1")
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], row_id)
        self.assertEqual(row["content_hash"], "lookup1")

    def test_mark_routed(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="route1", source="iCloud", transcript="test"
        )
        transcript_log.mark_routed(
            row_id, {"items": [{"item": "milk"}]}, "1 reminder(s)"
        )
        pending = transcript_log.get_pending()
        self.assertEqual(len(pending), 0)

    def test_mark_failed(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="fail1", source="iCloud", transcript="test"
        )
        transcript_log.mark_failed(row_id, "AppleScript failed")
        pending = transcript_log.get_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["id"], row_id)

    def test_update_transcript_progress(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="progress1", source="iCloud", transcript="test"
        )
        transcript_log.update_transcript_progress(row_id, {"note_created": True})
        row = transcript_log.get_transcript(row_id)
        self.assertIn("note_created", row["routing_progress"])

    def test_voice_memo_ingest_tracking(self) -> None:
        transcript_log.upsert_voice_memo_recording(
            101,
            label="memo",
            raw_path="memo.m4a",
            duration_seconds=42.0,
        )
        waiting = transcript_log.get_voice_memo_recordings_waiting_for_file()
        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0]["recording_pk"], 101)

        transcript_log.mark_voice_memo_waiting_for_file(101, "not yet")
        transcript_log.mark_voice_memo_file_seen(101, "/tmp/memo.m4a")
        waiting_after_file_seen = transcript_log.get_voice_memo_recordings_waiting_for_file()
        self.assertEqual(len(waiting_after_file_seen), 1)
        self.assertEqual(waiting_after_file_seen[0]["status"], "file_ready")

        row_id = transcript_log.insert_transcript("hash101", "iCloud", "memo text")
        transcript_log.link_voice_memo_transcript(
            101,
            transcript_row_id=row_id,
            content_hash="hash101",
            audio_path="/tmp/memo.m4a",
        )
        transcript_log.mark_voice_memo_routed_for_transcript(row_id)

        health = transcript_log.get_voice_memo_health()
        self.assertEqual(health["latest_recording_pk"], 101)
        self.assertEqual(health["awaiting_file_count"], 0)

    def test_get_pending_excludes_routed(self) -> None:
        transcript_log.insert_transcript("p1", "iCloud", "pending one")
        rid2 = transcript_log.insert_transcript("p2", "iCloud", "routed one")
        transcript_log.mark_routed(rid2, {}, "done")
        transcript_log.insert_transcript("p3", "iCloud", "pending two")

        pending = transcript_log.get_pending()
        hashes = [r["content_hash"] for r in pending]
        self.assertIn("p1", hashes)
        self.assertIn("p3", hashes)
        self.assertNotIn("p2", hashes)

    def test_migration_from_processed_file(self) -> None:
        # Create a fake processed.txt
        processed_dir = Path(self.db_dir) / ".penny"
        processed_dir.mkdir()
        processed_file = processed_dir / "processed.txt"
        processed_file.write_text("oldhash1\noldhash2\n\n")

        with patch.object(
            transcript_log,
            "_MIGRATION_SOURCES",
            [(processed_file, "iCloud")],
        ):
            conn = transcript_log._get_conn()
            migrated = transcript_log._migrate_processed_files(conn)
            conn.commit()
            conn.close()

        self.assertEqual(migrated, 2)
        self.assertTrue(transcript_log.is_already_logged("oldhash1"))
        self.assertTrue(transcript_log.is_already_logged("oldhash2"))

    def test_retry_picks_up_failed_transcripts(self) -> None:
        """Verify that get_pending returns failed transcripts for retry."""
        rid = transcript_log.insert_transcript("fail_hash", "iCloud", "test transcript")
        transcript_log.mark_failed(rid, "AppleScript error")
        pending = transcript_log.get_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["content_hash"], "fail_hash")

    def test_insert_returns_none_on_duplicate(self) -> None:
        transcript_log.insert_transcript("dup_x", "iCloud", "first")
        result = transcript_log.insert_transcript("dup_x", "Shortcut", "second")
        self.assertIsNone(result)

    def test_migration_counts_only_new_rows(self) -> None:
        """Migration count should reflect actual inserts, not attempts."""
        processed_dir = Path(self.db_dir) / ".penny"
        processed_dir.mkdir()
        processed_file = processed_dir / "processed.txt"
        processed_file.write_text("new1\nnew2\n")

        with patch.object(
            transcript_log,
            "_MIGRATION_SOURCES",
            [(processed_file, "iCloud")],
        ):
            conn = transcript_log._get_conn()
            migrated = transcript_log._migrate_processed_files(conn)
            conn.commit()
            conn.close()

        self.assertEqual(migrated, 2)

        # Re-run migration — duplicates should not be counted
        with patch.object(
            transcript_log,
            "_MIGRATION_SOURCES",
            [(processed_file, "iCloud")],
        ):
            conn = transcript_log._get_conn()
            migrated2 = transcript_log._migrate_processed_files(conn)
            conn.commit()
            conn.close()

        self.assertEqual(migrated2, 0)

    def test_is_already_logged_returns_false_on_db_error(self):
        """Document intentional behavior: DB errors return False (allows retry)."""
        with patch.object(transcript_log, "_get_conn", side_effect=Exception("DB locked")):
            self.assertFalse(transcript_log.is_already_logged("any_hash"))


if __name__ == "__main__":
    unittest.main()
