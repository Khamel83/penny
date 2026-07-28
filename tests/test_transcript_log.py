from __future__ import annotations

import importlib
import hashlib
import logging
import multiprocessing
import os
import sqlite3
import sys
import tempfile
import threading
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


def _init_db_in_process(
    db_path: str,
    start_barrier: object,
    result_queue: object,
) -> None:
    transcript_log.TRANSCRIPT_DB_PATH = Path(db_path)
    try:
        start_barrier.wait()
        transcript_log.init_db()
    except Exception as exc:
        result_queue.put(f"{type(exc).__name__}: {exc}")
    else:
        result_queue.put(None)


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

    def test_icloud_transcript_ignores_mismatched_slack_channel_environment(
        self,
    ) -> None:
        with patch.dict(
            os.environ,
            {
                "PENNY_SLACK_CHANNEL_ID": "C-MALICIOUS",
                "SLACK_CHANNEL_ID": "C-UNRELATED",
            },
        ):
            row_id = transcript_log.insert_transcript(
                content_hash="slack-pinned-channel",
                source="iCloud",
                transcript="must only reach Penny",
            )

        pending = transcript_log.get_pending_slack_deliveries(transcript_id=row_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["channel_id"], "C0BKS0QT7FU")

    def test_canonical_migration_adds_safe_columns_without_replacing_legacy_rows(
        self,
    ) -> None:
        self.db_path.unlink()
        legacy_transcript = "Legacy transcript remains readable."
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                """
                CREATE TABLE transcripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_hash TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    transcript TEXT NOT NULL,
                    audio_path TEXT,
                    duration_seconds REAL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    ingest_state TEXT,
                    routing_result TEXT,
                    routing_progress TEXT,
                    error_message TEXT,
                    discovered_at TEXT,
                    file_seen_at TEXT,
                    transcription_started_at TEXT,
                    transcription_completed_at TEXT,
                    routing_started_at TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    last_error_at TEXT,
                    routed_at TEXT,
                    routed_to TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO transcripts (
                    content_hash, source, transcript, ingest_state, discovered_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "legacy-content-hash",
                    "iCloud",
                    legacy_transcript,
                    "transcribed",
                    "2026-07-28T12:00:00Z",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        transcript_log.init_db()

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(transcripts)")
            }
            row = dict(
                conn.execute(
                    """
                    SELECT content_hash, transcript, quality_status, quality_detail,
                           transcript_sha256, maya_delivery_status, maya_drop_id,
                           superseded_by_transcript_row_id
                    FROM transcripts
                    WHERE content_hash = ?
                    """,
                    ("legacy-content-hash",),
                ).fetchone()
            )
        finally:
            conn.close()

        self.assertTrue(
            {
                "quality_status",
                "quality_detail",
                "transcript_sha256",
                "maya_delivery_status",
                "maya_drop_id",
                "maya_delivery_attempt_count",
                "maya_next_attempt_at",
                "superseded_by_transcript_row_id",
            }.issubset(columns)
        )
        self.assertEqual(row["content_hash"], "legacy-content-hash")
        self.assertEqual(row["transcript"], legacy_transcript)
        self.assertEqual(row["quality_status"], "passed")
        self.assertIsNone(row["quality_detail"])
        self.assertEqual(
            row["transcript_sha256"],
            hashlib.sha256(legacy_transcript.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(row["maya_delivery_status"], "pending")
        self.assertIsNone(row["maya_drop_id"])
        self.assertIsNone(row["superseded_by_transcript_row_id"])

    def test_canonical_insert_uses_exact_utf8_hash_and_queues_only_passed_quality(
        self,
    ) -> None:
        passed_text = "Caf\u00e9 notes stay byte-exact."
        passed_row_id = transcript_log.insert_transcript(
            content_hash="canonical-passed-audio-hash",
            source="iCloud",
            transcript=passed_text,
            quality_status="passed",
        )
        review_row_id = transcript_log.insert_transcript(
            content_hash="canonical-review-audio-hash",
            source="iCloud",
            transcript="This requires human review.",
            ingest_state="needs_review",
            quality_status="needs_review",
            quality_detail="control_token",
        )

        self.assertIsNotNone(passed_row_id)
        self.assertIsNotNone(review_row_id)
        passed = transcript_log.get_transcript(int(passed_row_id))
        review = transcript_log.get_transcript(int(review_row_id))
        self.assertEqual(
            passed["transcript_sha256"],
            hashlib.sha256(passed_text.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(passed["quality_status"], "passed")
        self.assertIsNone(passed["quality_detail"])
        self.assertEqual(review["quality_status"], "needs_review")
        self.assertEqual(review["quality_detail"], "control_token")
        self.assertEqual(
            [delivery["transcript_row_id"] for delivery in transcript_log.get_pending_slack_deliveries()],
            [passed_row_id],
        )

    def test_maya_delivery_receipts_and_failures_persist_independent_state(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="maya-delivery-state-audio-hash",
            source="iCloud",
            transcript="Persist delivery acknowledgement state.",
            quality_status="passed",
        )
        self.assertIsNotNone(row_id)

        transcript_log.mark_maya_delivery_failed(
            int(row_id),
            "raw provider response must not be persisted",
        )
        failed = transcript_log.get_transcript(int(row_id))
        self.assertEqual(failed["maya_delivery_status"], "failed")
        self.assertEqual(failed["maya_delivery_error"], "delivery_error")
        self.assertIsNone(failed["maya_drop_id"])

        transcript_log.mark_maya_delivery_sent(int(row_id), "drop-penny-v2-123")
        transcript_log.mark_maya_delivery_sent(int(row_id), "drop-penny-v2-123")
        sent = transcript_log.get_transcript(int(row_id))
        self.assertEqual(sent["maya_delivery_status"], "sent")
        self.assertEqual(sent["maya_drop_id"], "drop-penny-v2-123")
        self.assertIsNone(sent["maya_delivery_error"])

    def test_pending_slack_delivery_excludes_row_that_later_fails_quality(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="slack-quality-dequeue-hash",
            source="iCloud",
            transcript="Do not publish a body that later fails quality.",
            quality_status="passed",
        )
        self.assertIsNotNone(row_id)

        conn = transcript_log._get_conn()
        try:
            conn.execute(
                "UPDATE transcripts SET quality_status = 'needs_review' WHERE id = ?",
                (row_id,),
            )
            conn.commit()
        finally:
            conn.close()

        self.assertEqual(transcript_log.get_pending_slack_deliveries(), [])

    def test_concurrent_conflicting_maya_receipts_preserve_one_drop_id(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="maya-conflicting-receipt-hash",
            source="iCloud",
            transcript="Only one durable Maya receipt may win.",
            quality_status="passed",
            enqueue_slack=False,
        )
        self.assertIsNotNone(row_id)
        select_gate = threading.Barrier(2)
        real_get_conn = transcript_log._get_conn

        class GateInitialReceiptRead:
            def __init__(self, connection: sqlite3.Connection) -> None:
                self.connection = connection

            def execute(self, sql: str, parameters: object = ()) -> object:
                if sql.strip() == "SELECT maya_drop_id FROM transcripts WHERE id = ?":
                    try:
                        select_gate.wait(timeout=0.2)
                    except threading.BrokenBarrierError:
                        pass
                return self.connection.execute(sql, parameters)

            def __getattr__(self, name: str) -> object:
                return getattr(self.connection, name)

        outcomes: list[object] = []
        outcomes_lock = threading.Lock()

        def acknowledge(drop_id: str) -> None:
            try:
                transcript_log.mark_maya_delivery_sent(int(row_id), drop_id)
            except Exception as exc:
                outcome: object = exc
            else:
                outcome = drop_id
            with outcomes_lock:
                outcomes.append(outcome)

        with patch.object(
            transcript_log,
            "_get_conn",
            side_effect=lambda: GateInitialReceiptRead(real_get_conn()),
        ):
            first = threading.Thread(target=acknowledge, args=("drop-race-a",))
            second = threading.Thread(target=acknowledge, args=("drop-race-b",))
            first.start()
            second.start()
            first.join(timeout=5)
            second.join(timeout=5)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(len([outcome for outcome in outcomes if isinstance(outcome, str)]), 1)
        self.assertEqual(len([outcome for outcome in outcomes if isinstance(outcome, ValueError)]), 1)
        stored = transcript_log.get_transcript(int(row_id))
        self.assertEqual(stored["maya_delivery_status"], "sent")
        self.assertIn(stored["maya_drop_id"], {"drop-race-a", "drop-race-b"})

    def test_maya_delivery_failure_does_not_overwrite_sent_receipt(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="maya-sent-monotonic-hash",
            source="iCloud",
            transcript="A durable acknowledgement is terminal.",
            quality_status="passed",
            enqueue_slack=False,
        )
        self.assertIsNotNone(row_id)
        transcript_log.mark_maya_delivery_sent(int(row_id), "drop-terminal")

        transcript_log.mark_maya_delivery_failed(int(row_id), "delivery_error")

        stored = transcript_log.get_transcript(int(row_id))
        self.assertEqual(stored["maya_delivery_status"], "sent")
        self.assertEqual(stored["maya_drop_id"], "drop-terminal")
        self.assertIsNone(stored["maya_delivery_error"])

    def test_canonical_processed_file_migration_persists_exact_utf8_hash(self) -> None:
        processed_file = Path(self.db_dir) / "legacy_processed.txt"
        processed_file.write_text("legacy-processed-hash\n", encoding="utf-8")

        with patch.object(
            transcript_log,
            "_MIGRATION_SOURCES",
            [(processed_file, "iCloud")],
        ):
            conn = transcript_log._get_conn()
            try:
                migrated = transcript_log._migrate_processed_files(conn)
                conn.commit()
            finally:
                conn.close()

        self.assertEqual(migrated, 1)
        conn = transcript_log._get_conn()
        try:
            stored_sha256 = conn.execute(
                "SELECT transcript_sha256 FROM transcripts WHERE content_hash = ?",
                ("legacy-processed-hash",),
            ).fetchone()["transcript_sha256"]
        finally:
            conn.close()
        self.assertEqual(
            stored_sha256,
            hashlib.sha256(
                "(migrated \u2014 original transcript not preserved)".encode("utf-8")
            ).hexdigest(),
        )

    def test_init_db_migrates_retryable_legacy_failures_and_wrong_destinations(
        self,
    ) -> None:
        retryable_row_id = transcript_log.insert_transcript(
            content_hash="legacy-retryable-row",
            source="iCloud",
            transcript="retryable legacy body",
            enqueue_slack=False,
        )
        terminal_row_id = transcript_log.insert_transcript(
            content_hash="legacy-terminal-row",
            source="iCloud",
            transcript="terminal legacy body",
            enqueue_slack=False,
        )
        self.assertIsNotNone(retryable_row_id)
        self.assertIsNotNone(terminal_row_id)

        conn = transcript_log._get_conn()
        try:
            conn.execute("DROP TABLE slack_deliveries")
            conn.execute(
                """
                CREATE TABLE slack_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transcript_row_id INTEGER NOT NULL UNIQUE,
                    channel_id TEXT NOT NULL,
                    message_text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    sent_at TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO slack_deliveries (
                    transcript_row_id, channel_id, message_text, status,
                    attempt_count, last_error
                ) VALUES
                    (?, 'C-WRONG-RETRY', 'retryable legacy body', 'failed', 2, 'ratelimited'),
                    (?, 'C-WRONG-TERMINAL', 'terminal legacy body', 'failed', 5, 'invalid_auth')
                """,
                (retryable_row_id, terminal_row_id),
            )
            conn.commit()
        finally:
            conn.close()

        transcript_log.init_db()

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(slack_deliveries)").fetchall()
            }
            rows = conn.execute(
                """
                SELECT transcript_row_id, channel_id, status, attempt_count,
                       next_attempt_at, provider_ts
                FROM slack_deliveries
                ORDER BY transcript_row_id
                """
            ).fetchall()
        finally:
            conn.close()

        self.assertIn("next_attempt_at", columns)
        self.assertIn("provider_ts", columns)
        retryable, terminal = [dict(row) for row in rows]
        self.assertEqual(retryable["channel_id"], "C0BKS0QT7FU")
        self.assertEqual(retryable["status"], "pending")
        self.assertEqual(retryable["attempt_count"], 2)
        self.assertIsNotNone(retryable["next_attempt_at"])
        self.assertIsNone(retryable["provider_ts"])
        self.assertEqual(terminal["channel_id"], "C0BKS0QT7FU")
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(terminal["attempt_count"], 5)
        self.assertIsNone(terminal["next_attempt_at"])
        due = transcript_log.get_pending_slack_deliveries(
            transcript_id=retryable_row_id
        )
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["message_text"], "retryable legacy body")

    def test_init_db_migrates_legacy_transcript_id_to_transcript_row_id(self) -> None:
        first_row_id = transcript_log.insert_transcript(
            content_hash="legacy-slack-schema-1",
            source="iCloud",
            transcript="legacy body one",
            enqueue_slack=False,
        )
        second_row_id = transcript_log.insert_transcript(
            content_hash="legacy-slack-schema-2",
            source="iCloud",
            transcript="legacy body two",
            enqueue_slack=False,
        )
        self.assertIsNotNone(first_row_id)
        self.assertIsNotNone(second_row_id)

        conn = transcript_log._get_conn()
        try:
            conn.execute("DROP TABLE slack_deliveries")
            conn.execute(
                """
                CREATE TABLE slack_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transcript_id INTEGER NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT,
                    last_error TEXT,
                    provider_ts TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    sent_at TEXT,
                    FOREIGN KEY(transcript_id) REFERENCES transcripts(id)
                )
                """
            )
            conn.executemany(
                """
                INSERT INTO slack_deliveries (
                    transcript_id
                ) VALUES (?)
                """,
                [
                    (first_row_id,),
                    (second_row_id,),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        transcript_log.init_db()
        transcript_log.init_db()
        transcript_log.queue_slack_delivery(int(first_row_id))

        conn = sqlite3.connect(str(self.db_path))
        try:
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(slack_deliveries)").fetchall()
            }
            rows = conn.execute(
                """
                SELECT transcript_row_id, message_text
                FROM slack_deliveries
                ORDER BY transcript_row_id
                """
            ).fetchall()
            foreign_key = conn.execute(
                "PRAGMA foreign_key_list(slack_deliveries)"
            ).fetchone()
            row_count = conn.execute("SELECT COUNT(*) FROM slack_deliveries").fetchone()[0]
        finally:
            conn.close()

        self.assertIn("transcript_row_id", columns)
        self.assertNotIn("transcript_id", columns)
        self.assertEqual(
            (foreign_key[2], foreign_key[3], foreign_key[4]),
            ("transcripts", "transcript_row_id", "id"),
        )
        self.assertEqual(
            rows,
            [
                (first_row_id, "legacy body one"),
                (second_row_id, "legacy body two"),
            ],
        )
        self.assertEqual(row_count, 2)
        pending = transcript_log.get_pending_slack_deliveries(transcript_id=first_row_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["transcript_row_id"], first_row_id)
        self.assertEqual(pending[0]["message_text"], "legacy body one")

    def test_init_db_rolls_back_legacy_migration_and_retries(self) -> None:
        transcript_row_id = transcript_log.insert_transcript(
            content_hash="legacy-slack-schema-retry",
            source="iCloud",
            transcript="retry after migration failure",
            enqueue_slack=False,
        )
        self.assertIsNotNone(transcript_row_id)

        conn = transcript_log._get_conn()
        try:
            conn.execute("DROP TABLE slack_deliveries")
            conn.execute(
                """
                CREATE TABLE slack_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transcript_id INTEGER NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                "INSERT INTO slack_deliveries (transcript_id) VALUES (?)",
                (transcript_row_id,),
            )
            conn.commit()
        finally:
            conn.close()

        with patch.object(
            transcript_log,
            "_migrate_slack_delivery_rows",
            side_effect=sqlite3.OperationalError("injected migration failure"),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                transcript_log.init_db()

        conn = sqlite3.connect(str(self.db_path))
        try:
            columns_after_failure = {
                row[1]
                for row in conn.execute("PRAGMA table_info(slack_deliveries)").fetchall()
            }
        finally:
            conn.close()

        self.assertIn("transcript_id", columns_after_failure)
        self.assertNotIn("transcript_row_id", columns_after_failure)

        transcript_log.init_db()
        conn = sqlite3.connect(str(self.db_path))
        try:
            columns_after_retry = {
                row[1]
                for row in conn.execute("PRAGMA table_info(slack_deliveries)").fetchall()
            }
            row = conn.execute(
                "SELECT transcript_row_id, message_text FROM slack_deliveries"
            ).fetchone()
        finally:
            conn.close()

        self.assertIn("transcript_row_id", columns_after_retry)
        self.assertNotIn("transcript_id", columns_after_retry)
        self.assertEqual(row, (transcript_row_id, "retry after migration failure"))

    def test_init_db_rejects_orphan_legacy_delivery_without_partial_migration(self) -> None:
        conn = transcript_log._get_conn()
        try:
            conn.execute("DROP TABLE slack_deliveries")
            conn.execute(
                """
                CREATE TABLE slack_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transcript_id INTEGER NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY(transcript_id) REFERENCES transcripts(id)
                )
                """
            )
            conn.execute("INSERT INTO slack_deliveries (transcript_id) VALUES (999999)")
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(sqlite3.IntegrityError):
            transcript_log.init_db()

        conn = sqlite3.connect(str(self.db_path))
        try:
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(slack_deliveries)").fetchall()
            }
            row = conn.execute(
                "SELECT transcript_id FROM slack_deliveries"
            ).fetchone()
        finally:
            conn.close()

        self.assertIn("transcript_id", columns)
        self.assertNotIn("transcript_row_id", columns)
        self.assertEqual(row, (999999,))

    def test_add_column_if_missing_returns_false_when_concurrent_alter_wins(
        self,
    ) -> None:
        before_alter = Mock()
        before_alter.fetchall.return_value = []
        after_alter = Mock()
        after_alter.fetchall.return_value = [(0, "chunk_attempt_count")]
        conn = Mock()
        conn.execute.side_effect = [
            before_alter,
            sqlite3.OperationalError("Spalte wurde gleichzeitig hinzugefügt"),
            after_alter,
        ]

        added = transcript_log._add_column_if_missing(
            conn,
            table="slack_deliveries",
            column="chunk_attempt_count",
            sql=(
                "ALTER TABLE slack_deliveries "
                "ADD COLUMN chunk_attempt_count INTEGER NOT NULL DEFAULT 0"
            ),
        )

        self.assertFalse(added)

    def test_add_column_if_missing_reraises_unrelated_operational_error(
        self,
    ) -> None:
        before_alter = Mock()
        before_alter.fetchall.return_value = []
        after_alter = Mock()
        after_alter.fetchall.return_value = []
        original_error = sqlite3.OperationalError("database disk image is malformed")
        conn = Mock()
        conn.execute.side_effect = [before_alter, original_error, after_alter]

        with self.assertRaises(sqlite3.OperationalError) as raised:
            transcript_log._add_column_if_missing(
                conn,
                table="slack_deliveries",
                column="chunk_attempt_count",
                sql=(
                    "ALTER TABLE slack_deliveries "
                    "ADD COLUMN chunk_attempt_count INTEGER NOT NULL DEFAULT 0"
                ),
            )

        self.assertIs(raised.exception, original_error)
        self.assertEqual(conn.execute.call_count, 3)

    def test_add_column_if_missing_preserves_error_when_schema_reread_fails(
        self,
    ) -> None:
        before_alter = Mock()
        before_alter.fetchall.return_value = []
        original_error = sqlite3.OperationalError("database is locked")
        reread_error = sqlite3.OperationalError("schema unavailable")
        conn = Mock()
        conn.execute.side_effect = [before_alter, original_error, reread_error]

        with self.assertRaises(sqlite3.OperationalError) as raised:
            transcript_log._add_column_if_missing(
                conn,
                table="slack_deliveries",
                column="chunk_attempt_count",
                sql=(
                    "ALTER TABLE slack_deliveries "
                    "ADD COLUMN chunk_attempt_count INTEGER NOT NULL DEFAULT 0"
                ),
            )

        self.assertIs(raised.exception, original_error)

    def test_init_db_rejects_non_unique_transcript_identity_index(self) -> None:
        conn = transcript_log._get_conn()
        try:
            conn.execute("DROP INDEX idx_slack_deliveries_transcript_row_id")
            conn.execute(
                "CREATE INDEX idx_slack_deliveries_transcript_row_id "
                "ON slack_deliveries(message_text)"
            )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(sqlite3.IntegrityError):
            transcript_log.init_db()

        conn = sqlite3.connect(str(self.db_path))
        try:
            index = conn.execute(
                """
                SELECT name, "unique"
                FROM pragma_index_list('slack_deliveries')
                WHERE name = 'idx_slack_deliveries_transcript_row_id'
                """
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(index, ("idx_slack_deliveries_transcript_row_id", 0))

    def test_concurrent_init_db_migrates_slack_schema_without_errors(self) -> None:
        conn = transcript_log._get_conn()
        try:
            conn.execute("DROP TABLE slack_deliveries")
            conn.execute(
                """
                CREATE TABLE slack_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transcript_row_id INTEGER NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

        process_count = 4
        context = multiprocessing.get_context("spawn")
        start_barrier = context.Barrier(process_count)
        result_queue = context.Queue()
        processes = [
            context.Process(
                target=_init_db_in_process,
                args=(str(self.db_path), start_barrier, result_queue),
            )
            for _ in range(process_count)
        ]

        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=15)
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            process.join()

        self.assertEqual([process.exitcode for process in processes], [0] * process_count)
        errors = [
            result
            for result in (result_queue.get() for _ in range(process_count))
            if result is not None
        ]
        self.assertEqual(errors, [])

        conn = sqlite3.connect(str(self.db_path))
        try:
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(slack_deliveries)").fetchall()
            }
        finally:
            conn.close()

        self.assertTrue(
            {
                "id",
                "transcript_row_id",
                "channel_id",
                "message_text",
                "status",
                "attempt_count",
                "next_attempt_at",
                "last_error",
                "provider_ts",
                "next_chunk_index",
                "chunk_attempt_count",
                "chunk_provider_ts",
                "created_at",
                "updated_at",
                "sent_at",
            }.issubset(columns)
        )

    def test_concurrent_init_db_migrates_legacy_transcript_id_schema(self) -> None:
        transcript_row_id = transcript_log.insert_transcript(
            content_hash="concurrent-legacy-slack-schema",
            source="iCloud",
            transcript="concurrent legacy body",
            enqueue_slack=False,
        )
        self.assertIsNotNone(transcript_row_id)

        conn = transcript_log._get_conn()
        try:
            conn.execute("DROP TABLE slack_deliveries")
            conn.execute(
                """
                CREATE TABLE slack_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transcript_id INTEGER NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT,
                    last_error TEXT,
                    provider_ts TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    sent_at TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO slack_deliveries (transcript_id) VALUES (?)",
                (transcript_row_id,),
            )
            conn.commit()
        finally:
            conn.close()

        process_count = 4
        context = multiprocessing.get_context("spawn")
        start_barrier = context.Barrier(process_count)
        result_queue = context.Queue()
        processes = [
            context.Process(
                target=_init_db_in_process,
                args=(str(self.db_path), start_barrier, result_queue),
            )
            for _ in range(process_count)
        ]

        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=15)
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            process.join()

        self.assertEqual([process.exitcode for process in processes], [0] * process_count)
        errors = [
            result
            for result in (result_queue.get() for _ in range(process_count))
            if result is not None
        ]
        self.assertEqual(errors, [])

        conn = sqlite3.connect(str(self.db_path))
        try:
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(slack_deliveries)").fetchall()
            }
            row = conn.execute(
                """
                SELECT transcript_row_id, message_text
                FROM slack_deliveries
                """
            ).fetchone()
            row_count = conn.execute("SELECT COUNT(*) FROM slack_deliveries").fetchone()[0]
        finally:
            conn.close()

        self.assertIn("transcript_row_id", columns)
        self.assertNotIn("transcript_id", columns)
        self.assertEqual(row, (transcript_row_id, "concurrent legacy body"))
        self.assertEqual(row_count, 1)

        transcript_log.queue_slack_delivery(int(transcript_row_id))
        conn = sqlite3.connect(str(self.db_path))
        try:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM slack_deliveries").fetchone()[0],
                1,
            )
        finally:
            conn.close()

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

    def test_slack_delivery_health_surfaces_database_failure(self) -> None:
        with patch.object(
            transcript_log,
            "_get_conn",
            side_effect=sqlite3.OperationalError("database unavailable"),
        ):
            health = transcript_log.get_slack_delivery_health()

        self.assertEqual(health["pending_count"], 0)
        self.assertEqual(health["sent_count"], 0)
        self.assertEqual(health["failed_count"], 0)
        self.assertEqual(health["health_error"], 1)

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
