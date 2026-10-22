from __future__ import annotations

import hashlib
import logging
import os
import shutil
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
from archive import StagedAudio  # noqa: E402
from transcript_view import (  # noqa: E402
    VIEW_INDEX_FILENAME,
    TranscriptViewError,
    publish_transcript_view,
    scan_view_root,
    split_front_matter,
    view_filename,
    write_index,
)

CAPTURED_AT = "2026-10-02T18:05:11Z"


def _row(transcript: str = "buy milk", **overrides: object) -> dict:
    row = {
        "transcript_row_id": 42,
        "transcript": transcript,
        "source": "iCloud",
        "captured_at": CAPTURED_AT,
        "ingested_at": "2026-10-02T18:06:00Z",
        "quality_status": "passed",
        "audio_sha256": "a" * 64,
        "transcription_backend": "parakeet",
        "transcription_model": "parakeet-v3",
    }
    row.update(overrides)
    return row


def _snapshot_markdown(transcript: str, transcript_id: int = 42) -> str:
    digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    header = (
        "---\n"
        "schema_version: 1\n"
        f"canonical_transcript_id: {transcript_id}\n"
        'source: "iCloud"\n'
        f'captured_at: "{CAPTURED_AT}"\n'
        f'audio_sha256: "{"a" * 64}"\n'
        f'transcript_sha256: "{digest}"\n'
        'transcription_backend: "parakeet"\n'
        'transcription_model: "parakeet-v3"\n'
        'quality_status: "passed"\n'
        "---\n"
    )
    return header + transcript


class TranscriptViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = Path(self.tmp)
        self.view_root = self.root / "Penny Transcripts"

    def test_publish_writes_stable_markdown_with_provenance(self) -> None:
        path = publish_transcript_view(_row(), self.view_root)

        self.assertEqual(
            path.name, "p00000042__2026-10-02T18-05-11Z__iCloud.md"
        )
        fields, body = split_front_matter(path.read_text(encoding="utf-8"))
        self.assertEqual(fields["canonical_transcript_id"], "42")
        self.assertEqual(fields["source"], "iCloud")
        self.assertEqual(fields["quality_status"], "passed")
        self.assertEqual(
            fields["transcript_sha256"],
            hashlib.sha256(b"buy milk").hexdigest(),
        )
        self.assertEqual(body, "buy milk")

    def test_changed_accepted_text_updates_one_file(self) -> None:
        first = publish_transcript_view(_row(), self.view_root)
        second = publish_transcript_view(_row("buy oat milk"), self.view_root)

        self.assertEqual(first, second)
        files = sorted(self.view_root.glob("*.md"))
        self.assertEqual(len(files), 1)
        _, body = split_front_matter(second.read_text(encoding="utf-8"))
        self.assertEqual(body, "buy oat milk")

    def test_existing_snapshot_file_is_reconciled_into_the_canonical_name(self) -> None:
        snapshot = self.view_root / "2026-10-02T18-05-11Z__p42__iCloud__abc123def456.md"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(_snapshot_markdown("buy milk"), encoding="utf-8")

        path = publish_transcript_view(_row(), self.view_root)

        self.assertEqual(path.name, view_filename(42, CAPTURED_AT, "iCloud"))
        self.assertFalse(snapshot.exists())
        self.assertEqual(len(list(self.view_root.glob("*.md"))), 1)
        _, body = split_front_matter(path.read_text(encoding="utf-8"))
        self.assertEqual(body, "buy milk")

    def test_duplicate_copies_of_one_transcript_collapse_to_one_file(self) -> None:
        self.view_root.mkdir(parents=True, exist_ok=True)
        (self.view_root / "copy-a.md").write_text(
            _snapshot_markdown("buy milk"), encoding="utf-8"
        )
        (self.view_root / "copy-b.md").write_text(
            _snapshot_markdown("buy milk"), encoding="utf-8"
        )

        path = publish_transcript_view(_row(), self.view_root)

        self.assertEqual(len(list(self.view_root.glob("*.md"))), 1)
        self.assertEqual(path.name, view_filename(42, CAPTURED_AT, "iCloud"))

    def test_snapshot_file_without_front_matter_is_adopted_by_its_text(self) -> None:
        self.view_root.mkdir(parents=True, exist_ok=True)
        snapshot = self.view_root / "hand-made.md"
        snapshot.write_text("buy\nmilk", encoding="utf-8")

        path = publish_transcript_view(_row(), self.view_root)

        self.assertFalse(snapshot.exists())
        self.assertEqual(len(list(self.view_root.glob("*.md"))), 1)
        self.assertEqual(path.name, view_filename(42, CAPTURED_AT, "iCloud"))
        _, body = split_front_matter(path.read_text(encoding="utf-8"))
        self.assertEqual(body, "buy milk")

    def test_unrelated_files_are_left_untouched(self) -> None:
        self.view_root.mkdir(parents=True, exist_ok=True)
        stranger = self.view_root / "notes.md"
        stranger.write_text("personal note", encoding="utf-8")

        publish_transcript_view(_row(), self.view_root)

        self.assertTrue(stranger.exists())
        self.assertEqual(stranger.read_text(encoding="utf-8"), "personal note")

    def test_index_lists_entries_and_changes_with_new_entries(self) -> None:
        entries = [
            {
                "transcript_row_id": 42,
                "captured_at": CAPTURED_AT,
                "source": "iCloud",
                "transcript_sha256": "b" * 64,
                "filename": "p00000042__2026-10-02T18-05-11Z__iCloud.md",
            }
        ]
        self.assertTrue(write_index(self.view_root, entries))
        index = self.view_root / VIEW_INDEX_FILENAME
        self.assertIn("p00000042__2026-10-02T18-05-11Z__iCloud.md", index.read_text())
        self.assertFalse(write_index(self.view_root, entries))

        entries.append(
            {
                "transcript_row_id": 43,
                "captured_at": "2026-10-03T09:00:00Z",
                "source": "iCloud",
                "transcript_sha256": "c" * 64,
                "filename": "p00000043__2026-10-03T09-00-00Z__iCloud.md",
            }
        )
        self.assertTrue(write_index(self.view_root, entries))
        self.assertIn("p00000043", index.read_text(encoding="utf-8"))

    def test_view_root_is_not_created_without_its_container(self) -> None:
        missing = self.root / "not-mounted" / "Penny Transcripts"
        with self.assertRaises(TranscriptViewError):
            publish_transcript_view(_row(), missing)
        self.assertFalse(missing.exists())

    def test_published_view_holds_markdown_only(self) -> None:
        publish_transcript_view(_row(), self.view_root)
        write_index(self.view_root, [])

        for path in self.view_root.iterdir():
            self.assertTrue(path.is_file())
            self.assertEqual(path.suffix, ".md")
            self.assertFalse(path.name.startswith("."))


class TranscriptViewLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.db_dir, ignore_errors=True)
        self.db_path = Path(self.db_dir) / "test_transcripts.db"
        patch.object(transcript_log, "TRANSCRIPT_DB_PATH", self.db_path).start()
        patch.object(transcript_log, "_MIGRATION_SOURCES", []).start()
        transcript_log.init_db()
        self.addCleanup(patch.stopall)

    def _publish_archive(self, row_id: int) -> None:
        """Publish the local-mirror trio for one canonical row."""
        staged = StagedAudio(
            Path(self.db_dir) / "object.m4a", "a" * 64, 128, ".m4a"
        )
        transcript_log.queue_archive_delivery(
            row_id, staged, {"source": "iCloud"}
        )
        conn = transcript_log._get_conn()
        try:
            delivery_id = conn.execute(
                "SELECT id FROM archive_deliveries WHERE transcript_row_id = ?",
                (row_id,),
            ).fetchone()[0]
        finally:
            conn.close()
        transcript_log.mark_archive_delivery_published(
            int(delivery_id),
            audio_path=str(staged.path),
            markdown_path=str(staged.path) + ".md",
            manifest_path=str(staged.path) + ".json",
            receipt_sha256="b" * 64,
        )

    def test_published_archive_queues_the_view_publication(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="view-accepted",
            source="iCloud",
            transcript="buy milk",
            quality_status="passed",
        )
        self.assertIsNotNone(row_id)

        self._publish_archive(int(row_id))

        pending = transcript_log.get_pending_transcript_view_publications()
        self.assertEqual([int(row["transcript_row_id"]) for row in pending], [row_id])

    def test_transcript_without_a_published_archive_is_not_queued(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="view-unarchived",
            source="iCloud",
            transcript="text only row",
            quality_status="passed",
        )
        self.assertIsNotNone(row_id)

        self.assertEqual(transcript_log.get_pending_transcript_view_publications(), [])

    def test_needs_review_transcript_is_not_queued(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="view-review",
            source="iCloud",
            transcript="unclear recording",
            quality_status="needs_review",
        )
        self.assertIsNotNone(row_id)
        self._publish_archive(int(row_id))

        self.assertEqual(transcript_log.get_pending_transcript_view_publications(), [])

    def test_migrated_placeholder_is_not_exported(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="view-placeholder",
            source="iCloud",
            transcript="(migrated — original transcript not preserved)",
            quality_status="passed",
        )
        self.assertIsNotNone(row_id)
        self._publish_archive(int(row_id))

        self.assertEqual(transcript_log.get_pending_transcript_view_publications(), [])

    def test_backlog_queues_rows_that_predate_the_view(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="view-backlog",
            source="iCloud",
            transcript="existing snapshot row",
            quality_status="passed",
        )
        self._publish_archive(int(row_id))
        conn = transcript_log._get_conn()
        try:
            conn.execute(
                "DELETE FROM transcript_view_publications WHERE transcript_row_id = ?",
                (row_id,),
            )
            conn.commit()
        finally:
            conn.close()

        queued = transcript_log.queue_transcript_view_backlog(limit=10)

        self.assertEqual(queued, 1)
        pending = transcript_log.get_pending_transcript_view_publications()
        self.assertEqual([int(row["transcript_row_id"]) for row in pending], [row_id])

    def test_publication_is_recorded_with_its_destination(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="view-published",
            source="iCloud",
            transcript="buy milk",
            quality_status="passed",
        )
        self._publish_archive(int(row_id))
        transcript_log.mark_transcript_view_published(
            row_id,
            destination_path="/tmp/Penny Transcripts/p00000001.md",
            transcript_sha256=hashlib.sha256(b"buy milk").hexdigest(),
        )

        self.assertEqual(transcript_log.get_pending_transcript_view_publications(), [])
        published = transcript_log.get_transcript_view_publications()
        self.assertEqual(len(published), 1)
        self.assertEqual(int(published[0]["transcript_row_id"]), row_id)


class TranscriptViewWatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.db_dir, ignore_errors=True)
        self.db_path = Path(self.db_dir) / "test_transcripts.db"
        patch.object(transcript_log, "TRANSCRIPT_DB_PATH", self.db_path).start()
        patch.object(transcript_log, "_MIGRATION_SOURCES", []).start()
        transcript_log.init_db()
        self.view_root = Path(self.db_dir) / "Penny Transcripts"
        self.view_root.mkdir(parents=True, exist_ok=True)
        patch.object(
            watcher.cfg,
            "transcript_view",
            type(watcher.cfg.transcript_view)(
                enabled=True,
                root=self.view_root,
                batch_limit=25,
            ),
        ).start()
        self.addCleanup(patch.stopall)

    def _publish_archive(self, row_id: int) -> None:
        """Publish the local-mirror trio for one canonical row."""
        staged = StagedAudio(
            Path(self.db_dir) / "object.m4a", "a" * 64, 128, ".m4a"
        )
        transcript_log.queue_archive_delivery(
            row_id, staged, {"source": "iCloud"}
        )
        conn = transcript_log._get_conn()
        try:
            delivery_id = conn.execute(
                "SELECT id FROM archive_deliveries WHERE transcript_row_id = ?",
                (row_id,),
            ).fetchone()[0]
        finally:
            conn.close()
        transcript_log.mark_archive_delivery_published(
            int(delivery_id),
            audio_path=str(staged.path),
            markdown_path=str(staged.path) + ".md",
            manifest_path=str(staged.path) + ".json",
            receipt_sha256="b" * 64,
        )

    def test_watcher_uses_the_configured_view_root(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="watcher-view-config",
            source="iCloud",
            transcript="configured root",
            quality_status="passed",
            recorded_at="2026-10-06T07:08:09Z",
        )
        self.assertIsNotNone(row_id)
        self._publish_archive(int(row_id))

        import config

        previous = config._config
        config._config = None
        try:
            with patch.dict(
                os.environ,
                {
                    "PENNY_TRANSCRIPT_VIEW_ROOT": str(self.view_root),
                    "PENNY_TRANSCRIPT_VIEW_ENABLED": "true",
                },
            ):
                loaded = config.get_config()
                self.assertEqual(loaded.transcript_view.root, self.view_root)
                self.assertTrue(loaded.transcript_view.enabled)
                patch.object(watcher, "cfg", loaded).start()
                watcher._process_transcript_view_outbox()
        finally:
            config._config = previous

        files = [
            path
            for path in self.view_root.iterdir()
            if path.suffix == ".md" and path.name != VIEW_INDEX_FILENAME
        ]
        self.assertEqual(len(files), 1)
        _, body = split_front_matter(files[0].read_text(encoding="utf-8"))
        self.assertEqual(body, "configured root")

    def test_new_accepted_transcript_appears_as_markdown_with_index(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="watcher-view",
            source="iCloud",
            transcript="the quick brown fox",
            quality_status="passed",
            recorded_at="2026-10-04T07:08:09Z",
        )
        self.assertIsNotNone(row_id)
        self._publish_archive(int(row_id))

        watcher._process_transcript_view_outbox()

        files = sorted(
            path for path in self.view_root.iterdir() if path.suffix == ".md"
        )
        transcript_files = [
            path for path in files if path.name != VIEW_INDEX_FILENAME
        ]
        self.assertEqual(len(transcript_files), 1)
        _, body = split_front_matter(transcript_files[0].read_text(encoding="utf-8"))
        self.assertEqual(body, "the quick brown fox")
        index = (self.view_root / VIEW_INDEX_FILENAME).read_text(encoding="utf-8")
        self.assertIn(transcript_files[0].name, index)

    def test_repeated_passes_keep_one_file_and_the_transcript_digest(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="watcher-view-repeat",
            source="iCloud",
            transcript="the quick brown fox",
            quality_status="passed",
            recorded_at="2026-10-04T07:08:09Z",
        )
        self.assertIsNotNone(row_id)
        self._publish_archive(int(row_id))

        watcher._process_transcript_view_outbox()
        published = transcript_log.get_transcript_view_publications()
        self.assertEqual(len(published), 1)
        self.assertEqual(
            str(published[0]["transcript_sha256"]),
            hashlib.sha256(b"the quick brown fox").hexdigest(),
        )
        files = [
            path
            for path in self.view_root.iterdir()
            if path.suffix == ".md" and path.name != VIEW_INDEX_FILENAME
        ]
        self.assertEqual(len(files), 1)
        first_bytes = files[0].read_bytes()

        watcher._process_transcript_view_outbox()

        files = [
            path
            for path in self.view_root.iterdir()
            if path.suffix == ".md" and path.name != VIEW_INDEX_FILENAME
        ]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), first_bytes)
        self.assertEqual(
            transcript_log.get_pending_transcript_view_publications(), []
        )

    def test_failed_publication_is_retried_by_a_later_pass(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="watcher-view-retry",
            source="iCloud",
            transcript="retry me",
            quality_status="passed",
            recorded_at="2026-10-05T07:08:09Z",
        )
        self.assertIsNotNone(row_id)
        self._publish_archive(int(row_id))
        conn = transcript_log._get_conn()
        try:
            conn.execute(
                "UPDATE transcript_view_publications SET status = 'failed', "
                "attempt_count = 5 WHERE transcript_row_id = ?",
                (row_id,),
            )
            conn.commit()
        finally:
            conn.close()

        watcher._process_transcript_view_outbox()

        published = transcript_log.get_transcript_view_publications()
        self.assertEqual(len(published), 1)
        self.assertEqual(int(published[0]["transcript_row_id"]), row_id)

    def test_publication_failure_is_recorded_without_publishing(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="watcher-view-failure",
            source="iCloud",
            transcript="never published",
            quality_status="passed",
        )
        self.assertIsNotNone(row_id)
        self._publish_archive(int(row_id))
        patch.object(
            watcher,
            "publish_transcript_view",
            side_effect=OSError("view unavailable"),
        ).start()

        watcher._process_transcript_view_outbox()

        published = transcript_log.get_transcript_view_publications()
        self.assertEqual(published, [])
        pending = transcript_log.get_pending_transcript_view_publications()
        self.assertEqual(len(pending), 1)
