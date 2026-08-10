from __future__ import annotations

import logging
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
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
from archive import StagedAudio  # noqa: E402
from transcript_log import InsertOutcome, TranscriptInsertResult  # noqa: E402
from transcript_quality import QualityResult, TranscriptionResult  # noqa: E402


def _inserted(row_id: int) -> TranscriptInsertResult:
    return TranscriptInsertResult(InsertOutcome.INSERTED, row_id=row_id)


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
            patch.object(
                watcher, "insert_transcript_result", return_value=_inserted(99)
            ) as insert_mock,
            patch.object(watcher, "link_voice_memo_transcript", return_value=True),
            patch.object(watcher, "mark_voice_memo_terminal") as terminal_mock,
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
        terminal_mock.assert_called_once_with(123, "skipped_too_large")

    def test_stages_before_transcription_and_queues_after_canonical_insert(self) -> None:
        audio_path = Path(self.db_dir) / "ordered.m4a"
        audio_path.write_bytes(b"audio")
        staged = StagedAudio(audio_path, "a" * 64, 5, ".m4a")
        events: list[str] = []
        with (
            patch.object(watcher, "stage_audio", side_effect=lambda *a: (events.append("stage"), staged)[1]),
            patch.object(watcher, "transcribe_with_quality", side_effect=lambda *a, **k: (events.append("transcribe"), TranscriptionResult("text", QualityResult(True), 1))[1]),
            patch.object(watcher, "insert_transcript_result", side_effect=lambda **k: (events.append("insert"), _inserted(42))[1]) as insert,
            patch.object(watcher, "queue_archive_delivery"),
            patch.object(watcher, "classify_and_route"),
        ):
            self.assertTrue(watcher._process_audio_file(audio_path, file_hash="legacy-md5"))
        self.assertEqual(events, ["stage", "transcribe", "insert"])
        self.assertIs(insert.call_args.kwargs["archive_staged"], staged)

    def test_persistence_failure_never_queues_archive(self) -> None:
        audio_path = Path(self.db_dir) / "failed.m4a"
        audio_path.write_bytes(b"audio")
        staged = StagedAudio(audio_path, "b" * 64, 5, ".m4a")
        with (
            patch.object(watcher, "stage_audio", return_value=staged),
            patch.object(watcher, "transcribe_with_quality", return_value=TranscriptionResult("text", QualityResult(True), 1)),
            patch.object(watcher, "insert_transcript_result", return_value=TranscriptInsertResult(InsertOutcome.FAILED, error_code="database_unavailable")),
            patch.object(watcher, "queue_archive_delivery") as queue,
        ):
            self.assertFalse(watcher._process_audio_file(audio_path, file_hash="legacy-md5"))
        queue.assert_not_called()

    def test_quality_oversize_and_existing_rows_queue_archive(self) -> None:
        cases = [
            ("quality", 50, {"id": 50, "quality_status": "needs_review", "status": "pending", "transcript": "review", "source": "iCloud"}),
            ("oversize", 51, {"id": 51, "quality_status": "passed", "status": "pending", "transcript": "(skipped: file too large)", "source": "iCloud"}),
            ("existing", 52, {"id": 52, "quality_status": "passed", "status": "routed", "transcript": "done", "source": "iCloud"}),
        ]
        for name, row_id, canonical in cases:
            with self.subTest(name=name):
                audio_path = Path(self.db_dir) / f"{name}.m4a"
                audio_path.write_bytes(b"audio")
                staged = StagedAudio(audio_path, str(row_id) * 32, 5, ".m4a")
                with (
                    patch.object(watcher, "stage_audio", return_value=staged),
                    patch.object(watcher, "queue_archive_delivery") as queue,
                    patch.object(watcher, "get_transcript_by_hash", return_value=canonical if name == "existing" else None),
                    patch.object(watcher, "transcribe_with_quality", return_value=TranscriptionResult("review", QualityResult(False, "needs_review"), 1)),
                    patch.object(watcher, "insert_transcript_result", return_value=_inserted(row_id)) as insert,
                    patch.object(watcher, "MAX_FILE_SIZE", 0 if name == "oversize" else watcher.MAX_FILE_SIZE),
                ):
                    self.assertTrue(watcher._process_audio_file(audio_path, file_hash=f"hash-{name}"))
                if name == "existing":
                    queue.assert_called_once()
                    self.assertIsNone(queue.call_args.args[2]["backend"])
                elif name == "oversize":
                    self.assertIsNone(
                        insert.call_args.kwargs[
                            "archive_metadata"
                        ]["backend"]
                    )

    def test_valid_legacy_md5_must_match_staged_object_before_transcription(self) -> None:
        audio_path = Path(self.db_dir) / "changed.m4a"
        audio_path.write_bytes(b"new bytes")
        staged = StagedAudio(audio_path, "c" * 64, len(b"new bytes"), ".m4a")
        with (
            patch.object(watcher, "stage_audio", return_value=staged),
            patch.object(watcher, "transcribe_with_quality") as transcribe,
        ):
            with self.assertRaises(watcher.SourceChangedError):
                watcher._process_audio_file(
                    audio_path, file_hash="00000000000000000000000000000000"
                )
        transcribe.assert_not_called()

    def test_archive_outbox_drains_independently_when_routing_outboxes_fail(self) -> None:
        with (
            patch.object(watcher, "_process_db_batch", side_effect=RuntimeError("source down")),
            patch.object(watcher, "_process_archive_outbox") as archive_outbox,
            patch.object(watcher, "_process_slack_outbox"),
            patch.object(watcher, "_process_maya_outbox"),
        ):
            watcher._process_ingest_pass()
        archive_outbox.assert_called_once()

    def test_archive_outbox_persists_local_trio_receipt(self) -> None:
        receipt = SimpleNamespace(
            audio_path=Path("/mirror/a.m4a"),
            markdown_path=Path("/mirror/a.md"),
            manifest_path=Path("/mirror/a.json"),
            receipt_sha256="manifest-hash",
        )
        with (
            patch.object(watcher, "get_pending_archive_deliveries", return_value=[{"id": 17}]),
            patch.object(watcher, "process_archive_delivery", return_value=receipt),
            patch.object(watcher, "mark_archive_delivery_published") as published,
        ):
            watcher._process_archive_outbox()
        published.assert_called_once_with(
            17,
            audio_path="/mirror/a.m4a",
            markdown_path="/mirror/a.md",
            manifest_path="/mirror/a.json",
            receipt_sha256="manifest-hash",
        )

    def test_disk_scan_reconciles_canonical_row_missing_archive_delivery(self) -> None:
        memo_dir = Path(self.db_dir) / "memos"
        memo_dir.mkdir()
        memo = memo_dir / "existing.m4a"
        memo.write_bytes(b"audio")
        with (
            patch.object(watcher, "VOICE_MEMOS_DIR", memo_dir),
            patch.object(watcher, "get_file_hash", return_value="existing-hash"),
            patch.object(watcher, "is_already_logged", return_value=True),
            patch.object(watcher, "needs_archive_delivery", return_value=True),
        ):
            self.assertEqual(watcher.scan_for_unprocessed_files(), [(memo, "existing-hash")])

    def test_watcher_does_not_mark_source_routed_after_insert_failure(self) -> None:
        audio_path = Path(self.db_dir) / "persistence-failure.m4a"
        audio_path.write_bytes(b"audio")
        failed = TranscriptInsertResult(
            InsertOutcome.FAILED, error_code="database_unavailable"
        )

        with (
            patch.object(
                watcher,
                "transcribe_with_quality",
                return_value=TranscriptionResult("retry me", QualityResult(True), 1),
            ),
            patch.object(
                watcher,
                "insert_transcript_result",
                return_value=failed,
            ),
            patch.object(watcher, "mark_voice_memo_routed") as routed,
        ):
            self.assertFalse(
                watcher._process_audio_file(
                    audio_path,
                    file_hash="persistence-failure-hash",
                    recording_pk=44,
                )
            )

        routed.assert_not_called()

    def test_failed_transcription_schedules_safe_retry_for_unlinked_source(self) -> None:
        audio_path = Path(self.db_dir) / "failing.m4a"
        audio_path.write_bytes(b"audio")
        with (
            patch.object(watcher, "_find_audio_path_for_recording", return_value=audio_path),
            patch.object(
                watcher,
                "transcribe_with_quality",
                side_effect=RuntimeError("memo text must not enter retry state"),
            ),
        ):
            self.assertFalse(watcher.process_recording({"Z_PK": 45}))

        conn = transcript_log._get_conn()
        try:
            row = conn.execute(
                "SELECT retryable, error_message FROM voice_memo_ingest "
                "WHERE recording_pk = 45"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["retryable"], 1)
        self.assertEqual(row["error_message"], "processing_error")

    def test_failed_upsert_does_not_advance_discovery_cursor(self) -> None:
        state_file = Path(self.db_dir) / "last_pk.txt"
        with (
            patch.object(watcher, "STATE_FILE", state_file),
            patch.object(watcher, "get_source_watermark", return_value=0),
            patch.object(watcher, "upsert_voice_memo_recording", return_value=False),
            patch.object(watcher, "process_recording") as process_recording,
            patch.object(watcher, "advance_source_watermark") as advance,
        ):
            watcher._process_db_batch([{"Z_PK": 501}])

        self.assertLess(watcher.get_last_seen_pk(), 501)
        process_recording.assert_not_called()
        advance.assert_not_called()

    def test_discovery_advances_after_durable_upserts_despite_processing_failure(self) -> None:
        state_file = Path(self.db_dir) / "last_pk.txt"
        recordings = [{"Z_PK": 501}, {"Z_PK": 503}]
        with (
            patch.object(watcher, "STATE_FILE", state_file),
            patch.object(watcher, "get_source_watermark", return_value=500),
            patch.object(watcher, "upsert_voice_memo_recording", return_value=True),
            patch.object(watcher, "process_recording", return_value=False),
            patch.object(watcher, "advance_source_watermark", return_value=True) as advance,
        ):
            watcher._process_db_batch(recordings)

        advance.assert_called_once_with("voice_memos", 503)
        self.assertEqual(state_file.read_text(encoding="utf-8"), "503")

    def test_batch_does_not_repeat_a_durable_upsert_before_processing(self) -> None:
        state_file = Path(self.db_dir) / "last_pk.txt"
        recording = {"Z_PK": 504}
        with (
            patch.object(watcher, "STATE_FILE", state_file),
            patch.object(watcher, "get_source_watermark", return_value=503),
            patch.object(watcher, "upsert_voice_memo_recording", return_value=True) as upsert,
            patch.object(watcher, "process_recording", return_value=False) as process,
            patch.object(watcher, "advance_source_watermark", return_value=True),
        ):
            watcher._process_db_batch([recording])

        upsert.assert_called_once()
        process.assert_called_once_with(recording, already_upserted=True)

    def test_link_failure_does_not_report_existing_canonical_row_as_processed(self) -> None:
        audio_path = Path(self.db_dir) / "canonical.m4a"
        audio_path.write_bytes(b"audio")
        canonical = {
            "id": 91,
            "status": "routed",
            "quality_status": "passed",
            "transcript": "canonical",
            "source": "iCloud",
        }
        with (
            patch.object(watcher, "_find_audio_path_for_recording", return_value=audio_path),
            patch.object(watcher, "get_file_hash", return_value="canonical-hash"),
            patch.object(watcher, "get_transcript_by_hash", return_value=canonical),
            patch.object(watcher, "link_voice_memo_transcript", return_value=False),
            patch.object(watcher, "mark_voice_memo_terminal") as terminal,
        ):
            self.assertFalse(watcher.process_recording({"Z_PK": 46}))

        terminal.assert_not_called()
        conn = transcript_log._get_conn()
        try:
            row = conn.execute(
                "SELECT retryable FROM voice_memo_ingest WHERE recording_pk = 46"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["retryable"], 1)

    def test_existing_pending_row_resumes_routing_without_transcribing(self) -> None:
        audio_path = Path(self.db_dir) / "existing-pending.m4a"
        audio_path.write_bytes(b"audio")
        canonical = {
            "id": 88,
            "status": "pending",
            "quality_status": "passed",
            "transcript": "route canonical transcript",
            "source": "iCloud",
        }

        with (
            patch.object(watcher, "get_transcript_by_hash", return_value=canonical),
            patch.object(watcher, "link_voice_memo_transcript", return_value=True),
            patch.object(watcher, "transcribe_with_quality") as transcribe,
            patch.object(watcher, "classify_and_route") as route,
            patch.object(watcher, "mark_voice_memo_routed") as routed,
        ):
            self.assertTrue(
                watcher._process_audio_file(
                    audio_path,
                    file_hash="existing-pending-hash",
                    recording_pk=88,
                )
            )

        transcribe.assert_not_called()
        route.assert_called_once_with(
            "route canonical transcript",
            source="iCloud",
            row_id=88,
            duration_seconds=None,
            allow_maya=False,
        )
        routed.assert_called_once_with(88)

    def test_existing_routed_row_skips_routing(self) -> None:
        audio_path = Path(self.db_dir) / "existing-routed.m4a"
        audio_path.write_bytes(b"audio")
        canonical = {
            "id": 89,
            "status": "routed",
            "quality_status": "passed",
            "transcript": "already routed",
            "source": "iCloud",
        }

        with (
            patch.object(watcher, "get_transcript_by_hash", return_value=canonical),
            patch.object(watcher, "link_voice_memo_transcript", return_value=True),
            patch.object(watcher, "transcribe_with_quality") as transcribe,
            patch.object(watcher, "classify_and_route") as route,
        ):
            self.assertTrue(
                watcher._process_audio_file(
                    audio_path,
                    file_hash="existing-routed-hash",
                    recording_pk=89,
                )
            )

        transcribe.assert_not_called()
        route.assert_not_called()

    def test_insert_race_processed_duplicate_skips_routing(self) -> None:
        audio_path = Path(self.db_dir) / "race-processed.m4a"
        audio_path.write_bytes(b"audio")
        canonical = {
            "id": 90,
            "status": "processed",
            "quality_status": "passed",
            "transcript": "already processed",
            "source": "iCloud",
        }

        with (
            patch.object(
                watcher, "get_transcript_by_hash", side_effect=[None, canonical]
            ),
            patch.object(
                watcher,
                "transcribe_with_quality",
                return_value=TranscriptionResult("fresh transcript", QualityResult(True), 1),
            ),
            patch.object(
                watcher,
                "insert_transcript_result",
                return_value=TranscriptInsertResult(
                    InsertOutcome.DUPLICATE, row_id=90, existing_status="processed"
                ),
            ),
            patch.object(watcher, "classify_and_route") as route,
        ):
            self.assertTrue(
                watcher._process_audio_file(
                    audio_path,
                    file_hash="race-processed-hash",
                )
            )

        route.assert_not_called()

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
            patch.object(
                watcher, "insert_transcript_result", return_value=_inserted(42)
            ),
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
                    (
                        "attempt_1=consecutive_token_repetition;"
                        "attempt_2=low_diversity_suffix"
                    ),
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
            stored_row["quality_detail"],
            (
                "attempt_1=consecutive_token_repetition;"
                "attempt_2=low_diversity_suffix"
            ),
        )
        self.assertEqual(
            transcript_log.get_pending_slack_deliveries(
                transcript_id=review_row["id"],
            ),
            [],
        )
        operational = transcript_log.get_pending_quality_failure_deliveries()
        self.assertEqual(len(operational), 1)
        self.assertNotIn(stored_row["transcript"], operational[0]["message_text"])

    def test_backlogged_recording_uses_zdate_as_maya_capture_time(self) -> None:
        audio_path = Path(self.db_dir) / "backlogged-recording.m4a"
        audio_path.write_bytes(b"audio")
        recorded_at = datetime(2026, 7, 20, 12, 34, 56, tzinfo=timezone.utc)
        reference_date = datetime(2001, 1, 1, tzinfo=timezone.utc)
        zdate = (recorded_at - reference_date).total_seconds()

        with (
            patch.object(
                watcher,
                "_find_audio_path_for_recording",
                return_value=audio_path,
            ),
            patch.object(
                watcher,
                "get_file_hash",
                return_value="backlogged-recording-hash",
            ),
            patch.object(
                watcher,
                "transcribe_with_quality",
                return_value=TranscriptionResult(
                    "This memo was recorded eight days before processing.",
                    QualityResult(True),
                    1,
                ),
            ),
            patch.object(watcher, "classify_and_route"),
        ):
            processed = watcher.process_recording(
                {
                    "Z_PK": 501,
                    "ZCUSTOMLABEL": "Backlogged memo",
                    "ZDATE": zdate,
                    "ZDURATION": 12.5,
                    "ZPATH": "backlogged-recording.m4a",
                }
            )

        self.assertTrue(processed)
        row = transcript_log.get_transcript_by_hash("backlogged-recording-hash")
        self.assertEqual(row["recorded_at"], "2026-07-20T12:34:56Z")
        self.assertEqual(row["maya_delivery_eligible"], 1)
        self.assertNotEqual(row["recorded_at"], row["file_seen_at"])
        envelope = transcript_log.build_maya_v2_envelope(int(row["id"]))
        self.assertEqual(envelope["captured_at"], "2026-07-20T12:34:56Z")
        conn = transcript_log._get_conn()
        try:
            ledger = conn.execute(
                """
                SELECT recorded_at
                FROM voice_memo_ingest
                WHERE recording_pk = 501
                """
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(ledger["recorded_at"], "2026-07-20T12:34:56Z")

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

    def test_retry_pending_routes_redacts_exception_text(self) -> None:
        sentinel = "pending-transcript-text-must-not-be-logged"
        pending_row = {
            "id": 47,
            "source": "iCloud",
            "transcript": "route this",
            "duration_seconds": None,
        }
        with (
            patch.object(watcher, "get_pending", return_value=[pending_row]),
            patch.object(
                watcher,
                "classify_and_route",
                side_effect=RuntimeError(sentinel),
            ),
            patch.object(watcher.log, "error") as error_log,
        ):
            watcher._retry_pending_routes(limit=1)

        self.assertNotIn(sentinel, str(error_log.call_args))
        self.assertIn("RuntimeError", str(error_log.call_args))

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

    def test_ingest_pass_gives_slack_an_opportunity_before_maya(self) -> None:
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
                "_retry_voice_memo_recordings",
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

        self.assertEqual(events, ["db", "waiting", "disk", "routes", "slack", "maya"])
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

    def test_each_ingest_pass_reaches_slack_before_a_maya_outage(self) -> None:
        events: list[str] = []

        with (
            patch.object(watcher, "get_new_recordings", return_value=[]),
            patch.object(watcher, "_process_db_batch"),
            patch.object(watcher, "_retry_waiting_for_files"),
            patch.object(watcher, "_process_disk_backlog"),
            patch.object(watcher, "_retry_pending_routes"),
            patch.object(
                watcher,
                "_process_slack_outbox",
                side_effect=lambda: events.append("slack"),
            ),
            patch.object(
                watcher,
                "_process_maya_outbox",
                side_effect=lambda: events.append("maya-timeout"),
            ),
        ):
            watcher._process_ingest_pass()
            watcher._process_ingest_pass()

        self.assertEqual(
            events,
            ["slack", "maya-timeout", "slack", "maya-timeout"],
        )

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

    def test_health_check_reports_bounded_maya_and_quality_state_without_secrets(
        self,
    ) -> None:
        health_path = Path(self.db_dir) / "health.txt"
        secret = "maya-secret-value-that-must-not-appear"
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
                    "retry_due_count": 3,
                    "terminal_count": 2,
                    "terminal_failure_count": 0,
                    "max_attempt_count": 0,
                    "source_watermark": 123,
                },
            ),
            patch.object(
                watcher,
                "get_slack_delivery_health",
                return_value={
                    "pending_count": 0,
                    "sent_count": 1,
                    "failed_count": 0,
                    "quality_failure_pending_count": 1,
                    "quality_failure_failed_count": 0,
                    "health_error": 0,
                },
            ),
            patch.object(
                watcher,
                "get_maya_delivery_health",
                return_value={
                    "pending_count": 3,
                    "due_count": 2,
                    "failed_count": 0,
                    "oldest_due_age_seconds": 91,
                    "quality_needs_review_count": 4,
                    "health_error": 0,
                },
                create=True,
            ),
            patch.object(watcher.cfg.maya, "transcript_url", "http://maya/ingest"),
            patch.object(watcher.cfg.maya, "ingest_token", secret),
        ):
            watcher.update_health_check()

        health = health_path.read_text(encoding="utf-8")
        self.assertIn("|watcher_ok:1|", health)
        self.assertIn("|maya_configured:1|", health)
        self.assertIn("|maya_pending:3|maya_due:2|maya_failed:0|", health)
        self.assertIn("|maya_oldest_due_age_seconds:91|", health)
        self.assertIn("|maya_health_error:0|quality_needs_review:4", health)
        self.assertIn("|quality_failure_slack_pending:1|", health)
        self.assertIn("|quality_failure_slack_failed:0|", health)
        self.assertIn("|voice_memo_retry_due:3|voice_memo_terminal:2|", health)
        self.assertIn("|voice_memo_terminal_failures:0|", health)
        self.assertIn("|voice_memo_source_watermark:123|", health)
        self.assertNotIn(secret, health)

    def test_health_check_fails_for_terminal_voice_memo_failure(self) -> None:
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
                    "db_ok": True, "record_count": 1, "latest_pk": 1,
                    "latest_date": None, "wal_exists": False, "wal_age_seconds": -1,
                },
            ),
            patch.object(
                watcher,
                "get_voice_memo_health",
                return_value={
                    "latest_recording_pk": 1, "awaiting_file_count": 0,
                    "failed_count": 1, "retry_due_count": 0, "terminal_count": 3,
                    "terminal_failure_count": 1, "max_attempt_count": 1,
                    "source_watermark": 1,
                },
            ),
            patch.object(
                watcher,
                "get_slack_delivery_health",
                return_value={"pending_count": 0, "failed_count": 0, "health_error": 0},
            ),
            patch.object(
                watcher,
                "get_maya_delivery_health",
                return_value={
                    "pending_count": 0, "due_count": 0, "failed_count": 0,
                    "oldest_due_age_seconds": 0, "quality_needs_review_count": 0,
                    "health_error": 0,
                },
            ),
            patch.object(watcher.cfg.maya, "transcript_url", "http://maya/ingest"),
            patch.object(watcher.cfg.maya, "ingest_token", "test-token"),
        ):
            watcher.update_health_check()

        health = health_path.read_text(encoding="utf-8")
        self.assertIn("|watcher_ok:0|", health)
        self.assertIn("|voice_memo_terminal_failures:1|", health)

    def test_maya_query_failure_forces_watcher_unhealthy(self) -> None:
        health_path = Path(self.db_dir) / "health.txt"
        with (
            patch.object(watcher, "HEALTH_FILE", health_path),
            patch.object(watcher, "_voicememos_running", return_value=False),
            patch.object(watcher, "_transcripts_pending", return_value=0),
            patch.object(watcher, "_cloud_recording_snapshot", return_value={
                "db_ok": True,
                "record_count": 0,
                "latest_pk": 0,
                "latest_date": None,
                "wal_exists": False,
                "wal_age_seconds": -1,
            }),
            patch.object(watcher, "get_voice_memo_health", return_value={
                "latest_recording_pk": 0,
                "awaiting_file_count": 0,
                "failed_count": 0,
            }),
            patch.object(watcher, "get_slack_delivery_health", return_value={
                "pending_count": 0,
                "sent_count": 0,
                "failed_count": 0,
                "health_error": 0,
            }),
            patch.object(
                watcher,
                "get_maya_delivery_health",
                return_value={
                    "pending_count": 0,
                    "due_count": 0,
                    "failed_count": 0,
                    "oldest_due_age_seconds": 0,
                    "quality_needs_review_count": 0,
                    "health_error": 1,
                },
                create=True,
            ),
            patch.object(watcher.cfg.maya, "transcript_url", "http://maya/ingest"),
            patch.object(watcher.cfg.maya, "ingest_token", "configured"),
        ):
            watcher.update_health_check()

        health = health_path.read_text(encoding="utf-8")
        self.assertIn("|watcher_ok:0|", health)
        self.assertIn("|maya_health_error:1|", health)


if __name__ == "__main__":
    unittest.main()
