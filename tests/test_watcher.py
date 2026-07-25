from __future__ import annotations

import logging
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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

    def test_new_recording_routes_without_draining_slack_outbox(self) -> None:
        audio_path = Path(self.db_dir) / "new-recording.m4a"
        audio_path.write_bytes(b"audio")
        events: list[str] = []

        with (
            patch.object(watcher, "get_transcript_by_hash", return_value=None),
            patch.object(watcher, "transcribe", return_value="route this transcript"),
            patch.object(watcher, "insert_transcript", return_value=42),
            patch.object(
                watcher,
                "classify_and_route",
                side_effect=lambda *args, **kwargs: events.append("route"),
            ),
            patch.object(
                watcher,
                "update_transcript_stages",
                create=True,
            ) as stage_mock,
            patch.object(
                watcher,
                "_process_slack_outbox",
                side_effect=lambda: events.append("slack"),
            ) as slack_mock,
        ):
            processed = watcher._process_audio_file(
                audio_path,
                file_hash="new-recording-hash",
            )

        self.assertTrue(processed)
        self.assertEqual(events, ["route"])
        stage_mock.assert_not_called()
        slack_mock.assert_not_called()

    def test_empty_transcription_remains_failed_and_not_slack_eligible(self) -> None:
        audio_path = Path(self.db_dir) / "empty-transcription.m4a"
        audio_path.write_bytes(b"audio")

        with (
            patch.object(watcher, "transcribe", return_value="SE<|hr|><|hr|><|hr|>"),
            self.assertRaisesRegex(
                RuntimeError,
                "empty transcript after normalization",
            ),
        ):
            watcher._process_audio_file(
                audio_path,
                file_hash="empty-transcription-hash",
            )

        failed_row = transcript_log.get_transcript_by_hash(
            "empty-transcription-hash"
        )
        self.assertEqual(failed_row["status"], "failed")
        stored_row = transcript_log.get_transcript(failed_row["id"])
        self.assertEqual(stored_row["ingest_state"], "failed")
        self.assertEqual(
            len(
                transcript_log.get_pending_slack_deliveries(
                    transcript_id=failed_row["id"],
                )
            ),
            1,
        )
        self.assertEqual(
            transcript_log.get_pending_slack_deliveries(
                transcript_id=failed_row["id"],
                routed_only=True,
            ),
            [],
        )

    def test_retry_pending_routes_does_not_promote_state_after_core_returns(
        self,
    ) -> None:
        pending_row = {
            "id": 42,
            "source": "iCloud",
            "transcript": "route this transcript",
            "duration_seconds": None,
        }

        with (
            patch.object(watcher, "get_pending", return_value=[pending_row]),
            patch.object(watcher, "classify_and_route", return_value={"ok": True}),
            patch.object(
                watcher,
                "update_transcript_stages",
                create=True,
            ) as stage_mock,
            patch.object(watcher, "mark_voice_memo_routed_for_transcript"),
        ):
            watcher._retry_pending_routes(limit=1)

        stage_mock.assert_not_called()

    def test_ingest_pass_drains_one_slack_chunk_after_all_local_work(self) -> None:
        events: list[str] = []

        with (
            patch.object(watcher, "get_new_recordings", return_value=[{"Z_PK": 1}]),
            patch.object(
                watcher,
                "_process_db_batch",
                side_effect=lambda recordings: events.append("db"),
            ),
            patch.object(
                watcher,
                "_retry_waiting_for_files",
                side_effect=lambda limit: events.append("waiting"),
            ),
            patch.object(
                watcher,
                "_process_disk_backlog",
                side_effect=lambda limit: events.append("disk"),
            ),
            patch.object(
                watcher,
                "_retry_pending_routes",
                side_effect=lambda limit: events.append("routes"),
            ),
            patch.object(
                watcher,
                "_process_slack_outbox",
                side_effect=lambda: events.append("slack"),
            ) as slack_mock,
        ):
            watcher._process_ingest_pass()

        self.assertEqual(events, ["db", "waiting", "disk", "routes", "slack"])
        slack_mock.assert_called_once_with()

    def test_slack_outbox_helper_requests_one_delivery(self) -> None:
        with patch.object(watcher, "process_pending_slack", return_value=0) as process_mock:
            watcher._process_slack_outbox()

        process_mock.assert_called_once_with(limit=1)

    def test_voicememos_sync_is_refreshed_even_when_process_is_running(self) -> None:
        calls: list[list[str]] = []

        def fake_run(args, **kwargs):
            calls.append(args)
            if args[0] == "osascript":
                return SimpleNamespace(returncode=0, stdout="Voice Memos", stderr="")
            return SimpleNamespace(returncode=0, stdout="411\n", stderr="")

        with patch.object(watcher.subprocess, "run", side_effect=fake_run):
            watcher._voicememos_unresponsive_streak = 0
            watcher._ensure_voicememos_running()

        self.assertEqual(
            calls,
            [
                ["pgrep", "-x", "VoiceMemos"],
                ["osascript", "-e", watcher.VOICE_MEMOS_RESPONSIVENESS_SCRIPT],
                ["open", "-g", "-a", "VoiceMemos"],
            ],
        )

    def test_voicememos_unresponsive_is_relaunched_after_three_probes(self) -> None:
        calls: list[list[str]] = []

        def fake_run(args, **kwargs):
            calls.append(args)
            if args[0] == "osascript":
                return SimpleNamespace(returncode=1, stdout="", stderr="timed out")
            return SimpleNamespace(returncode=0, stdout="411\n", stderr="")

        with patch.object(watcher.subprocess, "run", side_effect=fake_run):
            watcher._voicememos_unresponsive_streak = 0
            watcher._ensure_voicememos_running()
            watcher._ensure_voicememos_running()
            watcher._ensure_voicememos_running()

        self.assertIn(["pkill", "-TERM", "-x", "VoiceMemos"], calls)
        self.assertEqual(calls[-1], ["open", "-g", "-a", "VoiceMemos"])

    def test_cloud_recording_snapshot_reports_database_and_wal(self) -> None:
        db_path = Path(self.db_dir) / "CloudRecordings.db"
        connection = sqlite3.connect(db_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "CREATE TABLE ZCLOUDRECORDING (Z_PK INTEGER, ZDATE REAL)"
        )
        connection.execute(
            "INSERT INTO ZCLOUDRECORDING VALUES (123, 800000000)"
        )
        connection.commit()

        with patch.object(watcher, "CLOUDRECORDINGS_DB", db_path):
            snapshot = watcher._cloud_recording_snapshot()

        connection.close()

        self.assertTrue(snapshot["db_ok"])
        self.assertEqual(snapshot["record_count"], 1)
        self.assertEqual(snapshot["latest_pk"], 123)
        self.assertTrue(snapshot["wal_exists"])

    def test_health_check_is_non_healthy_when_slack_health_query_fails(self) -> None:
        health_path = Path(self.db_dir) / "health.txt"
        with (
            patch.object(watcher, "HEALTH_FILE", health_path),
            patch.object(watcher, "_voicememos_running", return_value=True),
            patch.object(watcher, "_voicememos_responsive", return_value=True),
            patch.object(watcher, "_transcripts_pending", return_value=0),
            patch.object(
                watcher,
                "_cloud_recording_snapshot",
                return_value={
                    "db_ok": True,
                    "record_count": 12,
                    "latest_pk": 123,
                    "latest_date": None,
                    "wal_exists": True,
                    "wal_age_seconds": 3,
                },
            ),
            patch.object(
                watcher,
                "get_voice_memo_health",
                return_value={
                    "latest_recording_pk": 123,
                    "awaiting_file_count": 0,
                    "failed_count": 0,
                },
            ),
            patch.object(
                watcher,
                "get_slack_delivery_health",
                return_value={
                    "pending_count": 0,
                    "sent_count": 0,
                    "failed_count": 0,
                    "health_error": 1,
                },
            ),
        ):
            watcher.update_health_check()

        health = health_path.read_text(encoding="utf-8")
        self.assertIn("|watcher_ok:0|", health)
        self.assertIn("|slack_health_error:1", health)


if __name__ == "__main__":
    unittest.main()
