from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import transcript_log  # noqa: E402
import watcher  # noqa: E402
from archive import StagedAudio  # noqa: E402
from transcript_quality import QualityResult, TranscriptionResult  # noqa: E402
from scripts.backfill_voice_memos import compact_ranges, run_backfill  # noqa: E402


class BackfillVoiceMemoTests(unittest.TestCase):
    def test_unavailable_linked_placeholder_does_not_starve_next_batch(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash='missing', source='iCloud',
            transcript='(migrated — original transcript not preserved)',
            quality_status='pending', enqueue_slack=False,
        )
        transcript_log.upsert_voice_memo_recording(10, raw_path='missing.m4a', label='old', duration_seconds=1)
        transcript_log.link_voice_memo_transcript(10, transcript_row_id=row_id, content_hash='missing', audio_path='missing.m4a')
        (self.voice_root / '10.m4a').unlink()
        first = run_backfill(limit=1)
        self.assertEqual(first['failed_count'], 1)
        with patch.object(watcher, 'transcribe_with_quality', return_value=TranscriptionResult('next available', QualityResult(True), 1)):
            second = run_backfill(limit=1)
        self.assertEqual(second['processed_count'], 1)

    def test_linked_migration_placeholder_is_recovered_in_place(self) -> None:
        audio = self.voice_root / '10.m4a'
        content_hash = watcher.get_file_hash(audio)
        row_id = transcript_log.insert_transcript(
            content_hash=content_hash, source='iCloud',
            transcript='(migrated — original transcript not preserved)',
            quality_status='pending', quality_detail=None,
            enqueue_slack=False,
        )
        transcript_log.upsert_voice_memo_recording(10, raw_path='10.m4a', label='old', duration_seconds=1)
        transcript_log.link_voice_memo_transcript(
            10, transcript_row_id=row_id, content_hash=content_hash,
            audio_path=str(audio), routed=True,
        )
        with transcript_log._get_conn() as conn:
            conn.execute("INSERT INTO slack_deliveries (transcript_row_id, status, channel_id, message_text) VALUES (?, 'pending', 'C_TEST', 'old placeholder')", (row_id,))
        with patch.object(watcher, 'transcribe_with_quality', return_value=
                          TranscriptionResult('Recovered actual words.', QualityResult(True), 1)) as transcribe:
            report = run_backfill(limit=1)
            self.assertEqual(transcript_log.get_transcript(row_id)['transcript'], 'Recovered actual words.')
            transcribe.assert_called_once()
        self.assertEqual(report['downstream_effect_count'], 1)
        self.assertIsNone(transcript_log.claim_next_slack_delivery('test'))
        with transcript_log._get_conn() as conn:
            self.assertEqual(conn.execute('SELECT status FROM slack_deliveries WHERE transcript_row_id=?', (row_id,)).fetchone()[0], 'suppressed')
        self.assertEqual(transcript_log.get_transcript(row_id)['routing_suppressed'], 1)
        with patch.object(watcher, 'transcribe_with_quality') as transcribe:
            watcher.process_recording(watcher.get_recordings_by_pk([10])[10], local_only=True)
            transcribe.assert_not_called()

    def setUp(self) -> None:
        self.db_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.db_dir, ignore_errors=True)
        self.db_path = Path(self.db_dir) / "transcripts.db"
        self.source_db = Path(self.db_dir) / "CloudRecordings.db"
        self.voice_root = Path(self.db_dir) / "voice"
        self.voice_root.mkdir()
        self.object_root = Path(self.db_dir) / "objects"
        patch.object(transcript_log, "TRANSCRIPT_DB_PATH", self.db_path).start()
        patch.object(transcript_log, "_MIGRATION_SOURCES", []).start()
        patch.object(watcher, "CLOUDRECORDINGS_DB", self.source_db).start()
        patch.object(watcher, "VOICE_MEMOS_DIR", self.voice_root).start()
        patch.object(watcher.cfg.archive, "object_root", self.object_root).start()
        transcript_log.init_db()
        self.addCleanup(patch.stopall)
        self._create_source_rows()

    def _create_source_rows(self) -> None:
        conn = sqlite3.connect(self.source_db)
        try:
            conn.execute(
                """
                CREATE TABLE ZCLOUDRECORDING (
                    Z_PK INTEGER PRIMARY KEY,
                    ZCUSTOMLABEL TEXT,
                    ZDATE REAL,
                    ZDURATION REAL,
                    ZPATH TEXT
                )
                """
            )
            conn.executemany(
                "INSERT INTO ZCLOUDRECORDING VALUES (?, ?, ?, ?, ?)",
                [
                    (10, "private old one", 1.0, 1.0, "10.m4a"),
                    (11, "private old two", 2.0, 1.0, "11.m4a"),
                    (12, "private current", 3.0, 1.0, "12.m4a"),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        for recording_pk in (10, 11):
            (self.voice_root / f"{recording_pk}.m4a").write_bytes(
                f"private audio {recording_pk}".encode()
            )

        transcript_log.upsert_voice_memo_recording(
            12,
            label="private current",
            raw_path="12.m4a",
            duration_seconds=1.0,
        )
        row_id = transcript_log.insert_transcript(
            content_hash="already-indexed-hash",
            source="iCloud",
            transcript="already indexed",
            ingest_state="transcribed",
            quality_status="passed",
            enqueue_slack=False,
            routing_suppressed=True,
            routing_suppression_reason="historical_local_only",
        )
        self.assertTrue(
            transcript_log.link_voice_memo_transcript(
                12,
                transcript_row_id=int(row_id),
                content_hash="already-indexed-hash",
                audio_path="12.m4a",
            )
        )

    def test_backfill_processes_records_below_watermark_without_downstream_effects(
        self,
    ) -> None:
        with (
            patch.object(
                watcher,
                "transcribe_with_quality",
                return_value=TranscriptionResult(
                    "historical transcript", QualityResult(True), 1
                ),
            ),
            patch.object(watcher, "classify_and_route") as route,
        ):
            report = run_backfill(limit=None, dry_run=False)

        self.assertEqual(report["source_records"], 3)
        self.assertEqual(report["initial_unindexed_ranges"], ["10-11"])
        self.assertEqual(report["unindexed_ranges"], [])
        self.assertEqual(report["processed_count"], 2)
        self.assertEqual(report["archive_counts"]["health_error"], 0)
        self.assertEqual(report["downstream_effect_count"], 0)
        route.assert_not_called()

    def test_limit_makes_progress_and_rerun_does_not_duplicate_transcripts(self) -> None:
        with patch.object(
            watcher,
            "transcribe_with_quality",
            return_value=TranscriptionResult(
                "historical transcript", QualityResult(True), 1
            ),
        ):
            first = run_backfill(limit=1, dry_run=False)
            second = run_backfill(limit=1, dry_run=False)

        self.assertEqual(first["processed_count"], 1)
        self.assertEqual(first["unindexed_ranges"], ["11"])
        self.assertEqual(second["processed_count"], 1)
        self.assertEqual(second["unindexed_ranges"], [])
        conn = transcript_log._get_conn()
        try:
            transcript_count = conn.execute(
                "SELECT COUNT(*) FROM transcripts"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(transcript_count, 3)

    def test_dry_run_does_not_mutate_the_ledger(self) -> None:
        before = transcript_log.get_voice_memo_coverage()
        report = run_backfill(limit=None, dry_run=True)
        after = transcript_log.get_voice_memo_coverage()

        self.assertEqual(report["initial_unindexed_ranges"], ["10-11"])
        self.assertEqual(report["processed_count"], 0)
        self.assertEqual(before, after)

    def test_missing_source_remains_visible(self) -> None:
        conn = sqlite3.connect(self.source_db)
        try:
            conn.execute(
                "INSERT INTO ZCLOUDRECORDING VALUES (?, ?, ?, ?, ?)",
                (13, "private missing", 4.0, 1.0, ""),
            )
            conn.commit()
        finally:
            conn.close()

        report = run_backfill(limit=None, dry_run=False)
        self.assertNotIn("13", report["unindexed_ranges"])
        self.assertGreaterEqual(report["unlinked_count"], 1)
        conn = transcript_log._get_conn()
        try:
            row = conn.execute(
                """
                SELECT status, retryable, transcript_row_id
                FROM voice_memo_ingest
                WHERE recording_pk = 13
                """
            ).fetchone()
        finally:
            conn.close()
        self.assertIn(row["status"], {"awaiting_file", "failed"})
        self.assertEqual(row["retryable"], 1)
        self.assertIsNone(row["transcript_row_id"])

    def test_report_is_metadata_only(self) -> None:
        report = run_backfill(limit=None, dry_run=True)
        rendered = json.dumps(report, sort_keys=True)
        for private_value in (
            "private old one",
            "private old two",
            "private audio 10",
            str(self.voice_root),
        ):
            self.assertNotIn(private_value, rendered)

    def test_coverage_reads_legacy_ledger_before_suppression_migration(self) -> None:
        legacy_db = Path(self.db_dir) / "legacy.db"
        conn = sqlite3.connect(legacy_db)
        try:
            conn.executescript(
                """
                CREATE TABLE voice_memo_ingest (
                    recording_pk INTEGER PRIMARY KEY,
                    transcript_row_id INTEGER,
                    retryable INTEGER NOT NULL DEFAULT 0,
                    terminal_at TEXT
                );
                CREATE TABLE transcripts (id INTEGER PRIMARY KEY);
                INSERT INTO voice_memo_ingest
                    (recording_pk, transcript_row_id, retryable, terminal_at)
                VALUES (10, 1, 0, NULL), (11, NULL, 1, NULL),
                       (12, NULL, 0, '2026-01-01T00:00:00Z');
                INSERT INTO transcripts (id) VALUES (1);
                """
            )
            conn.commit()
        finally:
            conn.close()

        with patch.object(transcript_log, "TRANSCRIPT_DB_PATH", legacy_db):
            coverage = transcript_log.get_voice_memo_coverage()

        self.assertEqual(
            coverage,
            {
                "ledger_count": 3,
                "linked_count": 1,
                "unlinked_count": 2,
                "retryable_count": 1,
                "terminal_count": 1,
                "local_only_count": 0,
            },
        )

    def test_compact_ranges(self) -> None:
        self.assertEqual(compact_ranges([1, 2, 3, 8]), ["1-3", "8"])
        self.assertEqual(compact_ranges([]), [])

    def test_operator_documentation_describes_safe_backfill(self) -> None:
        readme = (ROOT / "README.md").read_text()

        self.assertIn("scripts/backfill_voice_memos.py", readme)
        self.assertIn("--dry-run", readme)
        self.assertRegex(
            readme,
            r"(?is)backfill_voice_memos.*?(?:does not|never).*?(?:send|deliver)",
        )


if __name__ == "__main__":
    unittest.main()
