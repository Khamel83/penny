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
import core  # noqa: E402
import maya_delivery  # noqa: E402
from transcript_quality import QualityResult, TranscriptionResult  # noqa: E402


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
            patch.object(
                watcher,
                "transcribe_with_quality",
                return_value=TranscriptionResult(
                    "route this transcript", QualityResult(True), 1
                ),
            ),
            patch.object(watcher, "insert_transcript", return_value=42),
            patch.object(
                watcher,
                "classify_and_route",
                side_effect=lambda *args, **kwargs: events.append("route"),
            ) as route_mock,
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
        self.assertIs(route_mock.call_args.kwargs["allow_maya"], False)
        stage_mock.assert_not_called()
        slack_mock.assert_not_called()

    def test_low_quality_transcription_is_retained_for_review_without_routing(self) -> None:
        audio_path = Path(self.db_dir) / "low-quality-transcription.m4a"
        audio_path.write_bytes(b"audio")

        with (
            patch.object(
                watcher,
                "transcribe_with_quality",
                return_value=TranscriptionResult(
                    "A valid memo first. " + "Vous " * 20,
                    QualityResult(False, "needs_review"),
                    2,
                ),
            ),
            patch.object(watcher, "classify_and_route") as route_mock,
        ):
            processed = watcher._process_audio_file(
                audio_path,
                file_hash="low-quality-transcription-hash",
            )

        self.assertTrue(processed)
        route_mock.assert_not_called()
        review_row = transcript_log.get_transcript_by_hash(
            "low-quality-transcription-hash"
        )
        self.assertEqual(
            review_row["transcript"], "A valid memo first. " + "Vous " * 20
        )
        stored_row = transcript_log.get_transcript(review_row["id"])
        self.assertEqual(stored_row["ingest_state"], "needs_review")
        self.assertEqual(
            transcript_log.get_pending_slack_deliveries(
                transcript_id=review_row["id"],
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

    def test_retry_pending_routes_does_not_let_review_rows_consume_limit(self) -> None:
        transcript_log.insert_transcript(
            content_hash="quality-review-hash",
            source="iCloud",
            transcript="unreviewed transcript",
            ingest_state="needs_review",
            enqueue_slack=False,
        )
        eligible_id = transcript_log.insert_transcript(
            content_hash="eligible-route-hash",
            source="iCloud",
            transcript="route this eligible transcript",
            ingest_state="transcribed",
            enqueue_slack=False,
        )

        with (
            patch.object(watcher, "classify_and_route") as route_mock,
        ):
            watcher._retry_pending_routes(limit=1)

        route_mock.assert_called_once_with(
            "route this eligible transcript",
            source="iCloud",
            row_id=eligible_id,
            duration_seconds=None,
            allow_maya=False,
        )

    def test_maya_origin_retry_uses_persisted_source_and_never_reenters_maya(
        self,
    ) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="maya-origin-retry-hash",
            source="maya:icloud",
            transcript="Keep this Maya-originated retry local.",
            ingest_state="transcribed",
            quality_status="passed",
            enqueue_slack=False,
        )
        observed_kwargs: dict[str, object] = {}
        original_classify_and_route = watcher.classify_and_route

        def observe_route(*args, **kwargs):
            observed_kwargs.update(kwargs)
            return original_classify_and_route(*args, **kwargs)

        with (
            patch.object(
                watcher,
                "classify_and_route",
                side_effect=observe_route,
            ),
            patch.object(core.cfg.maya, "transcript_url", "http://maya.test/ingest/transcript"),
            patch.object(core.cfg.maya, "ingest_token", "test-token"),
            patch.object(core, "_route_to_maya") as legacy_maya,
            patch.object(core, "detect_content_type", return_value="long_note"),
            patch.object(core, "add_note", return_value=True) as add_note,
            patch.object(maya_delivery.cfg.maya, "transcript_url", "http://maya.test/ingest/transcript"),
            patch.object(maya_delivery.cfg.maya, "ingest_token", "test-token"),
            patch.object(maya_delivery.requests, "post") as v2_maya,
        ):
            watcher._retry_pending_routes(limit=1)
            delivered = maya_delivery.process_pending_maya_deliveries()

        self.assertEqual(observed_kwargs["source"], "maya:icloud")
        self.assertIs(observed_kwargs["allow_maya"], False)
        legacy_maya.assert_not_called()
        v2_maya.assert_not_called()
        self.assertEqual(delivered, 0)
        add_note.assert_called_once_with(
            "Keep this Maya-originated retry local.",
            folder_name="Penny",
            source="maya:icloud",
        )
        stored = transcript_log.get_transcript(int(row_id))
        self.assertEqual(stored["routed_to"], "note in Penny")

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
            patch.object(
                watcher,
                "_process_maya_outbox",
                side_effect=lambda: events.append("maya"),
                create=True,
            ) as maya_mock,
        ):
            watcher._process_ingest_pass()

        self.assertEqual(events, ["db", "waiting", "disk", "routes", "maya", "slack"])
        maya_mock.assert_called_once_with()
        slack_mock.assert_called_once_with()

    def test_slack_outbox_helper_requests_one_delivery(self) -> None:
        with patch.object(watcher, "process_pending_slack", return_value=0) as process_mock:
            watcher._process_slack_outbox()

        process_mock.assert_called_once_with(limit=1)

    def test_maya_outbox_helper_requests_one_delivery(self) -> None:
        with patch.object(
            watcher,
            "process_pending_maya_deliveries",
            return_value=0,
            create=True,
        ) as process_mock:
            watcher._process_maya_outbox()

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
