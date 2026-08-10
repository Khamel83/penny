from __future__ import annotations

import logging
import json
import os
import sqlite3
import sys
import tempfile
import threading
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
from apple_effects import AppleEffectReceipt  # noqa: E402
import watcher  # noqa: E402
import core  # noqa: E402
import maya_delivery  # noqa: E402
from archive import StagedAudio  # noqa: E402
from transcript_log import InsertOutcome, TranscriptInsertResult  # noqa: E402
from transcript_quality import QualityResult, TranscriptionResult  # noqa: E402


def _inserted(row_id: int) -> TranscriptInsertResult:
    return TranscriptInsertResult(InsertOutcome.INSERTED, row_id=row_id)


def _render_log_calls(*log_mocks: object) -> str:
    return " ".join(str(getattr(mock, "mock_calls", [])) for mock in log_mocks)


class WatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_dir = tempfile.mkdtemp()
        self.db_path = Path(self.db_dir) / "test_transcripts.db"
        patch.object(transcript_log, "TRANSCRIPT_DB_PATH", self.db_path).start()
        patch.object(transcript_log, "_MIGRATION_SOURCES", []).start()
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

    def test_oversized_archive_manifest_reports_skipped_quality_truthfully(self) -> None:
        audio_path = Path(self.db_dir) / "oversized-truth.m4a"
        audio_path.write_bytes(b"audio")
        object_root = Path(self.db_dir) / "objects"
        mirror_root = Path(self.db_dir) / "mirror"
        with (
            patch.object(watcher, "MAX_FILE_SIZE", 0),
            patch.object(watcher.cfg.archive, "object_root", object_root),
            patch.object(watcher.cfg.archive, "mirror_root", mirror_root),
        ):
            self.assertTrue(
                watcher._process_audio_file(
                    audio_path, file_hash="oversized-truth-hash"
                )
            )
            row = transcript_log.get_transcript_by_hash("oversized-truth-hash")
            self.assertEqual(row["quality_status"], "skipped_too_large")
            watcher._process_archive_outbox()
        delivery = transcript_log.get_archive_delivery_health()
        self.assertEqual(delivery["sent_count"], 1)
        manifest_path = next(mirror_root.rglob("*.json"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["quality_status"], "skipped_too_large")

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

    def test_voice_memo_link_preserves_apple_source_path_while_transcript_uses_stage(self) -> None:
        audio_path = Path(self.db_dir) / "source-provenance.m4a"
        audio_path.write_bytes(b"audio")
        object_root = Path(self.db_dir) / "objects"
        transcript_log.upsert_voice_memo_recording(
            204,
            label="source provenance",
            raw_path=audio_path.name,
            duration_seconds=1.0,
        )
        with (
            patch.object(watcher.cfg.archive, "object_root", object_root),
            patch.object(
                watcher,
                "transcribe_with_quality",
                return_value=TranscriptionResult("text", QualityResult(True), 1),
            ),
            patch.object(watcher, "classify_and_route"),
        ):
            self.assertTrue(
                watcher._process_audio_file(
                    audio_path,
                    file_hash="source-provenance-hash",
                    recording_pk=204,
                )
            )
        canonical = transcript_log.get_transcript_by_hash("source-provenance-hash")
        conn = transcript_log._get_conn()
        try:
            source_row = conn.execute(
                "SELECT audio_path FROM voice_memo_ingest WHERE recording_pk = 204"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(source_row["audio_path"], str(audio_path))
        self.assertNotEqual(canonical["audio_path"], str(audio_path))
        self.assertTrue(str(canonical["audio_path"]).startswith(str(object_root)))

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

    def test_published_local_mirror_tamper_and_missing_manifest_rebuild_safely(self) -> None:
        object_root = Path(self.db_dir) / "validation-objects"
        mirror_root = Path(self.db_dir) / "validation-mirror"
        for index in (1, 2):
            source = Path(self.db_dir) / f"validation-{index}.m4a"
            source.write_bytes(f"audio-{index}".encode())
            staged = watcher.stage_audio(source, object_root)
            row_id = transcript_log.insert_transcript(
                content_hash=f"validation-{index}",
                source="iCloud",
                transcript=f"canonical-{index}",
                recorded_at="2026-08-09T19:27:31Z",
                archive_staged=staged,
                archive_metadata={
                    "source": "iCloud",
                    "source_alias": source.name,
                    "original_name": source.name,
                    "quality_status": "passed",
                },
                enqueue_slack=False,
            )
            self.assertIsNotNone(row_id)
        with (
            patch.object(watcher.cfg.archive, "mirror_root", mirror_root),
            patch.object(watcher.cfg.archive, "delivery_batch_limit", 10),
        ):
            watcher._process_archive_outbox()
            published = transcript_log.get_published_archive_deliveries(limit=10)
            self.assertEqual(len(published), 2)
            tampered_markdown = Path(published[0]["destination_markdown_path"])
            os.chmod(tampered_markdown, 0o600)
            tampered_markdown.write_text("tampered", encoding="utf-8")
            Path(published[1]["destination_manifest_path"]).unlink()

            watcher._reconcile_published_archives(limit=10)
            health = transcript_log.get_archive_delivery_health()
            self.assertEqual(health["rebuild_needed_count"], 2)
            self.assertEqual(health["invalid_count"], 2)
            self.assertGreaterEqual(
                len(list((mirror_root / ".penny-conflicts").rglob("*.*"))), 3
            )

            watcher._process_archive_outbox()
            rebuilt = transcript_log.get_published_archive_deliveries(limit=10)
        self.assertEqual(len(rebuilt), 2)
        self.assertTrue(all(row["publication_generation"] == 2 for row in rebuilt))
        self.assertTrue(
            all(watcher.validate_archive(Path(row["destination_manifest_path"])) for row in rebuilt)
        )
        health = transcript_log.get_archive_delivery_health()
        self.assertEqual(health["rebuild_needed_count"], 0)
        self.assertEqual(health["invalid_count"], 0)

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

    def test_find_audio_path_rejects_unsafe_source_paths_and_nonregular_files(self) -> None:
        voice_root = Path(self.db_dir) / "voice-memos"
        voice_root.mkdir()
        safe = voice_root / "safe.m4a"
        safe.write_bytes(b"safe")
        outside = Path(self.db_dir) / "outside.m4a"
        outside.write_bytes(b"outside")
        symlink = voice_root / "symlink.m4a"
        symlink.symlink_to(safe)
        fifo = voice_root / "special.m4a"
        os.mkfifo(fifo)

        with patch.object(watcher, "VOICE_MEMOS_DIR", voice_root):
            unsafe_recordings = [
                {"ZPATH": str(outside), "ZCUSTOMLABEL": "safe"},
                {"ZPATH": "../outside.m4a", "ZCUSTOMLABEL": "safe"},
                {"ZPATH": "symlink.m4a", "ZCUSTOMLABEL": "safe"},
                {"ZPATH": "special.m4a", "ZCUSTOMLABEL": "safe"},
            ]
            for recording in unsafe_recordings:
                with self.subTest(path=recording["ZPATH"]):
                    self.assertIsNone(watcher._find_audio_path_for_recording(recording))

            self.assertEqual(
                watcher._find_audio_path_for_recording({"ZPATH": "safe.m4a"}),
                safe,
            )

            with (
                patch.object(watcher, "get_file_hash", return_value="safe-hash"),
                patch.object(watcher, "is_already_logged", return_value=False),
            ):
                self.assertEqual(
                    watcher.scan_for_unprocessed_files(), [(safe, "safe-hash")]
                )

    def test_voice_memo_root_must_not_be_a_symlink(self) -> None:
        actual_root = Path(self.db_dir) / "voice-memos-real"
        actual_root.mkdir()
        (actual_root / "memo.m4a").write_bytes(b"audio")
        configured_root = Path(self.db_dir) / "voice-memos-link"
        configured_root.symlink_to(actual_root, target_is_directory=True)

        with patch.object(watcher, "VOICE_MEMOS_DIR", configured_root):
            self.assertIsNone(watcher._voice_memo_roots())
            self.assertIsNone(
                watcher._find_audio_path_for_recording({"ZPATH": "memo.m4a"})
            )
            self.assertEqual(watcher.scan_for_unprocessed_files(), [])

    def test_audio_is_staged_before_any_content_hash_read(self) -> None:
        source = Path(self.db_dir) / "source.m4a"
        source.write_bytes(b"source")
        staged_path = Path(self.db_dir) / "objects" / "staged.m4a"
        staged_path.parent.mkdir()
        staged_path.write_bytes(b"stable")
        staged = StagedAudio(staged_path, "a" * 64, 6, ".m4a")

        def hash_only_staged(path: Path) -> str:
            self.assertEqual(path, staged_path)
            return "f" * 32

        with (
            patch.object(watcher, "stage_audio", return_value=staged) as stage,
            patch.object(watcher, "get_file_hash", side_effect=hash_only_staged),
            patch.object(watcher, "MAX_FILE_SIZE", 0),
            patch.object(
                watcher, "insert_transcript_result", return_value=_inserted(77)
            ),
        ):
            self.assertTrue(watcher._process_audio_file(source))

        stage.assert_called_once()

    def test_malformed_recording_timestamp_terminalizes_and_batch_continues(self) -> None:
        state_file = Path(self.db_dir) / "last_pk.txt"
        recordings = [
            {
                "Z_PK": 601,
                "ZCUSTOMLABEL": "bad timestamp",
                "ZPATH": "bad-timestamp.m4a",
                "ZDATE": 0,
                "recorded_at": "not-a-timestamp",
            },
            {
                "Z_PK": 602,
                "ZCUSTOMLABEL": "later memo",
                "ZPATH": "later.m4a",
                "ZDATE": 1,
            },
        ]
        with (
            patch.object(watcher, "STATE_FILE", state_file),
            patch.object(watcher, "process_recording", return_value=True) as process,
        ):
            watcher._process_db_batch(recordings)

        process.assert_called_once_with(recordings[1], already_upserted=True)
        self.assertEqual(state_file.read_text(encoding="utf-8"), "602")
        conn = transcript_log._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT recording_pk, status, error_message, transcript_row_id,
                       audio_path
                FROM voice_memo_ingest
                ORDER BY recording_pk
                """
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual([row["recording_pk"] for row in rows], [601, 602])
        malformed = rows[0]
        self.assertEqual(malformed["status"], "failed_terminal")
        self.assertEqual(malformed["error_message"], "processing_error")
        self.assertIsNone(malformed["transcript_row_id"])
        self.assertIsNone(malformed["audio_path"])
        self.assertNotIn("not-a-timestamp", malformed["error_message"])

    def test_malformed_recording_duration_terminalizes_and_batch_continues(self) -> None:
        state_file = Path(self.db_dir) / "last_pk.txt"
        recordings = [
            {
                "Z_PK": 701,
                "ZCUSTOMLABEL": "bad duration",
                "ZPATH": "bad-duration.m4a",
                "ZDATE": 0,
                "ZDURATION": "not-a-number",
            },
            {
                "Z_PK": 702,
                "ZCUSTOMLABEL": "later memo",
                "ZPATH": "later.m4a",
                "ZDATE": 1,
                "ZDURATION": 1.0,
            },
        ]
        with (
            patch.object(watcher, "STATE_FILE", state_file),
            patch.object(watcher, "process_recording", return_value=True) as process,
        ):
            watcher._process_db_batch(recordings)

        process.assert_called_once_with(recordings[1], already_upserted=True)
        self.assertEqual(state_file.read_text(encoding="utf-8"), "702")
        conn = transcript_log._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT recording_pk, status, error_message, duration_seconds,
                       transcript_row_id, audio_path
                FROM voice_memo_ingest
                ORDER BY recording_pk
                """
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual([row["recording_pk"] for row in rows], [701, 702])
        malformed = rows[0]
        self.assertEqual(malformed["status"], "failed_terminal")
        self.assertEqual(malformed["error_message"], "processing_error")
        self.assertIsNone(malformed["duration_seconds"])
        self.assertIsNone(malformed["transcript_row_id"])
        self.assertIsNone(malformed["audio_path"])

    def test_invalid_metadata_does_not_advance_watermark_without_terminal_receipt(
        self,
    ) -> None:
        state_file = Path(self.db_dir) / "last_pk.txt"
        recordings = [
            {
                "Z_PK": 711,
                "ZPATH": "invalid.m4a",
                "ZDATE": 0,
                "ZDURATION": "invalid",
            },
            {
                "Z_PK": 712,
                "ZPATH": "later.m4a",
                "ZDATE": 1,
                "ZDURATION": 1,
            },
        ]
        previous_watermark = transcript_log.get_source_watermark("voice_memos")
        with (
            patch.object(watcher, "STATE_FILE", state_file),
            patch.object(watcher, "mark_voice_memo_terminal", return_value=False),
            patch.object(watcher, "process_recording") as process,
        ):
            watcher._process_db_batch(recordings)

        process.assert_not_called()
        self.assertFalse(state_file.exists())
        self.assertEqual(
            transcript_log.get_source_watermark("voice_memos"), previous_watermark
        )

    def test_health_check_requires_voice_memos_responsiveness(self) -> None:
        health_path = Path(self.db_dir) / "health.txt"
        with (
            patch.object(watcher, "HEALTH_FILE", health_path),
            patch.object(watcher, "_voicememos_running", return_value=True),
            patch.object(watcher, "_voicememos_responsive", return_value=False),
            patch.object(watcher, "_transcripts_pending", return_value=0),
            patch.object(
                watcher,
                "_cloud_recording_snapshot",
                return_value={
                    "db_ok": True,
                    "record_count": 0,
                    "latest_pk": 0,
                    "latest_date": None,
                    "wal_exists": False,
                    "wal_age_seconds": -1,
                },
            ),
            patch.object(
                watcher,
                "get_voice_memo_health",
                return_value={
                    "latest_recording_pk": 0,
                    "awaiting_file_count": 0,
                    "failed_count": 0,
                    "retry_due_count": 0,
                    "terminal_count": 0,
                    "terminal_failure_count": 0,
                    "max_attempt_count": 0,
                    "source_watermark": 0,
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
                    "pending_count": 0,
                    "due_count": 0,
                    "failed_count": 0,
                    "oldest_due_age_seconds": 0,
                    "quality_needs_review_count": 0,
                    "health_error": 0,
                },
            ),
        ):
            watcher.update_health_check()

        health = health_path.read_text(encoding="utf-8")
        self.assertIn("|watcher_ok:0|", health)
        self.assertIn("|voicememos_responsive:0|", health)

    def test_health_check_requires_cloud_recording_database_integrity(self) -> None:
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
                    "db_ok": False,
                    "record_count": 0,
                    "latest_pk": 0,
                    "latest_date": None,
                    "wal_exists": False,
                    "wal_age_seconds": -1,
                },
            ),
            patch.object(
                watcher,
                "get_voice_memo_health",
                return_value={
                    "latest_recording_pk": 0,
                    "awaiting_file_count": 0,
                    "failed_count": 0,
                    "retry_due_count": 0,
                    "terminal_count": 0,
                    "terminal_failure_count": 0,
                    "max_attempt_count": 0,
                    "source_watermark": 0,
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
                    "pending_count": 0,
                    "due_count": 0,
                    "failed_count": 0,
                    "oldest_due_age_seconds": 0,
                    "quality_needs_review_count": 0,
                    "health_error": 0,
                },
            ),
        ):
            watcher.update_health_check()

        health = health_path.read_text(encoding="utf-8")
        self.assertIn("|watcher_ok:0|", health)
        self.assertIn("|voice_db_ok:0|", health)

    def test_historical_backfill_queues_old_linked_audio_without_retranscription(self) -> None:
        source = Path(self.db_dir) / "historical.m4a"
        source.write_bytes(b"historical audio")
        row_id = transcript_log.insert_transcript(
            content_hash="historical-backfill",
            source="iCloud",
            transcript="already canonical",
            recorded_at="2025-01-02T03:04:05Z",
            enqueue_slack=False,
        )
        transcript_log.upsert_voice_memo_recording(
            701,
            label="historical",
            raw_path=source.name,
            duration_seconds=2.0,
            recorded_at="2025-01-02T03:04:05Z",
        )
        transcript_log.link_voice_memo_transcript(
            701,
            transcript_row_id=int(row_id),
            content_hash="historical-backfill",
            audio_path=str(source),
        )
        with (
            patch.object(
                watcher.cfg.archive,
                "object_root",
                Path(self.db_dir) / "historical-objects",
            ),
            patch.object(watcher, "VOICE_MEMOS_DIR", Path(self.db_dir)),
            patch.object(watcher, "transcribe_with_quality") as transcribe,
            patch.object(watcher, "classify_and_route") as route,
        ):
            watcher._reconcile_archive_backfill(limit=100)
        transcribe.assert_not_called()
        route.assert_not_called()
        due = transcript_log.get_pending_archive_deliveries(limit=5)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["transcript_row_id"], row_id)
        self.assertEqual(due[0]["canonical_recorded_at"], "2025-01-02T03:04:05Z")
        self.assertTrue(
            Path(due[0]["local_object_path"]).is_relative_to(
                Path(self.db_dir) / "historical-objects"
            )
        )

    def test_historical_backfill_rejects_unapproved_db_path_without_opening(self) -> None:
        outside = Path(self.db_dir).parent / "private-recording.m4a"
        outside.write_bytes(b"must not be opened")
        self.addCleanup(outside.unlink, missing_ok=True)
        row_id = transcript_log.insert_transcript(
            content_hash="unsafe-backfill-path",
            source="iCloud",
            transcript="canonical",
            audio_path=str(outside),
            enqueue_slack=False,
        )
        with (
            patch.object(watcher, "VOICE_MEMOS_DIR", Path(self.db_dir) / "approved"),
            patch.object(watcher, "stage_audio") as stage,
        ):
            watcher._reconcile_archive_backfill(limit=10)
        stage.assert_not_called()
        conn = transcript_log._get_conn()
        try:
            delivery = conn.execute(
                "SELECT status, unavailable_reason FROM archive_deliveries "
                "WHERE transcript_row_id = ?", (row_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(tuple(delivery), ("unavailable", "unsafe_audio_source"))

    def test_historical_backfill_queue_failure_is_durable_and_retryable(self) -> None:
        source = Path(self.db_dir) / "retryable.m4a"
        source.write_bytes(b"audio")
        row_id = transcript_log.insert_transcript(
            content_hash="retryable-backfill",
            source="iCloud",
            transcript="canonical",
            audio_path=str(source),
            enqueue_slack=False,
        )
        with (
            patch.object(watcher, "VOICE_MEMOS_DIR", Path(self.db_dir)),
            patch.object(
                watcher, "queue_archive_delivery",
                side_effect=sqlite3.OperationalError("secret path"),
            ),
        ):
            watcher._reconcile_archive_backfill(limit=10)
        conn = transcript_log._get_conn()
        try:
            delivery = conn.execute(
                "SELECT status, attempt_count, next_attempt_at, last_error_code "
                "FROM archive_deliveries WHERE transcript_row_id = ?", (row_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(delivery["status"], "backfill_pending")
        self.assertEqual(delivery["attempt_count"], 1)
        self.assertIsNotNone(delivery["next_attempt_at"])
        self.assertEqual(delivery["last_error_code"], "archive_backfill_queue_error")
        health = transcript_log.get_archive_delivery_health()
        self.assertEqual(health["backfill_pending_count"], 1)
        for _ in range(4):
            conn = transcript_log._get_conn()
            try:
                conn.execute(
                    "UPDATE archive_deliveries SET next_attempt_at = datetime('now', '-1 second') "
                    "WHERE transcript_row_id = ?", (row_id,),
                )
                conn.commit()
            finally:
                conn.close()
            with (
                patch.object(watcher, "VOICE_MEMOS_DIR", Path(self.db_dir)),
                patch.object(
                    watcher, "queue_archive_delivery",
                    side_effect=RuntimeError("secret content"),
                ),
            ):
                watcher._reconcile_archive_backfill(limit=10)
        health = transcript_log.get_archive_delivery_health()
        self.assertEqual(health["backfill_pending_count"], 0)
        self.assertEqual(health["backfill_failed_count"], 1)

    def test_historical_backfill_reuses_only_verified_local_object(self) -> None:
        source = Path(self.db_dir) / "local-object-source.m4a"
        source.write_bytes(b"audio")
        object_root = Path(self.db_dir) / "objects"
        staged = watcher.stage_audio(source, object_root)
        row_id = transcript_log.insert_transcript(
            content_hash="verified-local-object",
            source="iCloud",
            transcript="canonical",
            audio_path=str(staged.path),
            enqueue_slack=False,
        )
        conn = transcript_log._get_conn()
        try:
            conn.execute(
                "UPDATE transcripts SET audio_sha256 = ? WHERE id = ?",
                (staged.audio_sha256, row_id),
            )
            conn.commit()
        finally:
            conn.close()
        with (
            patch.object(watcher.cfg.archive, "object_root", object_root),
            patch.object(watcher, "stage_audio") as restage,
        ):
            watcher._reconcile_archive_backfill(limit=10)
        restage.assert_not_called()
        pending = transcript_log.get_pending_archive_deliveries(limit=10)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["local_object_path"], str(staged.path.resolve()))

    def test_partial_archive_migration_recovers_valid_audio_without_reopening_terminal_rows(self) -> None:
        source = Path(self.db_dir) / "migration-recovery.m4a"
        source.write_bytes(b"recoverable audio")
        row_id = transcript_log.insert_transcript(
            content_hash="migration-recovery",
            source="iCloud",
            transcript="canonical",
            audio_path=str(source),
            enqueue_slack=False,
        )
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("DROP TABLE archive_deliveries")
            conn.execute(
                "CREATE TABLE archive_deliveries ("
                "id INTEGER PRIMARY KEY, transcript_id INTEGER, status TEXT)"
            )
            conn.execute(
                "INSERT INTO archive_deliveries VALUES (41, ?, 'pending')", (row_id,)
            )
            conn.commit()
        finally:
            conn.close()
        transcript_log.init_db()
        terminal_id = transcript_log.insert_transcript(
            content_hash="terminal-legacy-placeholder",
            source="iCloud",
            transcript="(migrated legacy placeholder)",
            enqueue_slack=False,
        )
        transcript_log.record_archive_unavailable(
            int(terminal_id),
            availability_status="unavailable",
            reason_code="legacy_placeholder",
        )
        candidates = transcript_log.get_archive_backfill_candidates(limit=10)
        self.assertEqual(
            [row["transcript_row_id"] for row in candidates], [row_id]
        )
        object_root = Path(self.db_dir) / "migration-objects"
        with (
            patch.object(watcher, "VOICE_MEMOS_DIR", Path(self.db_dir)),
            patch.object(watcher.cfg.archive, "object_root", object_root),
        ):
            watcher._reconcile_archive_backfill(limit=10)
        pending = transcript_log.get_pending_archive_deliveries(limit=10)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["transcript_row_id"], row_id)
        self.assertTrue(
            Path(pending[0]["local_object_path"]).is_relative_to(object_root)
        )

    def test_outside_root_published_paths_become_visible_without_open_or_move(self) -> None:
        source = Path(self.db_dir) / "outside-root.m4a"
        source.write_bytes(b"audio")
        staged = watcher.stage_audio(source, Path(self.db_dir) / "objects")
        row_id = transcript_log.insert_transcript(
            content_hash="outside-root",
            source="iCloud",
            transcript="canonical",
            archive_staged=staged,
            archive_metadata={"source": "iCloud", "quality_status": "passed"},
            enqueue_slack=False,
        )
        mirror_root = Path(self.db_dir) / "mirror"
        with patch.object(watcher.cfg.archive, "mirror_root", mirror_root):
            watcher._process_archive_outbox()
        outside = Path(self.db_dir) / "outside"
        outside.mkdir()
        outside_files = [outside / f"capture{suffix}" for suffix in (".m4a", ".md", ".json")]
        for path in outside_files:
            path.write_bytes(b"do not touch")
        conn = transcript_log._get_conn()
        try:
            conn.execute(
                "UPDATE archive_deliveries SET destination_audio_path = ?, "
                "destination_markdown_path = ?, destination_manifest_path = ? "
                "WHERE transcript_row_id = ?",
                (*map(str, outside_files), row_id),
            )
            conn.commit()
        finally:
            conn.close()
        with patch.object(watcher.cfg.archive, "mirror_root", mirror_root):
            watcher._reconcile_published_archives(limit=10)
        self.assertTrue(all(path.read_bytes() == b"do not touch" for path in outside_files))
        conn = transcript_log._get_conn()
        try:
            delivery = conn.execute(
                "SELECT status, validation_status, rebuild_needed, validation_error_code "
                "FROM archive_deliveries WHERE transcript_row_id = ?", (row_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(
            tuple(delivery),
            ("pending", "invalid", 1, "local_mirror_path_outside_root"),
        )

    def test_historical_non_audio_and_missing_audio_are_visible_in_health(self) -> None:
        transcript_log.insert_transcript(
            content_hash="historical-text",
            source="text",
            transcript="no raw audio by design",
            enqueue_slack=False,
        )
        transcript_log.insert_transcript(
            content_hash="historical-missing-audio",
            source="iCloud",
            transcript="audio is unavailable",
            enqueue_slack=False,
        )
        watcher._reconcile_archive_backfill(limit=100)
        health = transcript_log.get_archive_delivery_health()
        self.assertEqual(health["not_applicable_count"], 1)
        self.assertEqual(health["unavailable_count"], 1)

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
            patch.object(watcher, "queue_archive_delivery"),
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
            patch.object(watcher, "queue_archive_delivery"),
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

    def test_existing_canonical_archive_queue_failure_blocks_success(self) -> None:
        audio_path = Path(self.db_dir) / "existing-queue-failure.m4a"
        audio_path.write_bytes(b"audio")
        canonical = {
            "id": 189,
            "status": "pending",
            "quality_status": "passed",
            "transcript": "do not route yet",
            "source": "iCloud",
        }
        with (
            patch.object(watcher, "get_transcript_by_hash", return_value=canonical),
            patch.object(
                watcher,
                "queue_archive_delivery",
                side_effect=sqlite3.OperationalError("archive unavailable"),
            ),
            patch.object(watcher, "classify_and_route") as route,
            patch.object(watcher, "link_voice_memo_transcript") as link,
            patch.object(watcher, "mark_voice_memo_routed") as routed,
        ):
            self.assertFalse(
                watcher._process_audio_file(
                    audio_path,
                    file_hash="existing-queue-failure-hash",
                    recording_pk=189,
                )
            )
        route.assert_not_called()
        link.assert_not_called()
        routed.assert_not_called()

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
            patch.object(watcher, "queue_archive_delivery"),
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

    def test_process_file_logs_no_filename_path_exception_text_or_traceback(
        self,
    ) -> None:
        filename = "PRIVATE_VOICE_MEMO_FILENAME_SENTINEL.m4a"
        audio_path = Path(self.db_dir) / filename
        audio_path.write_bytes(b"private audio")
        exception_text = (
            f"PROVIDER_EXCEPTION_TEXT_SENTINEL at {audio_path} with private detail"
        )

        with (
            patch.object(
                watcher,
                "_process_audio_file",
                side_effect=RuntimeError(exception_text),
            ),
            patch.object(watcher.log, "info") as info_log,
            patch.object(watcher.log, "warning") as warning_log,
            patch.object(watcher.log, "error") as error_log,
        ):
            self.assertFalse(watcher.process_file(audio_path))

        rendered = _render_log_calls(info_log, warning_log, error_log)
        self.assertNotIn(filename, rendered)
        self.assertNotIn(str(audio_path), rendered)
        self.assertNotIn(exception_text, rendered)
        self.assertNotIn("exc_info", rendered)
        self.assertIn("RuntimeError", rendered)

    def test_process_recording_logs_pk_without_label_or_raw_path(self) -> None:
        label = "PRIVATE_VOICE_MEMO_LABEL_SENTINEL"
        raw_path = "PRIVATE_VOICE_MEMO_RAW_PATH_SENTINEL.m4a"
        recording = {
            "Z_PK": 818,
            "ZCUSTOMLABEL": label,
            "ZPATH": raw_path,
            "ZDATE": None,
            "ZDURATION": None,
        }

        with (
            patch.object(watcher, "_find_audio_path_for_recording", return_value=None),
            patch.object(watcher, "mark_voice_memo_waiting_for_file"),
            patch.object(watcher, "mark_voice_memo_retryable"),
            patch.object(watcher.log, "info") as info_log,
            patch.object(watcher.log, "error") as error_log,
        ):
            self.assertFalse(
                watcher.process_recording(recording, already_upserted=True)
            )

        rendered = _render_log_calls(info_log, error_log)
        self.assertNotIn(label, rendered)
        self.assertNotIn(raw_path, rendered)
        self.assertIn("818", rendered)

    def test_source_database_logs_no_private_path_or_exception_text(self) -> None:
        db_path = Path(self.db_dir) / "PRIVATE_CLOUD_DB_PATH_SENTINEL.sqlite"
        exception_text = f"PRIVATE_SQLITE_EXCEPTION_SENTINEL at {db_path}"

        with (
            patch.object(watcher, "CLOUDRECORDINGS_DB", db_path),
            patch.object(watcher.log, "warning") as warning_log,
        ):
            self.assertEqual(watcher.get_new_recordings(), [])

        missing_rendered = _render_log_calls(warning_log)
        self.assertNotIn(db_path.name, missing_rendered)
        self.assertNotIn(str(db_path), missing_rendered)

        db_path.touch()
        with (
            patch.object(watcher, "CLOUDRECORDINGS_DB", db_path),
            patch.object(
                watcher.sqlite3,
                "connect",
                side_effect=RuntimeError(exception_text),
            ),
            patch.object(watcher.log, "error") as error_log,
        ):
            self.assertEqual(watcher.get_new_recordings(), [])

        failed_rendered = _render_log_calls(error_log)
        self.assertNotIn(db_path.name, failed_rendered)
        self.assertNotIn(str(db_path), failed_rendered)
        self.assertNotIn(exception_text, failed_rendered)
        self.assertIn("RuntimeError", failed_rendered)

    def test_source_health_probes_log_only_exit_and_error_classes(self) -> None:
        db_path = Path(self.db_dir) / "PRIVATE_HEALTH_DB_PATH_SENTINEL.sqlite"
        db_path.touch()
        exception_text = f"PRIVATE_HEALTH_EXCEPTION_SENTINEL at {db_path}"
        provider_text = "PRIVATE_APPLE_EVENT_PROVIDER_TEXT_SENTINEL"

        with (
            patch.object(watcher, "CLOUDRECORDINGS_DB", db_path),
            patch.object(
                watcher.sqlite3,
                "connect",
                side_effect=RuntimeError(exception_text),
            ),
            patch.object(watcher.log, "warning") as database_log,
        ):
            snapshot = watcher._cloud_recording_snapshot()

        self.assertFalse(snapshot["db_ok"])
        database_rendered = _render_log_calls(database_log)
        self.assertNotIn(db_path.name, database_rendered)
        self.assertNotIn(str(db_path), database_rendered)
        self.assertNotIn(exception_text, database_rendered)
        self.assertIn("RuntimeError", database_rendered)

        failed_probe = SimpleNamespace(
            returncode=17,
            stdout="",
            stderr=provider_text,
        )
        with (
            patch.object(watcher.subprocess, "run", return_value=failed_probe),
            patch.object(watcher.log, "warning") as provider_log,
        ):
            self.assertFalse(watcher._voicememos_responsive())

        provider_rendered = _render_log_calls(provider_log)
        self.assertNotIn(provider_text, provider_rendered)
        self.assertIn("17", provider_rendered)

    def test_disk_scan_logs_no_filename_path_or_exception_text(self) -> None:
        voice_root = Path(self.db_dir) / "private-voice-root"
        voice_root.mkdir()
        filename = "PRIVATE_SCAN_FILENAME_SENTINEL.m4a"
        audio_path = voice_root / filename
        audio_path.write_bytes(b"private audio")
        exception_text = f"PRIVATE_HASH_EXCEPTION_SENTINEL at {audio_path}"

        with (
            patch.object(watcher, "VOICE_MEMOS_DIR", voice_root),
            patch.object(
                watcher,
                "get_file_hash",
                side_effect=RuntimeError(exception_text),
            ),
            patch.object(watcher.log, "warning") as warning_log,
        ):
            self.assertEqual(watcher.scan_for_unprocessed_files(), [])

        rendered = _render_log_calls(warning_log)
        self.assertNotIn(filename, rendered)
        self.assertNotIn(str(audio_path), rendered)
        self.assertNotIn(exception_text, rendered)
        self.assertIn("RuntimeError", rendered)

    def test_outbox_logs_no_provider_exception_text_or_tracebacks(self) -> None:
        slack_text = "PRIVATE_SLACK_PROVIDER_EXCEPTION_SENTINEL"
        maya_text = "PRIVATE_MAYA_PROVIDER_EXCEPTION_SENTINEL"

        with (
            patch.object(
                watcher,
                "process_pending_slack",
                side_effect=RuntimeError(slack_text),
            ),
            patch.object(
                watcher,
                "process_pending_maya_deliveries",
                side_effect=RuntimeError(maya_text),
            ),
            patch.object(watcher.log, "error") as error_log,
        ):
            watcher._process_slack_outbox()
            watcher._process_maya_outbox()

        rendered = _render_log_calls(error_log)
        self.assertNotIn(slack_text, rendered)
        self.assertNotIn(maya_text, rendered)
        self.assertNotIn("exc_info", rendered)
        self.assertGreaterEqual(rendered.count("RuntimeError"), 2)

    def test_retry_logs_id_without_source_or_exception_text(self) -> None:
        source = "PRIVATE_RETRY_SOURCE_PROVIDER_SENTINEL"
        exception_text = "PRIVATE_RETRY_EXCEPTION_TEXT_SENTINEL"
        pending_row = {
            "id": 913,
            "source": source,
            "transcript": "route this",
            "duration_seconds": None,
        }

        with (
            patch.object(watcher, "get_pending", return_value=[pending_row]),
            patch.object(
                watcher,
                "classify_and_route",
                side_effect=RuntimeError(exception_text),
            ),
            patch.object(watcher.log, "info") as info_log,
            patch.object(watcher.log, "error") as error_log,
        ):
            watcher._retry_pending_routes(limit=1)

        rendered = _render_log_calls(info_log, error_log)
        self.assertNotIn(source, rendered)
        self.assertNotIn(exception_text, rendered)
        self.assertIn("913", rendered)
        self.assertIn("RuntimeError", rendered)

    def test_startup_logs_no_paths_model_or_unbounded_dependency_text(self) -> None:
        voice_root = Path(self.db_dir) / "PRIVATE_STARTUP_VOICE_PATH_SENTINEL"
        voice_root.mkdir()
        cloud_db = voice_root / "PRIVATE_STARTUP_DB_FILENAME_SENTINEL.sqlite"
        warning_text = "PRIVATE_STARTUP_WARNING_TEXT_SENTINEL"
        error_text = "PRIVATE_STARTUP_ERROR_TEXT_SENTINEL"
        model_text = "PRIVATE_MODEL_PROVIDER_SENTINEL"

        with (
            patch.object(watcher, "VOICE_MEMOS_DIR", voice_root),
            patch.object(watcher, "CLOUDRECORDINGS_DB", cloud_db),
            patch.object(watcher.cfg.llm, "model", model_text),
            patch.object(watcher, "init_db"),
            patch.object(
                watcher,
                "check_dependencies",
                return_value=([error_text], [warning_text]),
            ),
            patch.object(watcher, "get_last_seen_pk", return_value=42),
            patch.object(watcher, "_ensure_voicememos_running"),
            patch.object(watcher, "_process_ingest_pass"),
            patch.object(watcher, "update_health_check"),
            patch.object(watcher.time, "sleep", side_effect=[None, KeyboardInterrupt]),
            patch.object(watcher.log, "info") as info_log,
            patch.object(watcher.log, "warning") as warning_log,
            patch.object(watcher.log, "error") as error_log,
        ):
            watcher.main()

        rendered = _render_log_calls(info_log, warning_log, error_log)
        for private_value in (
            voice_root.name,
            str(voice_root),
            cloud_db.name,
            str(cloud_db),
            warning_text,
            error_text,
            model_text,
        ):
            self.assertNotIn(private_value, rendered)
        self.assertIn("42", rendered)

    def test_poll_loop_logs_exception_class_without_text_or_traceback(self) -> None:
        voice_root = Path(self.db_dir) / "voice-root"
        voice_root.mkdir()
        exception_text = "PRIVATE_POLL_EXCEPTION_TEXT_SENTINEL"

        with (
            patch.object(watcher, "VOICE_MEMOS_DIR", voice_root),
            patch.object(watcher, "init_db"),
            patch.object(watcher, "check_dependencies", return_value=([], [])),
            patch.object(watcher, "get_last_seen_pk", return_value=42),
            patch.object(watcher, "_ensure_voicememos_running"),
            patch.object(
                watcher,
                "_process_ingest_pass",
                side_effect=[None, RuntimeError(exception_text)],
            ),
            patch.object(watcher, "update_health_check"),
            patch.object(
                watcher.time,
                "sleep",
                side_effect=[None, None, None, KeyboardInterrupt],
            ),
            patch.object(watcher.log, "error") as error_log,
        ):
            watcher.main()

        rendered = _render_log_calls(error_log)
        self.assertNotIn(exception_text, rendered)
        self.assertNotIn("exc_info", rendered)
        self.assertIn("RuntimeError", rendered)

    def test_audio_pipeline_logs_pk_without_filename_or_quality_detail(self) -> None:
        filename = "PRIVATE_PIPELINE_FILENAME_SENTINEL.m4a"
        audio_path = Path(self.db_dir) / filename
        audio_path.write_bytes(b"private audio")
        quality_detail = "PRIVATE_TRANSCRIPTION_PROVIDER_DETAIL_SENTINEL"
        staged = StagedAudio(audio_path, "a" * 64, audio_path.stat().st_size, ".m4a")

        with (
            patch.object(watcher, "stage_audio", return_value=staged),
            patch.object(watcher, "get_file_hash", return_value="pipeline-md5"),
            patch.object(watcher, "get_transcript_by_hash", return_value=None),
            patch.object(
                watcher,
                "transcribe_with_quality",
                return_value=TranscriptionResult(
                    "private transcript",
                    QualityResult(False, quality_detail),
                    1,
                    quality_detail,
                ),
            ),
            patch.object(
                watcher,
                "insert_transcript_result",
                return_value=TranscriptInsertResult(
                    InsertOutcome.FAILED,
                    error_code="database_unavailable",
                ),
            ),
            patch.object(watcher.log, "warning") as warning_log,
            patch.object(watcher.log, "error") as error_log,
        ):
            self.assertFalse(
                watcher._process_audio_file(
                    audio_path,
                    file_hash="pipeline-hash",
                    recording_pk=927,
                )
            )

        rendered = _render_log_calls(warning_log, error_log)
        self.assertNotIn(filename, rendered)
        self.assertNotIn(str(audio_path), rendered)
        self.assertNotIn(quality_detail, rendered)
        self.assertIn("927", rendered)

    def test_archive_backfill_logs_id_and_class_without_source_details(self) -> None:
        voice_root = Path(self.db_dir) / "voice-root"
        voice_root.mkdir()
        filename = "PRIVATE_BACKFILL_FILENAME_SENTINEL.m4a"
        audio_path = voice_root / filename
        audio_path.write_bytes(b"private audio")
        exception_text = f"PRIVATE_BACKFILL_EXCEPTION_SENTINEL at {audio_path}"
        candidate = {
            "transcript_row_id": 941,
            "transcript_audio_path": None,
            "voice_audio_path": str(audio_path),
            "audio_sha256": None,
            "source": "iCloud",
            "transcript": "private transcript",
            "recorded_at": None,
            "created_at": None,
            "duration_seconds": None,
            "transcription_backend": None,
            "transcription_model": None,
            "quality_status": "passed",
        }

        with (
            patch.object(watcher, "VOICE_MEMOS_DIR", voice_root),
            patch.object(
                watcher,
                "get_archive_backfill_candidates",
                return_value=[candidate],
            ),
            patch.object(
                watcher,
                "stage_audio",
                side_effect=RuntimeError(exception_text),
            ),
            patch.object(watcher, "record_archive_backfill_failure"),
            patch.object(watcher.log, "error") as error_log,
        ):
            watcher._reconcile_archive_backfill(limit=1)

        rendered = _render_log_calls(error_log)
        self.assertNotIn(filename, rendered)
        self.assertNotIn(str(audio_path), rendered)
        self.assertNotIn(exception_text, rendered)
        self.assertIn("941", rendered)
        self.assertIn("RuntimeError", rendered)

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
            patch.object(
                core,
                "ensure_note",
                return_value=AppleEffectReceipt(
                    "f" * 64, "note", "note-id", "succeeded",
                    actual_target="Penny", transcript_id=row_id,
                ),
            ) as ensure_note,
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
        ensure_note.assert_called_once()
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

    def test_maya_worker_uses_bounded_config_and_continues_after_row_failure(self) -> None:
        first = {"id": 101, "maya_delivery_attempt_count": 19}
        second = {"id": 102, "maya_delivery_attempt_count": 0}
        envelope = {
            "schema_version": "penny-maya.v2",
            "transcript_id": "102",
            "transcript_sha256": "a" * 64,
            "transcript": "second row",
            "source": "icloud",
            "captured_at": "2026-08-10T12:00:00Z",
            "duration_seconds": None,
            "audio_provenance": {"content_hash": "b" * 32, "audio_path": None, "recording_pk": None},
            "source_spans": [],
            "client_ref": "penny:102",
        }
        response = SimpleNamespace(status_code=200, json=lambda: {})
        with (
            patch.object(
                maya_delivery.cfg.maya,
                "transcript_url",
                "http://maya.test/ingest/transcript",
            ),
            patch.object(maya_delivery.cfg.maya, "ingest_token", "test-token"),
            patch.object(maya_delivery.cfg.maya, "max_attempts", 3),
            patch.object(maya_delivery.cfg.maya, "max_age_days", 2),
            patch.object(
                maya_delivery,
                "get_pending_maya_deliveries",
                return_value=[first, second],
            ) as pending,
            patch.object(
                maya_delivery,
                "claim_maya_delivery",
                side_effect=[
                    {
                        "transcript_id": "101",
                        "maya_claim_token": "token-101",
                        "maya_claim_owner": "test-worker",
                        "maya_claimed_at": "2026-08-10T12:00:00Z",
                        "maya_claim_expires_at": "2026-08-10T12:02:00Z",
                    },
                    {
                        "transcript_id": "102",
                        "maya_claim_token": "token-102",
                        "maya_claim_owner": "test-worker",
                        "maya_claimed_at": "2026-08-10T12:00:00Z",
                        "maya_claim_expires_at": "2026-08-10T12:02:00Z",
                    },
                ],
            ),
            patch.object(
                maya_delivery,
                "build_maya_v2_envelope",
                side_effect=[RuntimeError("bad first row"), envelope],
            ),
            patch.object(
                maya_delivery,
                "mark_maya_delivery_failed",
                side_effect=RuntimeError("database unavailable"),
            ),
            patch.object(maya_delivery.requests, "post", return_value=response) as post,
            patch.object(maya_delivery, "_validated_drop_id", return_value="drop-102"),
            patch.object(maya_delivery, "mark_maya_delivery_sent"),
        ):
            delivered = maya_delivery.process_pending_maya_deliveries(limit=2)

        self.assertEqual(delivered, 1)
        pending.assert_called_once_with(
            limit=2,
            max_attempts=3,
            max_age_days=2,
        )
        post.assert_called_once()

    def test_maya_worker_terminalizes_capped_row_before_http(self) -> None:
        now = "2026-08-10T12:00:00Z"
        row_id = transcript_log.insert_transcript(
            content_hash="maya-worker-terminal-before-http",
            source="iCloud",
            transcript="This capped row must not reach Maya.",
            ingest_state="transcribed",
            recorded_at=now,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        conn = transcript_log._get_conn()
        try:
            conn.execute(
                "UPDATE transcripts SET maya_delivery_attempt_count = 20, "
                "maya_first_attempt_at = ? WHERE id = ?",
                ("2026-08-01T12:00:00Z", row_id),
            )
            conn.commit()
        finally:
            conn.close()

        with (
            patch.object(
                maya_delivery.cfg.maya,
                "transcript_url",
                "http://maya.test/ingest/transcript",
            ),
            patch.object(maya_delivery.cfg.maya, "ingest_token", "test-token"),
            patch.object(maya_delivery.requests, "post") as post,
        ):
            delivered = maya_delivery.process_pending_maya_deliveries(limit=5)

        self.assertEqual(delivered, 0)
        post.assert_not_called()
        stored = transcript_log.get_transcript(int(row_id))
        self.assertEqual(stored["maya_delivery_status"], "dead_letter")
        self.assertEqual(stored["maya_dead_letter_reason"], "attempt_cap")

    def test_two_maya_workers_claim_one_row_and_post_once(self) -> None:
        now = "2026-08-10T12:00:00Z"
        row_id = transcript_log.insert_transcript(
            content_hash="maya-two-worker-claim",
            source="iCloud",
            transcript="Two workers must produce one HTTP request.",
            ingest_state="transcribed",
            recorded_at=now,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        selected = {
            "id": int(row_id),
            "maya_delivery_attempt_count": 0,
        }
        pending_calls = 0
        pending_lock = threading.Lock()

        def pending_rows(*, limit: int, max_attempts: int, max_age_days: int):
            nonlocal pending_calls
            with pending_lock:
                pending_calls += 1
            return [selected]

        response = SimpleNamespace(status_code=200, json=lambda: {})
        results: list[int] = []
        with (
            patch.object(
                maya_delivery.cfg.maya,
                "transcript_url",
                "http://maya.test/ingest/transcript",
            ),
            patch.object(maya_delivery.cfg.maya, "ingest_token", "test-token"),
            patch.object(maya_delivery, "get_pending_maya_deliveries", side_effect=pending_rows),
            patch.object(maya_delivery.requests, "post", return_value=response) as post,
            patch.object(maya_delivery, "_validated_drop_id", return_value="drop-two-worker"),
        ):
            workers = [
                threading.Thread(
                    target=lambda: results.append(
                        maya_delivery.process_pending_maya_deliveries(limit=1)
                    )
                )
                for _ in range(2)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=5)

        self.assertEqual(pending_calls, 2)
        self.assertEqual(sorted(results), [0, 1])
        self.assertEqual(post.call_count, 1)
        stored = transcript_log.get_transcript(int(row_id))
        self.assertEqual(stored["maya_delivery_status"], "sent")
        self.assertEqual(stored["maya_drop_id"], "drop-two-worker")
        self.assertIsNone(stored["maya_claim_token"])

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

    def test_cloud_recording_snapshot_fails_closed_when_schema_is_missing(self) -> None:
        db_path = Path(self.db_dir) / "CloudRecordings.db"
        connection = sqlite3.connect(db_path)
        connection.execute("CREATE TABLE unrelated (id INTEGER)")
        connection.commit()
        connection.close()

        with patch.object(watcher, "CLOUDRECORDINGS_DB", db_path):
            snapshot = watcher._cloud_recording_snapshot()

        self.assertFalse(snapshot["db_ok"])
        self.assertEqual(snapshot["record_count"], 0)
        self.assertEqual(snapshot["latest_pk"], 0)

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
