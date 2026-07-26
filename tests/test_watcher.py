from __future__ import annotations

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

os.environ.setdefault("HOME", "/tmp/penny_test_home")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot")
os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")
os.environ.setdefault(
    "GOOGLE_CREDENTIALS_FILE",
    "/tmp/penny_test_home/.penny/google_credentials.json",
)
os.environ.setdefault(
    "GOOGLE_TOKEN_FILE",
    "/tmp/penny_test_home/.penny/google_token.json",
)
logging.disable(logging.CRITICAL)

import transcript_log  # noqa: E402
import watcher  # noqa: E402


class WatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_dir = tempfile.mkdtemp()
        self.db_path = Path(self.db_dir) / "test_transcripts.db"
        patch.object(transcript_log, "TRANSCRIPT_DB_PATH", self.db_path).start()
        transcript_log.init_db()
        self.addCleanup(patch.stopall)

    def test_oversized_file_is_recorded_as_skipped_without_slack_enqueue(self) -> None:
        audio_path = Path(self.db_dir) / "oversized.m4a"
        audio_path.write_bytes(b"x")

        with (
            patch.object(watcher, "MAX_FILE_SIZE", 0),
            patch.object(watcher, "get_file_hash", return_value="oversized-hash"),
            patch.object(watcher, "insert_transcript", return_value=99) as insert_mock,
            patch.object(watcher, "mark_voice_memo_failed") as failed_mock,
        ):
            processed = watcher._process_audio_file(
                audio_path,
                duration_seconds=42.0,
                recording_pk=123,
            )

        self.assertTrue(processed)
        insert_mock.assert_called_once()
        self.assertEqual(
            insert_mock.call_args.kwargs["ingest_state"],
            "skipped_too_large",
        )
        self.assertFalse(insert_mock.call_args.kwargs["enqueue_slack"])
        failed_mock.assert_called_once_with(123, "file too large")


if __name__ == "__main__":
    unittest.main()
