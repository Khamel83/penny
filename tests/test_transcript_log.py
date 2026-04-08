from __future__ import annotations

import importlib
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Keep any test-created runtime files inside /tmp (sandbox-writable).
os.environ["HOME"] = "/tmp/penny_test_home"
os.environ["OPENROUTER_API_KEY"] = "test-key"
os.environ["TELEGRAM_BOT_TOKEN"] = "test-bot"
os.environ["TELEGRAM_CHAT_ID"] = "12345"
os.environ["GOOGLE_CREDENTIALS_FILE"] = "/tmp/penny_test_home/.penny/google_credentials.json"
os.environ["GOOGLE_TOKEN_FILE"] = "/tmp/penny_test_home/.penny/google_token.json"
logging.disable(logging.CRITICAL)

import transcript_log  # noqa: E402


class TranscriptLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_dir = tempfile.mkdtemp()
        self.db_path = Path(self.db_dir) / "test_transcripts.db"
        patch.object(
            transcript_log, "TRANSCRIPT_DB_PATH", self.db_path
        ).start()
        transcript_log.init_db()
        self.addCleanup(patch.stopall)

    def test_insert_and_retrieve(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="abc123",
            source="iCloud",
            transcript="buy milk",
        )
        self.assertIsNotNone(row_id)
        self.assertTrue(transcript_log.is_already_logged("abc123"))

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


if __name__ == "__main__":
    unittest.main()
