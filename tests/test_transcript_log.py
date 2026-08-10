from __future__ import annotations

import importlib
import hashlib
import inspect
import json
import logging
import multiprocessing
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
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
from archive import StagedAudio  # noqa: E402


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
        patch.object(
            transcript_log,
            "LEGACY_VOICE_MEMO_CURSOR_PATH",
            Path(self.db_dir) / "legacy_last_pk.txt",
        ).start()
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

    def test_apple_effect_schema_migrates_partial_table_and_preserves_row(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="apple-effect-migration",
            source="test",
            transcript="migration fixture",
        )
        conn = transcript_log._get_conn()
        try:
            conn.execute("DROP TABLE apple_effects")
            conn.execute(
                """CREATE TABLE apple_effects (
                    effect_key TEXT PRIMARY KEY,
                    transcript_id INTEGER NOT NULL,
                    effect_type TEXT NOT NULL,
                    requested_target TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'reserved',
                    provider_id TEXT
                )"""
            )
            conn.execute(
                """INSERT INTO apple_effects (
                    effect_key, transcript_id, effect_type,
                    requested_target, payload_sha256, state, provider_id
                ) VALUES (?, ?, 'note', 'Penny', ?, 'succeeded', 'legacy-id')""",
                ("legacy-effect", row_id, "a" * 64),
            )
            conn.commit()
        finally:
            conn.close()

        transcript_log.init_db()
        conn = transcript_log._get_conn()
        try:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(apple_effects)")
            }
            preserved = conn.execute(
                "SELECT provider_id, state FROM apple_effects WHERE effect_key = ?",
                ("legacy-effect",),
            ).fetchone()
        finally:
            conn.close()
        self.assertIn("actual_target", columns)
        self.assertIn("lease_expires_at", columns)
        self.assertEqual(dict(preserved), {"provider_id": "legacy-id", "state": "succeeded"})

    def test_apple_effect_success_receipt_is_monotonic_and_conflicts_are_isolated(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="apple-effect-monotonic", source="test", transcript="body"
        )
        kwargs = dict(
            effect_key="e" * 64,
            transcript_id=int(row_id),
            effect_type="note",
            requested_target="Penny",
            fallback_target="",
            payload_sha256="a" * 64,
        )
        claim = transcript_log.claim_apple_effect(**kwargs)
        self.assertTrue(claim["claimable"])
        self.assertTrue(
            transcript_log.mark_apple_effect_succeeded(
                kwargs["effect_key"], "provider-one", "Penny",
                lease_owner=claim["lease_owner"],
            )
        )
        self.assertFalse(
            transcript_log.mark_apple_effect_succeeded(
                kwargs["effect_key"], "provider-two", "Penny"
            )
        )
        preserved = transcript_log.get_apple_effect(kwargs["effect_key"])
        self.assertEqual(preserved["state"], "succeeded")
        self.assertEqual(preserved["provider_id"], "provider-one")

        other = {**kwargs, "effect_key": "f" * 64, "effect_type": "reminder"}
        other_claim = transcript_log.claim_apple_effect(**other)
        self.assertTrue(other_claim["claimable"])
        self.assertTrue(
            transcript_log.mark_apple_effect_succeeded(
                other["effect_key"], "provider-one", "Inbox",
                lease_owner=other_claim["lease_owner"],
            )
        )
        # Provider IDs are scoped by effect type; a coincidental Notes ID and
        # Reminders ID are not a cross-provider collision.
        self.assertEqual(
            transcript_log.get_apple_effect(other["effect_key"])["state"],
            "succeeded",
        )
        conflict = {**kwargs, "effect_key": "9" * 64}
        conflict_claim = transcript_log.claim_apple_effect(**conflict)
        self.assertTrue(conflict_claim["claimable"])
        self.assertFalse(
            transcript_log.mark_apple_effect_succeeded(
                conflict["effect_key"], "provider-one", "Penny",
                lease_owner=conflict_claim["lease_owner"],
            )
        )
        self.assertEqual(
            transcript_log.get_apple_effect(conflict["effect_key"])["state"],
            "quarantined",
        )
        self.assertFalse(transcript_log.claim_apple_effect(**conflict)["claimable"])

    def test_apple_effect_health_parses_iso_z_stale_lease(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="apple-effect-health", source="test", transcript="body"
        )
        claim = transcript_log.claim_apple_effect(
            effect_key="b" * 64,
            transcript_id=int(row_id),
            effect_type="note",
            requested_target="Penny",
            payload_sha256="b" * 64,
            lease_seconds=1,
        )
        conn = transcript_log._get_conn()
        try:
            conn.execute(
                "UPDATE apple_effects SET lease_expires_at=? WHERE effect_key=?",
                ("2020-01-01T00:00:00Z", "b" * 64),
            )
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(transcript_log.get_apple_effect_health()["stale_in_flight_count"], 1)

    def test_apple_effect_timestamps_are_utc_iso_z_and_ownership_is_required(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="apple-effect-owner", source="test", transcript="body"
        )
        key = "c" * 64
        claim = transcript_log.claim_apple_effect(
            effect_key=key,
            transcript_id=int(row_id),
            effect_type="note",
            requested_target="Penny",
            payload_sha256="c" * 64,
            now="2026-08-10T10:00:00Z",
        )
        self.assertTrue(claim["claimable"])
        denied = transcript_log.mark_apple_effect_succeeded(key, "note-id")
        wrong = transcript_log.mark_apple_effect_succeeded(
            key, "note-id", lease_owner="wrong-owner"
        )
        self.assertFalse(denied)
        self.assertFalse(wrong)
        self.assertTrue(
            transcript_log.mark_apple_effect_succeeded(
                key, "note-id", lease_owner=claim["lease_owner"]
            )
        )
        row = transcript_log.get_apple_effect(key)
        for field in ("created_at", "updated_at", "succeeded_at"):
            self.assertRegex(row[field], r"^\d{4}-\d\d-\d\dT.*Z$")
        self.assertIsNone(row["lease_expires_at"])

        key2 = "d" * 64
        claim2 = transcript_log.claim_apple_effect(
            effect_key=key2,
            transcript_id=int(row_id),
            effect_type="note",
            requested_target="Penny",
            payload_sha256="d" * 64,
        )
        self.assertFalse(
            transcript_log.mark_apple_effect_uncertain(
                key2, lease_owner="wrong-owner"
            )
        )
        self.assertFalse(
            transcript_log.mark_apple_effect_failed(
                key2, lease_owner="wrong-owner"
            )
        )
        self.assertEqual(transcript_log.get_apple_effect(key2)["state"], "in_flight")

    def test_apple_effect_failure_codes_are_allowlisted_and_timestamps_are_iso_z(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="apple-effect-safe-code", source="test", transcript="body"
        )
        cases = (
            ("2" * 64, "uncertain"),
            ("3" * 64, "failed"),
            ("4" * 64, "quarantined"),
        )
        for key, expected_state in cases:
            claim = transcript_log.claim_apple_effect(
                effect_key=key,
                transcript_id=int(row_id),
                effect_type="note",
                requested_target="Penny",
                payload_sha256=key,
            )
            if expected_state == "uncertain":
                changed = transcript_log.mark_apple_effect_uncertain(
                    key, "secret", lease_owner=claim["lease_owner"]
                )
            else:
                changed = transcript_log.mark_apple_effect_failed(
                    key,
                    "secret",
                    quarantine=expected_state == "quarantined",
                    lease_owner=claim["lease_owner"],
                )
            self.assertTrue(changed)
            stored = transcript_log.get_apple_effect(key)
            self.assertEqual(stored["state"], expected_state)
            self.assertEqual(stored["last_error_code"], "provider_error")
            self.assertRegex(stored["updated_at"], r"^\d{4}-\d\d-\d\dT.*Z$")

    def test_effect_key_mismatch_quarantines_stale_but_not_active_foreign_claim(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="apple-effect-dimension-conflict",
            source="test",
            transcript="body",
        )
        key = "5" * 64
        initial = transcript_log.claim_apple_effect(
            effect_key=key,
            transcript_id=int(row_id),
            effect_type="note",
            requested_target="Penny",
            payload_sha256=key,
        )
        active_conflict = transcript_log.claim_apple_effect(
            effect_key=key,
            transcript_id=int(row_id),
            effect_type="note",
            requested_target="Other",
            payload_sha256=key,
        )
        self.assertFalse(active_conflict["claimable"])
        self.assertEqual(transcript_log.get_apple_effect(key)["state"], "in_flight")
        conn = transcript_log._get_conn()
        try:
            conn.execute(
                "UPDATE apple_effects SET lease_expires_at='2020-01-01T00:00:00Z' "
                "WHERE effect_key=? AND lease_owner=?",
                (key, initial["lease_owner"]),
            )
            conn.commit()
        finally:
            conn.close()
        stale_conflict = transcript_log.claim_apple_effect(
            effect_key=key,
            transcript_id=int(row_id),
            effect_type="note",
            requested_target="Other",
            payload_sha256=key,
        )
        self.assertFalse(stale_conflict["claimable"])
        self.assertEqual(stale_conflict["state"], "quarantined")
        self.assertEqual(stale_conflict["error_code"], "effect_key_conflict")

    def test_partial_migration_quarantines_orphan_receipt_metadata(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="apple-effect-orphan-valid", source="test", transcript="body"
        )
        conn = transcript_log._get_conn()
        try:
            conn.execute("DROP TABLE apple_effects")
            conn.execute(
                """CREATE TABLE apple_effects (
                    effect_key TEXT PRIMARY KEY,
                    transcript_id INTEGER NOT NULL,
                    effect_type TEXT NOT NULL,
                    requested_target TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'reserved',
                    provider_id TEXT
                )"""
            )
            rows = [
                ("valid-orphan-test", int(row_id), "valid-provider"),
                ("orphan-orphan-test", 999999, "orphan-provider"),
            ]
            conn.executemany(
                """INSERT INTO apple_effects (
                    effect_key, transcript_id, effect_type, requested_target,
                    payload_sha256, state, provider_id
                ) VALUES (?, ?, 'note', 'Penny', ?, 'succeeded', ?)""",
                [(key, rid, "e" * 64, provider) for key, rid, provider in rows],
            )
            conn.commit()
        finally:
            conn.close()
        transcript_log.init_db()
        conn = transcript_log._get_conn()
        try:
            preserved = conn.execute(
                "SELECT provider_id FROM apple_effects WHERE effect_key='valid-orphan-test'"
            ).fetchone()
            quarantine = conn.execute(
                "SELECT reason_code, effect_key, provider_id FROM apple_effect_quarantine "
                "WHERE effect_key='orphan-orphan-test'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(preserved["provider_id"], "valid-provider")
        self.assertEqual(dict(quarantine), {
            "reason_code": "orphan_transcript",
            "effect_key": "orphan-orphan-test",
            "provider_id": "orphan-provider",
        })
        transcript_log.init_db()
        conn = transcript_log._get_conn()
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM apple_effect_quarantine WHERE effect_key='orphan-orphan-test'"
                ).fetchone()[0],
                1,
            )
        finally:
            conn.close()

    def test_insert_result_distinguishes_duplicate_from_failure(self) -> None:
        inserted = transcript_log.insert_transcript_result(
            content_hash="typed-result", source="test", transcript="first"
        )
        duplicate = transcript_log.insert_transcript_result(
            content_hash="typed-result", source="test", transcript="first"
        )

        self.assertEqual(inserted.outcome, transcript_log.InsertOutcome.INSERTED)
        self.assertEqual(duplicate.outcome, transcript_log.InsertOutcome.DUPLICATE)
        self.assertEqual(duplicate.row_id, inserted.row_id)
        self.assertEqual(duplicate.existing_status, "pending")

    def test_archive_schema_migrates_additively_and_queue_is_unique(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="legacy-md5-content-hash",
            source="iCloud",
            transcript="archive me",
            recorded_at="2026-08-09T19:27:31Z",
        )
        self.assertIsNotNone(row_id)
        staged_path = Path(self.db_dir) / "objects" / "audio.m4a"
        staged_path.parent.mkdir()
        staged_path.write_bytes(b"audio")
        staged = StagedAudio(staged_path, hashlib.sha256(b"audio").hexdigest(), 5, ".m4a")

        metadata = {
            "source": "voice-memos",
            "source_alias": "memo-alias",
            "original_name": "Original Memo.m4a",
            "captured_at": "2026-08-09T19:27:31Z",
            "ingested_at": "2026-08-09T19:28:00Z",
            "duration_seconds": 3.2,
            "mime_type": "audio/mp4",
            "backend": "mlx-whisper",
            "model": "whisper-large-v3-turbo",
            "quality_status": "passed",
        }
        transcript_log.queue_archive_delivery(int(row_id), staged, metadata)
        transcript_log.queue_archive_delivery(
            int(row_id), staged, {**metadata, "source_alias": "second-alias"}
        )

        conn = transcript_log._get_conn()
        try:
            transcript = conn.execute(
                "SELECT content_hash, audio_sha256, transcription_backend, "
                "transcription_model FROM transcripts WHERE id = ?", (row_id,)
            ).fetchone()
            deliveries = conn.execute("SELECT * FROM archive_deliveries").fetchall()
        finally:
            conn.close()
        self.assertEqual(transcript["content_hash"], "legacy-md5-content-hash")
        self.assertEqual(transcript["audio_sha256"], staged.audio_sha256)
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["status"], "pending")
        self.assertEqual(
            json.loads(deliveries[0]["source_aliases"]),
            ["iCloud", "memo-alias", "second-alias", "voice-memos"],
        )

    def test_new_canonical_row_rolls_back_when_atomic_archive_queue_fails(self) -> None:
        staged_path = Path(self.db_dir) / "atomic.m4a"
        staged_path.write_bytes(b"audio")
        staged = StagedAudio(staged_path, hashlib.sha256(b"audio").hexdigest(), 5, ".m4a")
        with patch.object(
            transcript_log,
            "_queue_archive_delivery_conn",
            side_effect=sqlite3.OperationalError("queue unavailable"),
        ):
            result = transcript_log.insert_transcript_result(
                content_hash="atomic-archive",
                source="iCloud",
                transcript="must be atomic",
                archive_staged=staged,
                archive_metadata={"source": "iCloud"},
            )
        self.assertEqual(result.outcome, transcript_log.InsertOutcome.FAILED)
        self.assertIsNone(transcript_log.get_transcript_by_hash("atomic-archive"))

    def test_archive_outbox_retry_receipt_health_and_connection_closure(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="archive-outbox", source="iCloud", transcript="safe body"
        )
        staged_path = Path(self.db_dir) / "object.m4a"
        staged_path.write_bytes(b"audio")
        staged = StagedAudio(staged_path, hashlib.sha256(b"audio").hexdigest(), 5, ".m4a")
        transcript_log.queue_archive_delivery(int(row_id), staged, {"source": "iCloud"})
        due = transcript_log.get_pending_archive_deliveries(limit=1)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["transcript"], "safe body")

        transcript_log.mark_archive_delivery_failed(due[0]["id"], "raw secret body")
        health = transcript_log.get_archive_delivery_health()
        self.assertEqual(health["pending_count"], 1)
        conn = transcript_log._get_conn()
        try:
            failed = dict(conn.execute(
                "SELECT * FROM archive_deliveries WHERE id = ?", (due[0]["id"],)
            ).fetchone())
        finally:
            conn.close()
        self.assertEqual(failed["last_error_code"], "archive_publish_error")
        self.assertNotIn("raw secret body", failed["last_error_code"])
        self.assertIsNotNone(failed["next_attempt_at"])

        transcript_log.mark_archive_delivery_published(
            due[0]["id"],
            audio_path="/mirror/a.m4a",
            markdown_path="/mirror/a.md",
            manifest_path="/mirror/a.json",
            receipt_sha256="receipt-hash",
        )
        health = transcript_log.get_archive_delivery_health()
        self.assertEqual(health["sent_count"], 1)
        self.assertEqual(health["local_mirror_published_count"], 1)

        real = transcript_log._get_conn()
        class ClosingConnection:
            closed = False
            def execute(self, *args, **kwargs):
                raise sqlite3.OperationalError("unavailable")
            def close(self):
                self.closed = True
        broken = ClosingConnection()
        real.close()
        with patch.object(transcript_log, "_get_conn", return_value=broken):
            self.assertEqual(transcript_log.get_archive_delivery_health()["health_error"], 1)
        self.assertTrue(broken.closed)

    def test_archive_partial_schema_migrates_and_quarantines_orphans(self) -> None:
        valid_id = transcript_log.insert_transcript(
            content_hash="partial-valid", source="iCloud", transcript="valid"
        )
        self.assertIsNotNone(valid_id)
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("DROP TABLE archive_deliveries")
            conn.execute(
                """
                CREATE TABLE archive_deliveries (
                    id INTEGER PRIMARY KEY,
                    transcript_id INTEGER,
                    status TEXT,
                    destination_manifest_path TEXT,
                    receipt_sha256 TEXT
                )
                """
            )
            conn.executemany(
                "INSERT INTO archive_deliveries VALUES (?, ?, ?, ?, ?)",
                [
                    (41, valid_id, "published", "/mirror/valid.json", "receipt"),
                    (42, 999999, "pending", None, None),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        transcript_log.init_db()

        conn = transcript_log._get_conn()
        try:
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(archive_deliveries)")
            }
            self.assertIn("transcript_row_id", columns)
            self.assertIn("publication_generation", columns)
            preserved = conn.execute(
                "SELECT id, transcript_row_id, receipt_sha256, publication_scope "
                "FROM archive_deliveries"
            ).fetchone()
            self.assertEqual(tuple(preserved), (41, valid_id, "receipt", "local_mirror"))
            quarantined = conn.execute(
                "SELECT legacy_delivery_id, reason_code FROM archive_delivery_quarantine"
            ).fetchone()
            self.assertEqual(tuple(quarantined), (42, "orphan_transcript"))
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO archive_deliveries "
                    "(transcript_row_id, status, archive_source, source_aliases, "
                    "publication_scope) VALUES (999999, 'pending', 'iCloud', '[]', "
                    "'local_mirror')"
                )
        finally:
            conn.close()

    def test_archive_current_schema_sweeps_orphans_inserted_with_fk_disabled(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute(
                """
                INSERT INTO archive_deliveries (
                    transcript_row_id, archive_source, source_aliases, status
                ) VALUES (999999, 'iCloud', '[]', 'pending')
                """
            )
            orphan_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
        finally:
            conn.close()

        transcript_log.init_db()

        conn = transcript_log._get_conn()
        try:
            self.assertIsNone(
                conn.execute(
                    "SELECT id FROM archive_deliveries WHERE id = ?", (orphan_id,)
                ).fetchone()
            )
            quarantined = conn.execute(
                "SELECT legacy_delivery_id, reason_code "
                "FROM archive_delivery_quarantine WHERE legacy_delivery_id = ?",
                (orphan_id,),
            ).fetchone()
            self.assertEqual(tuple(quarantined), (orphan_id, "orphan_transcript"))
        finally:
            conn.close()

    def test_recoverable_audio_replaces_prior_unavailable_archive_marker(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="recovered-audio", source="iCloud", transcript="recovered"
        )
        transcript_log.record_archive_unavailable(
            int(row_id),
            availability_status="unavailable",
            reason_code="missing_audio_source",
        )
        staged_path = Path(self.db_dir) / "recovered.m4a"
        staged_path.write_bytes(b"audio")
        staged = StagedAudio(
            staged_path, hashlib.sha256(b"audio").hexdigest(), 5, ".m4a"
        )

        transcript_log.queue_archive_delivery(
            int(row_id), staged, {"source": "iCloud"}
        )

        pending = transcript_log.get_pending_archive_deliveries(limit=1)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["availability_status"], "available")
        self.assertIsNone(pending[0]["unavailable_reason"])

    def test_insert_result_reports_database_failure(self) -> None:
        with patch.object(
            transcript_log,
            "_get_conn",
            side_effect=sqlite3.OperationalError("locked: /sensitive/path"),
        ):
            result = transcript_log.insert_transcript_result(
                content_hash="db-failure", source="test", transcript="never stored"
            )

        self.assertEqual(result.outcome, transcript_log.InsertOutcome.FAILED)
        self.assertIsNone(result.row_id)
        self.assertEqual(result.error_code, "database_unavailable")

    def test_insert_result_reports_second_connection_database_failure(self) -> None:
        real_get_conn = transcript_log._get_conn
        connections_opened = 0

        def fail_only_canonical_duplicate_lookup():
            nonlocal connections_opened
            connections_opened += 1
            if connections_opened == 3:
                raise sqlite3.OperationalError("locked: /sensitive/path")
            return real_get_conn()

        with patch.object(
            transcript_log,
            "_get_conn",
            side_effect=fail_only_canonical_duplicate_lookup,
        ), patch.object(transcript_log, "log") as log_mock:
            inserted = transcript_log.insert_transcript_result(
                content_hash="second-lookup-failure", source="test", transcript="first"
            )
            failed = transcript_log.insert_transcript_result(
                content_hash="second-lookup-failure", source="test", transcript="first"
            )

        self.assertEqual(inserted.outcome, transcript_log.InsertOutcome.INSERTED)
        self.assertEqual(failed.outcome, transcript_log.InsertOutcome.FAILED)
        self.assertIsNone(failed.row_id)
        self.assertEqual(failed.error_code, "database_unavailable")
        log_mock.error.assert_called_once_with(
            "Failed to insert transcript due to a database error"
        )

    def test_insert_result_and_legacy_wrapper_propagate_invalid_recorded_at(self) -> None:
        for inserter in (
            transcript_log.insert_transcript_result,
            transcript_log.insert_transcript,
        ):
            with self.subTest(inserter=inserter.__name__), self.assertRaisesRegex(
                ValueError, "Persisted capture timestamp is invalid"
            ):
                inserter(
                    content_hash=f"invalid-recorded-at-{inserter.__name__}",
                    source="test",
                    transcript="never stored",
                    recorded_at="not-a-timestamp",
                )

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
                           maya_delivery_eligible, recorded_at,
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
                "maya_first_attempt_at",
                "maya_last_attempt_at",
                "maya_dead_letter_at",
                "maya_dead_letter_reason",
                "maya_claim_token",
                "maya_claim_owner",
                "maya_claimed_at",
                "maya_claim_expires_at",
                "maya_delivery_eligible",
                "recorded_at",
                "superseded_by_transcript_row_id",
            }.issubset(columns)
        )
        self.assertEqual(row["content_hash"], "legacy-content-hash")
        self.assertEqual(row["transcript"], legacy_transcript)
        self.assertEqual(row["quality_status"], "pending")
        self.assertIsNone(row["quality_detail"])
        self.assertEqual(
            row["transcript_sha256"],
            hashlib.sha256(legacy_transcript.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(row["maya_delivery_status"], "ineligible")
        self.assertEqual(row["maya_delivery_eligible"], 0)
        self.assertIsNone(row["recorded_at"])
        self.assertIsNone(row["maya_drop_id"])
        self.assertIsNone(row["superseded_by_transcript_row_id"])
        self.assertEqual(transcript_log.get_pending_maya_deliveries(), [])

    def test_maya_due_query_and_builder_fail_closed_for_noncanonical_rows(
        self,
    ) -> None:
        captured_at = "2026-07-28T12:34:56Z"
        canonical_id = transcript_log.insert_transcript(
            content_hash="maya-explicit-canonical",
            source="iCloud",
            transcript="Only this explicit canonical capture is Maya-due.",
            ingest_state="transcribed",
            recorded_at=captured_at,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        skipped_id = transcript_log.insert_transcript(
            content_hash="maya-skipped-placeholder",
            source="iCloud",
            transcript="(skipped: file too large)",
            ingest_state="skipped_too_large",
            recorded_at=captured_at,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        migrated_id = transcript_log.insert_transcript(
            content_hash="maya-migrated-placeholder",
            source="iCloud",
            transcript="(migrated — original transcript not preserved)",
            ingest_state="transcribed",
            recorded_at=captured_at,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        empty_id = transcript_log.insert_transcript(
            content_hash="maya-empty-body",
            source="iCloud",
            transcript="   ",
            ingest_state="transcribed",
            recorded_at=captured_at,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        review_id = transcript_log.insert_transcript(
            content_hash="maya-review-body",
            source="iCloud",
            transcript="This remains under review.",
            ingest_state="needs_review",
            recorded_at=captured_at,
            quality_status="needs_review",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        maya_origin_id = transcript_log.insert_transcript(
            content_hash="maya-origin-body",
            source="maya:icloud",
            transcript="This originated in Maya.",
            ingest_state="transcribed",
            recorded_at=captured_at,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        superseded_id = transcript_log.insert_transcript(
            content_hash="maya-superseded-body",
            source="iCloud",
            transcript="This canonical row was later superseded.",
            ingest_state="transcribed",
            recorded_at=captured_at,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        self.assertTrue(
            all(
                row_id is not None
                for row_id in (
                    canonical_id,
                    skipped_id,
                    migrated_id,
                    empty_id,
                    review_id,
                    maya_origin_id,
                    superseded_id,
                )
            )
        )
        conn = transcript_log._get_conn()
        try:
            conn.execute(
                """
                UPDATE transcripts
                SET superseded_by_transcript_row_id = ?
                WHERE id = ?
                """,
                (canonical_id, superseded_id),
            )
            conn.commit()
        finally:
            conn.close()

        due = transcript_log.get_pending_maya_deliveries()

        self.assertEqual([row["id"] for row in due], [canonical_id])
        self.assertEqual(
            transcript_log.build_maya_v2_envelope(int(canonical_id))["captured_at"],
            captured_at,
        )
        for row_id in (
            skipped_id,
            migrated_id,
            empty_id,
            review_id,
            maya_origin_id,
            superseded_id,
        ):
            with self.subTest(row_id=row_id):
                with self.assertRaises(ValueError):
                    transcript_log.build_maya_v2_envelope(int(row_id))

    def test_canonical_insert_uses_exact_utf8_hash_and_queues_only_passed_quality(
        self,
    ) -> None:
        passed_text = "Caf\u00e9 notes stay byte-exact."
        passed_row_id = transcript_log.insert_transcript(
            content_hash="canonical-passed-audio-hash",
            source="iCloud",
            transcript=passed_text,
            ingest_state="transcribed",
            recorded_at="2026-07-28T12:34:56Z",
            quality_status="passed",
            maya_delivery_eligible=True,
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
        self.assertEqual(passed["maya_delivery_eligible"], 1)
        self.assertEqual(passed["maya_delivery_status"], "pending")
        self.assertEqual(review["maya_delivery_eligible"], 0)
        self.assertEqual(review["maya_delivery_status"], "ineligible")
        self.assertEqual(
            [delivery["transcript_row_id"] for delivery in transcript_log.get_pending_slack_deliveries()],
            [passed_row_id],
        )

    def test_maya_delivery_receipts_and_failures_persist_independent_state(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="maya-delivery-state-audio-hash",
            source="iCloud",
            transcript="Persist delivery acknowledgement state.",
            ingest_state="transcribed",
            recorded_at="2026-07-28T12:34:56Z",
            quality_status="passed",
            maya_delivery_eligible=True,
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

        self.assertTrue(
            transcript_log.replay_maya_delivery(
                int(row_id), now="2026-08-10T12:00:00Z"
            )
        )
        transcript_log.mark_maya_delivery_sent(int(row_id), "drop-penny-v2-123")
        transcript_log.mark_maya_delivery_sent(int(row_id), "drop-penny-v2-123")
        sent = transcript_log.get_transcript(int(row_id))
        self.assertEqual(sent["maya_delivery_status"], "sent")
        self.assertEqual(sent["maya_drop_id"], "drop-penny-v2-123")
        self.assertIsNone(sent["maya_delivery_error"])

    def test_maya_retry_reaches_attempt_cap_dead_letter_atomically(self) -> None:
        now = "2026-08-10T12:00:00Z"
        row_id = transcript_log.insert_transcript(
            content_hash="maya-attempt-cap",
            source="iCloud",
            transcript="Attempt cap is terminal.",
            ingest_state="transcribed",
            recorded_at=now,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        conn = transcript_log._get_conn()
        try:
            conn.execute(
                "UPDATE transcripts SET maya_delivery_attempt_count = 19 "
                "WHERE id = ?",
                (row_id,),
            )
            conn.commit()
        finally:
            conn.close()

        transcript_log.mark_maya_delivery_retryable(
            int(row_id), "timeout", retry_after_seconds=1, now=now
        )

        stored = transcript_log.get_transcript(int(row_id))
        self.assertEqual(stored["maya_delivery_status"], "dead_letter")
        self.assertEqual(stored["maya_delivery_attempt_count"], 20)
        self.assertEqual(stored["maya_dead_letter_reason"], "attempt_cap")
        self.assertEqual(stored["maya_first_attempt_at"], now)
        self.assertEqual(stored["maya_last_attempt_at"], now)
        self.assertEqual(stored["maya_dead_letter_at"], now)
        self.assertIsNone(stored["maya_next_attempt_at"])

    def test_maya_retry_reaches_age_cap_dead_letter_atomically(self) -> None:
        now = "2026-08-10T12:00:00Z"
        first_attempt = "2026-08-03T11:59:59Z"
        row_id = transcript_log.insert_transcript(
            content_hash="maya-age-cap",
            source="iCloud",
            transcript="Age cap is terminal.",
            ingest_state="transcribed",
            recorded_at=now,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        conn = transcript_log._get_conn()
        try:
            conn.execute(
                "UPDATE transcripts SET maya_delivery_attempt_count = 1, "
                "maya_first_attempt_at = ?, maya_last_attempt_at = ? WHERE id = ?",
                (first_attempt, first_attempt, row_id),
            )
            conn.commit()
        finally:
            conn.close()

        transcript_log.mark_maya_delivery_retryable(
            int(row_id), "timeout", retry_after_seconds=1, now=now
        )

        stored = transcript_log.get_transcript(int(row_id))
        self.assertEqual(stored["maya_delivery_status"], "dead_letter")
        self.assertEqual(stored["maya_delivery_attempt_count"], 2)
        self.assertEqual(stored["maya_dead_letter_reason"], "age_cap")
        self.assertEqual(stored["maya_first_attempt_at"], first_attempt)
        self.assertEqual(stored["maya_last_attempt_at"], now)
        self.assertEqual(stored["maya_dead_letter_at"], now)

    def test_maya_retry_age_edges_are_deterministic(self) -> None:
        now = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
        for suffix, first_attempt, expected_status in (
            (
                "under",
                now - timedelta(days=7, seconds=-1),
                "pending",
            ),
            ("exact", now - timedelta(days=7), "dead_letter"),
            ("over", now - timedelta(days=7, seconds=1), "dead_letter"),
        ):
            with self.subTest(suffix=suffix):
                row_id = transcript_log.insert_transcript(
                    content_hash=f"maya-age-edge-{suffix}",
                    source="iCloud",
                    transcript=f"Age edge {suffix}.",
                    ingest_state="transcribed",
                    recorded_at=now.isoformat().replace("+00:00", "Z"),
                    quality_status="passed",
                    maya_delivery_eligible=True,
                    enqueue_slack=False,
                )
                first_value = first_attempt.isoformat().replace("+00:00", "Z")
                conn = transcript_log._get_conn()
                try:
                    conn.execute(
                        "UPDATE transcripts SET maya_delivery_attempt_count = 1, "
                        "maya_first_attempt_at = ? WHERE id = ?",
                        (first_value, row_id),
                    )
                    conn.commit()
                finally:
                    conn.close()
                transcript_log.mark_maya_delivery_retryable(
                    int(row_id), "timeout", now=now
                )
                stored = transcript_log.get_transcript(int(row_id))
                self.assertEqual(stored["maya_delivery_status"], expected_status)

    def test_maya_malformed_first_attempt_is_quarantined_and_future_is_not_aged(self) -> None:
        now = "2026-08-10T12:00:00Z"
        malformed = transcript_log.insert_transcript(
            content_hash="maya-malformed-first-attempt",
            source="iCloud",
            transcript="Malformed timestamp must fail closed.",
            ingest_state="transcribed",
            recorded_at=now,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        future = transcript_log.insert_transcript(
            content_hash="maya-future-first-attempt",
            source="iCloud",
            transcript="Future timestamp is not already old.",
            ingest_state="transcribed",
            recorded_at=now,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        conn = transcript_log._get_conn()
        try:
            conn.executemany(
                "UPDATE transcripts SET maya_delivery_attempt_count = 1, "
                "maya_first_attempt_at = ? WHERE id = ?",
                [("not-a-timestamp", malformed), ("2026-08-20T12:00:00Z", future)],
            )
            conn.commit()
        finally:
            conn.close()

        transcript_log.mark_maya_delivery_retryable(int(malformed), "timeout", now=now)
        transcript_log.mark_maya_delivery_retryable(int(future), "timeout", now=now)

        malformed_row = transcript_log.get_transcript(int(malformed))
        future_row = transcript_log.get_transcript(int(future))
        self.assertEqual(malformed_row["maya_delivery_status"], "dead_letter")
        self.assertEqual(malformed_row["maya_dead_letter_reason"], "age_cap")
        self.assertEqual(future_row["maya_delivery_status"], "pending")
        self.assertEqual(future_row["maya_first_attempt_at"], "2026-08-20T12:00:00Z")

    def test_maya_dead_letter_is_idempotent_and_sent_receipt_is_immutable(self) -> None:
        now = "2026-08-10T12:00:00Z"
        row_id = transcript_log.insert_transcript(
            content_hash="maya-dead-letter-idempotence",
            source="iCloud",
            transcript="Dead-letter reason cannot be rewritten.",
            ingest_state="transcribed",
            recorded_at=now,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        self.assertTrue(
            transcript_log.mark_maya_delivery_dead_letter(
                int(row_id), "attempt_cap", now=now
            )
        )
        self.assertFalse(
            transcript_log.mark_maya_delivery_dead_letter(
                int(row_id), "age_cap", now="2026-08-10T13:00:00Z"
            )
        )
        stored = transcript_log.get_transcript(int(row_id))
        self.assertEqual(stored["maya_dead_letter_reason"], "attempt_cap")
        self.assertEqual(stored["maya_dead_letter_at"], now)

        self.assertTrue(transcript_log.replay_maya_delivery(int(row_id), now=now))
        transcript_log.mark_maya_delivery_sent(int(row_id), "drop-immutable")
        self.assertFalse(
            transcript_log.mark_maya_delivery_dead_letter(
                int(row_id), "age_cap", now="2026-08-10T13:00:00Z"
            )
        )
        self.assertFalse(transcript_log.replay_maya_delivery(int(row_id), now=now))
        stored = transcript_log.get_transcript(int(row_id))
        self.assertEqual(stored["maya_delivery_status"], "sent")
        self.assertEqual(stored["maya_drop_id"], "drop-immutable")

    def test_maya_pending_query_terminalizes_stale_rows_and_excludes_them(self) -> None:
        now = "2026-08-10T12:00:00Z"
        stale = transcript_log.insert_transcript(
            content_hash="maya-stale-pending",
            source="iCloud",
            transcript="Stale pending row.",
            ingest_state="transcribed",
            recorded_at=now,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        fresh = transcript_log.insert_transcript(
            content_hash="maya-fresh-pending",
            source="iCloud",
            transcript="Fresh pending row.",
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
                "maya_first_attempt_at = ?, maya_next_attempt_at = NULL WHERE id = ?",
                ("2026-08-01T12:00:00Z", stale),
            )
            conn.commit()
        finally:
            conn.close()

        pending = transcript_log.get_pending_maya_deliveries(limit=20, now=now)

        self.assertEqual([int(row["id"]) for row in pending], [int(fresh)])
        stale_row = transcript_log.get_transcript(int(stale))
        self.assertEqual(stale_row["maya_delivery_status"], "dead_letter")
        self.assertEqual(stale_row["maya_dead_letter_reason"], "attempt_cap")

    def test_maya_pending_query_terminalizes_malformed_first_attempt_before_http(self) -> None:
        now = "2026-08-10T12:00:00Z"
        row_id = transcript_log.insert_transcript(
            content_hash="maya-malformed-pending-first-attempt",
            source="iCloud",
            transcript="Malformed pending timestamp.",
            ingest_state="transcribed",
            recorded_at=now,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        conn = transcript_log._get_conn()
        try:
            conn.execute(
                "UPDATE transcripts SET maya_delivery_attempt_count = 1, "
                "maya_first_attempt_at = ? WHERE id = ?",
                ("not-a-timestamp", row_id),
            )
            conn.commit()
        finally:
            conn.close()

        self.assertEqual(
            transcript_log.get_pending_maya_deliveries(limit=10, now=now), []
        )
        stored = transcript_log.get_transcript(int(row_id))
        self.assertEqual(stored["maya_delivery_status"], "dead_letter")
        self.assertEqual(stored["maya_dead_letter_reason"], "age_cap")

    def test_maya_pending_query_terminalizes_invalid_schedule_and_preserves_future_schedule(self) -> None:
        now = "2026-08-10T12:00:00Z"
        invalid = transcript_log.insert_transcript(
            content_hash="maya-invalid-next-attempt",
            source="iCloud",
            transcript="Invalid schedule must not be sent.",
            ingest_state="transcribed",
            recorded_at=now,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        future = transcript_log.insert_transcript(
            content_hash="maya-future-next-attempt",
            source="iCloud",
            transcript="Future schedule remains pending.",
            ingest_state="transcribed",
            recorded_at=now,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        conn = transcript_log._get_conn()
        try:
            conn.executemany(
                "UPDATE transcripts SET maya_next_attempt_at = ? WHERE id = ?",
                [("not-a-schedule", invalid), ("2026-08-11T12:00:00Z", future)],
            )
            conn.commit()
        finally:
            conn.close()

        pending = transcript_log.get_pending_maya_deliveries(limit=10, now=now)

        self.assertEqual([int(row["id"]) for row in pending], [])
        invalid_row = transcript_log.get_transcript(int(invalid))
        future_row = transcript_log.get_transcript(int(future))
        self.assertEqual(invalid_row["maya_delivery_status"], "dead_letter")
        self.assertEqual(invalid_row["maya_dead_letter_reason"], "invalid_schedule")
        self.assertEqual(future_row["maya_delivery_status"], "pending")
        self.assertEqual(future_row["maya_next_attempt_at"], "2026-08-11T12:00:00Z")

    def test_maya_claim_is_atomic_owner_bound_and_expired_claims_recover(self) -> None:
        now = "2026-08-10T12:00:00Z"
        row_id = transcript_log.insert_transcript(
            content_hash="maya-claim-cas",
            source="iCloud",
            transcript="Only one worker may claim this row.",
            ingest_state="transcribed",
            recorded_at=now,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )

        first = transcript_log.claim_maya_delivery(
            int(row_id), "worker-a", now=now, lease_seconds=60
        )
        self.assertIsNotNone(first)
        self.assertEqual(first["maya_claim_owner"], "worker-a")
        self.assertEqual(
            transcript_log.claim_maya_delivery(
                int(row_id), "worker-b", now=now, lease_seconds=60
            ),
            None,
        )
        with self.assertRaises(ValueError):
            transcript_log.mark_maya_delivery_retryable(
                int(row_id),
                "timeout",
                now=now,
                claim_token=first["maya_claim_token"],
                claim_owner="worker-b",
            )
        stored = transcript_log.get_transcript(int(row_id))
        self.assertEqual(stored["maya_delivery_status"], "pending")
        self.assertEqual(stored["maya_claim_owner"], "worker-a")

        recovered = transcript_log.claim_maya_delivery(
            int(row_id), "worker-b", now="2026-08-10T12:01:01Z", lease_seconds=60
        )
        self.assertIsNotNone(recovered)
        self.assertNotEqual(
            recovered["maya_claim_token"], first["maya_claim_token"]
        )
        self.assertEqual(recovered["maya_claim_owner"], "worker-b")

    def test_maya_claim_cannot_use_stale_snapshot_after_dead_letter(self) -> None:
        now = "2026-08-10T12:00:00Z"
        row_id = transcript_log.insert_transcript(
            content_hash="maya-claim-stale-snapshot",
            source="iCloud",
            transcript="A stale selection cannot dispatch.",
            ingest_state="transcribed",
            recorded_at=now,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        selected = transcript_log.get_pending_maya_deliveries(limit=1, now=now)[0]
        self.assertEqual(selected["id"], row_id)
        self.assertTrue(
            transcript_log.mark_maya_delivery_dead_letter(
                int(row_id), "operator_replay", now=now
            )
        )
        self.assertIsNone(
            transcript_log.claim_maya_delivery(int(row_id), "worker-a", now=now)
        )

    def test_maya_claim_owner_is_required_for_worker_transitions(self) -> None:
        now = "2026-08-10T12:00:00Z"
        row_id = transcript_log.insert_transcript(
            content_hash="maya-claim-owner-transition",
            source="iCloud",
            transcript="Claim ownership gates every worker transition.",
            ingest_state="transcribed",
            recorded_at=now,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        claim = transcript_log.claim_maya_delivery(int(row_id), "worker-a", now=now)
        self.assertIsNotNone(claim)
        claim_kwargs = {
            "claim_token": claim["maya_claim_token"],
            "claim_owner": "worker-b",
        }
        with self.assertRaises(ValueError):
            transcript_log.mark_maya_delivery_sent(
                int(row_id), "drop-owner-mismatch", **claim_kwargs
            )
        with self.assertRaises(ValueError):
            transcript_log.mark_maya_delivery_failed(
                int(row_id), "provider_error", **claim_kwargs
            )
        with self.assertRaises(ValueError):
            transcript_log.mark_maya_delivery_retryable(
                int(row_id), "timeout", now=now, **claim_kwargs
            )
        stored = transcript_log.get_transcript(int(row_id))
        self.assertEqual(stored["maya_delivery_status"], "pending")
        self.assertEqual(stored["maya_claim_owner"], "worker-a")

    def test_maya_pending_row_with_drop_id_cannot_overwrite_receipt(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="maya-pending-drop-invariant",
            source="iCloud",
            transcript="A pending row with a receipt must not be overwritten.",
            ingest_state="transcribed",
            recorded_at="2026-08-10T12:00:00Z",
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        conn = transcript_log._get_conn()
        try:
            conn.execute(
                "UPDATE transcripts SET maya_drop_id = ? WHERE id = ?",
                ("drop-existing", row_id),
            )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(ValueError):
            transcript_log.mark_maya_delivery_sent(int(row_id), "drop-new")
        stored = transcript_log.get_transcript(int(row_id))
        self.assertEqual(stored["maya_delivery_status"], "pending")
        self.assertEqual(stored["maya_drop_id"], "drop-existing")

    def test_active_maya_claim_is_not_terminalized_until_lease_expiry(self) -> None:
        now = "2026-08-10T12:00:00Z"
        row_id = transcript_log.insert_transcript(
            content_hash="maya-active-claim-cap",
            source="iCloud",
            transcript="An active worker claim must finish its HTTP attempt.",
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

        claim = transcript_log.claim_maya_delivery(
            int(row_id), "worker-active", now=now, lease_seconds=60
        )
        self.assertIsNotNone(claim)

        pending = transcript_log.get_pending_maya_deliveries(limit=10, now=now)
        self.assertEqual([int(row["id"]) for row in pending], [int(row_id)])
        active = transcript_log.get_transcript(int(row_id))
        self.assertEqual(active["maya_delivery_status"], "pending")
        self.assertEqual(active["maya_claim_owner"], "worker-active")

        expired_pending = transcript_log.get_pending_maya_deliveries(
            limit=10, now="2026-08-10T12:01:01Z"
        )
        self.assertEqual(expired_pending, [])
        expired = transcript_log.get_transcript(int(row_id))
        self.assertEqual(expired["maya_delivery_status"], "dead_letter")
        self.assertEqual(expired["maya_dead_letter_reason"], "attempt_cap")
        self.assertIsNone(expired["maya_claim_token"])
        self.assertIsNone(expired["maya_claim_owner"])

    def test_maya_replay_preserves_envelope_and_only_resets_delivery_schedule(self) -> None:
        now = "2026-08-10T12:00:00Z"
        row_id = transcript_log.insert_transcript(
            content_hash="maya-replay-identity",
            source="iCloud",
            transcript="Replay preserves this exact envelope.",
            ingest_state="transcribed",
            recorded_at=now,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=True,
        )
        before_envelope = transcript_log.build_maya_v2_envelope(int(row_id))
        before = transcript_log.get_transcript(int(row_id))
        transcript_log.mark_maya_delivery_dead_letter(int(row_id), "attempt_cap", now=now)

        self.assertTrue(transcript_log.replay_maya_delivery(int(row_id), now=now))

        after = transcript_log.get_transcript(int(row_id))
        self.assertEqual(
            transcript_log.build_maya_v2_envelope(int(row_id)), before_envelope
        )
        self.assertEqual(after["content_hash"], before["content_hash"])
        self.assertEqual(after["transcript_sha256"], before["transcript_sha256"])
        self.assertEqual(after["maya_delivery_status"], "pending")
        self.assertEqual(after["maya_delivery_attempt_count"], 0)
        self.assertIsNone(after["maya_first_attempt_at"])
        self.assertIsNone(after["maya_last_attempt_at"])
        self.assertIsNone(after["maya_dead_letter_at"])
        self.assertIsNone(after["maya_dead_letter_reason"])
        self.assertIsNone(after["maya_delivery_error"])
        self.assertEqual(
            transcript_log.get_pending_slack_deliveries(transcript_id=int(row_id))[0]["status"],
            "pending",
        )

    def test_maya_sent_receipt_cannot_be_reopened_from_terminal_state(self) -> None:
        now = "2026-08-10T12:00:00Z"
        row_id = transcript_log.insert_transcript(
            content_hash="maya-terminal-monotonic",
            source="iCloud",
            transcript="Terminal states stay terminal until explicit replay.",
            ingest_state="transcribed",
            recorded_at=now,
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        transcript_log.mark_maya_delivery_dead_letter(int(row_id), "age_cap", now=now)

        with self.assertRaises(ValueError):
            transcript_log.mark_maya_delivery_sent(int(row_id), "drop-must-not-send")
        self.assertEqual(
            transcript_log.get_transcript(int(row_id))["maya_delivery_status"],
            "dead_letter",
        )

    def test_maya_failed_row_requires_explicit_replay_before_sent_receipt(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="maya-failed-replay-gate",
            source="iCloud",
            transcript="A failed row cannot skip replay.",
            ingest_state="transcribed",
            recorded_at="2026-08-10T12:00:00Z",
            quality_status="passed",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        transcript_log.mark_maya_delivery_failed(int(row_id), "provider_error")
        with self.assertRaises(ValueError):
            transcript_log.mark_maya_delivery_sent(int(row_id), "drop-no-replay")
        self.assertEqual(
            transcript_log.get_transcript(int(row_id))["maya_delivery_status"],
            "failed",
        )

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
            ingest_state="transcribed",
            recorded_at="2026-07-28T12:34:56Z",
            quality_status="passed",
            maya_delivery_eligible=True,
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
            ingest_state="transcribed",
            recorded_at="2026-07-28T12:34:56Z",
            quality_status="passed",
            maya_delivery_eligible=True,
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
        migrated_row = transcript_log.get_transcript_by_hash(
            "legacy-processed-hash"
        )
        self.assertEqual(migrated_row["maya_delivery_status"], "ineligible")
        self.assertEqual(migrated_row["maya_delivery_eligible"], 0)
        self.assertEqual(transcript_log.get_pending_maya_deliveries(), [])

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

    def test_init_db_versions_legacy_plans_without_reinterpreting_partial_progress(
        self,
    ) -> None:
        sent_row_id = transcript_log.insert_transcript(
            content_hash="legacy-plan-sent",
            source="iCloud",
            transcript="sent legacy body",
            ingest_state="routed",
            enqueue_slack=False,
        )
        unstarted_row_id = transcript_log.insert_transcript(
            content_hash="legacy-plan-unstarted",
            source="iCloud",
            transcript="unstarted legacy body",
            ingest_state="routed",
            enqueue_slack=False,
        )
        partial_row_id = transcript_log.insert_transcript(
            content_hash="legacy-plan-partial",
            source="iCloud",
            transcript="P" * 80_000,
            ingest_state="routed",
            enqueue_slack=False,
        )
        self.assertIsNotNone(sent_row_id)
        self.assertIsNotNone(unstarted_row_id)
        self.assertIsNotNone(partial_row_id)

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
                    next_attempt_at TEXT,
                    last_error TEXT,
                    provider_ts TEXT,
                    next_chunk_index INTEGER NOT NULL DEFAULT 0,
                    chunk_attempt_count INTEGER NOT NULL DEFAULT 0,
                    chunk_provider_ts TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    sent_at TEXT,
                    FOREIGN KEY(transcript_row_id) REFERENCES transcripts(id)
                )
                """
            )
            conn.executemany(
                """
                INSERT INTO slack_deliveries (
                    transcript_row_id, channel_id, message_text, status,
                    provider_ts, next_chunk_index, chunk_provider_ts, sent_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        sent_row_id,
                        "C0BKS0QT7FU",
                        "sent legacy body",
                        "sent",
                        "legacy.latest",
                        2,
                        '["legacy.first", "legacy.latest"]',
                        "2026-07-28 12:00:00",
                    ),
                    (
                        unstarted_row_id,
                        "C0BKS0QT7FU",
                        "unstarted legacy body",
                        "pending",
                        None,
                        0,
                        "[]",
                        None,
                    ),
                    (
                        partial_row_id,
                        "C0BKS0QT7FU",
                        "P" * 80_000,
                        "pending",
                        "legacy.first",
                        1,
                        '["legacy.first"]',
                        None,
                    ),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        transcript_log.init_db()
        fresh_row_id = transcript_log.insert_transcript(
            content_hash="current-plan-fresh",
            source="iCloud",
            transcript="fresh Block Kit body",
            ingest_state="routed",
        )
        self.assertIsNotNone(fresh_row_id)

        conn = transcript_log._get_conn()
        try:
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(slack_deliveries)")
            }
            self.assertIn("delivery_plan_version", columns)
            rows = {
                int(row["transcript_row_id"]): dict(row)
                for row in conn.execute(
                    """
                    SELECT transcript_row_id, message_text, status, last_error,
                           delivery_plan_version, provider_ts,
                           next_chunk_index, chunk_provider_ts,
                           next_attempt_at, sent_at
                    FROM slack_deliveries
                    ORDER BY transcript_row_id
                    """
                ).fetchall()
            }
        finally:
            conn.close()

        sent = rows[int(sent_row_id)]
        self.assertEqual(sent["message_text"], "sent legacy body")
        self.assertEqual(sent["status"], "sent")
        self.assertEqual(sent["delivery_plan_version"], "legacy_top_level_v1")
        self.assertEqual(sent["provider_ts"], "legacy.latest")
        self.assertEqual(sent["next_chunk_index"], 2)
        self.assertEqual(
            sent["chunk_provider_ts"],
            '["legacy.first", "legacy.latest"]',
        )
        self.assertEqual(sent["sent_at"], "2026-07-28 12:00:00")

        unstarted = rows[int(unstarted_row_id)]
        self.assertEqual(unstarted["status"], "pending")
        self.assertEqual(unstarted["delivery_plan_version"], "block_kit_v2")
        self.assertIsNone(unstarted["provider_ts"])
        self.assertEqual(unstarted["next_chunk_index"], 0)
        self.assertEqual(unstarted["chunk_provider_ts"], "[]")

        partial = rows[int(partial_row_id)]
        self.assertEqual(partial["message_text"], "P" * 80_000)
        self.assertEqual(partial["status"], "failed")
        self.assertEqual(partial["delivery_plan_version"], "legacy_top_level_v1")
        self.assertEqual(
            partial["last_error"],
            "legacy_partial_reconciliation_required",
        )
        self.assertIsNone(partial["next_attempt_at"])
        self.assertEqual(partial["provider_ts"], "legacy.first")
        self.assertEqual(partial["next_chunk_index"], 1)
        self.assertEqual(partial["chunk_provider_ts"], '["legacy.first"]')

        fresh = rows[int(fresh_row_id)]
        self.assertEqual(fresh["status"], "pending")
        self.assertEqual(fresh["delivery_plan_version"], "block_kit_v2")
        self.assertEqual(
            {
                int(row["transcript_row_id"])
                for row in transcript_log.get_pending_slack_deliveries()
            },
            {int(unstarted_row_id), int(fresh_row_id)},
        )

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
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
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

    def test_quality_failure_outbox_is_body_free_durable_and_idempotent(self) -> None:
        transcript = "PRIVATE TRANSCRIPT BODY MUST NEVER ENTER THE LEDGER RECEIPT"
        row_id = transcript_log.insert_transcript(
            content_hash="quality-failure-stable-hash",
            source="iCloud",
            transcript=transcript,
            ingest_state="needs_review",
            quality_status="needs_review",
            quality_detail=(
                "attempt_1=consecutive_token_repetition;"
                "attempt_2=control_token"
            ),
            enqueue_slack=False,
        )
        transcript_log.init_db()

        pending = transcript_log.get_pending_quality_failure_deliveries()

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["transcript_row_id"], row_id)
        self.assertEqual(
            pending[0]["idempotency_key"],
            "penny:quality-failure:quality-failure-stable-hash",
        )
        self.assertEqual(
            pending[0]["content_kind"],
            "transcript_quality_failure",
        )
        self.assertEqual(pending[0]["destination"], "maya-ledger")
        self.assertNotIn(transcript, pending[0]["message_text"])
        self.assertIn(
            "attempt_2=control_token",
            pending[0]["message_text"],
        )
        health = transcript_log.get_slack_delivery_health()
        self.assertEqual(health["quality_failure_pending_count"], 1)
        self.assertEqual(health["quality_failure_failed_count"], 0)

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

    def test_late_failure_cannot_reopen_completed_parent_or_final_continuation(
        self,
    ) -> None:
        parent_row_id = transcript_log.insert_transcript(
            content_hash="slack-parent-terminal",
            source="iCloud",
            transcript="One parent is terminal after its receipt.",
        )
        parent_delivery_id = transcript_log.get_pending_slack_deliveries(
            transcript_id=parent_row_id
        )[0]["id"]
        transcript_log.mark_slack_delivery_chunk_sent(
            parent_delivery_id,
            chunk_index=0,
            chunk_count=1,
            provider_ts="parent.terminal",
        )

        continuation_row_id = transcript_log.insert_transcript(
            content_hash="slack-continuation-terminal",
            source="iCloud",
            transcript="An extreme message's final continuation is also terminal.",
        )
        continuation_delivery_id = transcript_log.get_pending_slack_deliveries(
            transcript_id=continuation_row_id
        )[0]["id"]
        transcript_log.mark_slack_delivery_chunk_sent(
            continuation_delivery_id,
            chunk_index=0,
            chunk_count=2,
            provider_ts="parent.extreme",
        )
        transcript_log.mark_slack_delivery_chunk_sent(
            continuation_delivery_id,
            chunk_index=1,
            chunk_count=2,
            provider_ts="continuation.final",
        )

        transcript_log.mark_slack_delivery_failed(
            parent_delivery_id,
            "delivery_error",
        )
        transcript_log.mark_slack_delivery_failed(
            continuation_delivery_id,
            "delivery_error",
        )

        conn = transcript_log._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT id, status, attempt_count, chunk_attempt_count,
                       last_error, provider_ts, next_chunk_index
                FROM slack_deliveries
                WHERE id IN (?, ?)
                ORDER BY id
                """,
                (parent_delivery_id, continuation_delivery_id),
            ).fetchall()
        finally:
            conn.close()
        parent, continuation = [dict(row) for row in rows]
        self.assertEqual(
            parent,
            {
                "id": parent_delivery_id,
                "status": "sent",
                "attempt_count": 0,
                "chunk_attempt_count": 0,
                "last_error": None,
                "provider_ts": "parent.terminal",
                "next_chunk_index": 1,
            },
        )
        self.assertEqual(
            continuation,
            {
                "id": continuation_delivery_id,
                "status": "sent",
                "attempt_count": 0,
                "chunk_attempt_count": 0,
                "last_error": None,
                "provider_ts": "parent.extreme",
                "next_chunk_index": 2,
            },
        )

    def test_sent_and_failure_race_cannot_reopen_slack_delivery(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="slack-sent-failure-race",
            source="iCloud",
            transcript="The provider receipt wins over a concurrent late failure.",
        )
        delivery_id = transcript_log.get_pending_slack_deliveries(
            transcript_id=row_id
        )[0]["id"]
        update_barrier = threading.Barrier(2)
        sent_committed = threading.Event()
        real_get_conn = transcript_log._get_conn

        class OrderedRaceConnection:
            def __init__(
                self,
                connection: sqlite3.Connection,
                role: str,
            ) -> None:
                self.connection = connection
                self.role = role

            def execute(self, sql: str, parameters: object = ()) -> object:
                if sql.lstrip().startswith("UPDATE slack_deliveries"):
                    update_barrier.wait(timeout=5)
                    if self.role == "failure":
                        self.assert_sent_committed()
                return self.connection.execute(sql, parameters)

            def assert_sent_committed(self) -> None:
                if not sent_committed.wait(timeout=5):
                    raise AssertionError("sent transition did not commit")

            def commit(self) -> None:
                self.connection.commit()
                if self.role == "sent":
                    sent_committed.set()

            def __getattr__(self, name: str) -> object:
                return getattr(self.connection, name)

        errors: list[Exception] = []
        errors_lock = threading.Lock()

        def run_sent() -> None:
            try:
                transcript_log.mark_slack_delivery_chunk_sent(
                    delivery_id,
                    chunk_index=0,
                    chunk_count=1,
                    provider_ts="race.sent",
                )
            except Exception as exc:
                with errors_lock:
                    errors.append(exc)

        def run_failure() -> None:
            try:
                transcript_log.mark_slack_delivery_failed(
                    delivery_id,
                    "delivery_error",
                )
            except Exception as exc:
                with errors_lock:
                    errors.append(exc)

        def get_race_connection() -> OrderedRaceConnection:
            role = "failure" if threading.current_thread().name == "failure" else "sent"
            return OrderedRaceConnection(real_get_conn(), role)

        with patch.object(
            transcript_log,
            "_get_conn",
            side_effect=get_race_connection,
        ):
            sent_thread = threading.Thread(target=run_sent, name="sent")
            failure_thread = threading.Thread(target=run_failure, name="failure")
            sent_thread.start()
            failure_thread.start()
            sent_thread.join(timeout=5)
            failure_thread.join(timeout=5)

        self.assertFalse(sent_thread.is_alive())
        self.assertFalse(failure_thread.is_alive())
        self.assertEqual(errors, [])
        conn = transcript_log._get_conn()
        try:
            stored = dict(
                conn.execute(
                    """
                    SELECT status, provider_ts, attempt_count,
                           chunk_attempt_count, last_error
                    FROM slack_deliveries
                    WHERE id = ?
                    """,
                    (delivery_id,),
                ).fetchone()
            )
        finally:
            conn.close()
        self.assertEqual(
            stored,
            {
                "status": "sent",
                "provider_ts": "race.sent",
                "attempt_count": 0,
                "chunk_attempt_count": 0,
                "last_error": None,
            },
        )

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

    def test_maya_delivery_health_reports_due_backoff_failed_and_quality_counts(
        self,
    ) -> None:
        due_id = transcript_log.insert_transcript(
            content_hash="maya-health-due",
            source="iCloud",
            transcript="due now",
            ingest_state="transcribed",
            recorded_at="2026-07-28T10:00:00Z",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        backoff_id = transcript_log.insert_transcript(
            content_hash="maya-health-backoff",
            source="iCloud",
            transcript="retry later",
            ingest_state="transcribed",
            recorded_at="2026-07-28T10:01:00Z",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        failed_id = transcript_log.insert_transcript(
            content_hash="maya-health-failed",
            source="iCloud",
            transcript="failed permanently",
            ingest_state="transcribed",
            recorded_at="2026-07-28T10:02:00Z",
            maya_delivery_eligible=True,
            enqueue_slack=False,
        )
        transcript_log.insert_transcript(
            content_hash="maya-health-review",
            source="iCloud",
            transcript="review this",
            ingest_state="needs_review",
            quality_status="needs_review",
            quality_detail="attempt_1=repetition;attempt_2=control_token",
            enqueue_slack=False,
        )
        transcript_log.mark_maya_delivery_retryable(
            int(backoff_id),
            "delivery_error",
            retry_after_seconds=120,
        )
        transcript_log.mark_maya_delivery_failed(
            int(failed_id),
            "provider_error",
        )
        conn = transcript_log._get_conn()
        try:
            conn.execute(
                "UPDATE transcripts SET created_at = datetime('now', '-120 seconds') "
                "WHERE id = ?",
                (due_id,),
            )
            conn.commit()
        finally:
            conn.close()

        health = transcript_log.get_maya_delivery_health()

        self.assertEqual(health["pending_count"], 2)
        self.assertEqual(health["due_count"], 1)
        self.assertEqual(health["failed_count"], 1)
        self.assertGreaterEqual(health["oldest_due_age_seconds"], 119)
        self.assertLessEqual(health["oldest_due_age_seconds"], 180)
        self.assertEqual(health["quality_needs_review_count"], 1)
        self.assertEqual(health["health_error"], 0)

    def test_maya_delivery_health_surfaces_query_failure(self) -> None:
        with patch.object(
            transcript_log,
            "_get_conn",
            side_effect=sqlite3.OperationalError("secret database detail"),
        ):
            health = transcript_log.get_maya_delivery_health()

        self.assertEqual(
            health,
            {
                "pending_count": 0,
                "due_count": 0,
                "failed_count": 0,
                "dead_letter_count": 0,
                "oldest_due_age_seconds": 0,
                "oldest_pending_age_seconds": 0,
                "max_attempt_count": 0,
                "quality_needs_review_count": 0,
                "query_ok": 0,
                "health_error": 1,
            },
        )

    def test_maya_health_probe_does_not_read_transcript_body(self) -> None:
        source = inspect.getsource(transcript_log.get_maya_delivery_health)
        self.assertNotIn("TRIM(transcript)", source)
        self.assertNotIn("LOWER(TRIM(transcript))", source)

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
        self.assertTrue(transcript_log.link_voice_memo_transcript(
            101,
            transcript_row_id=row_id,
            content_hash="hash101",
            audio_path="/tmp/memo.m4a",
        ))
        transcript_log.mark_voice_memo_routed_for_transcript(row_id)

        health = transcript_log.get_voice_memo_health()
        self.assertEqual(health["latest_recording_pk"], 101)
        self.assertEqual(health["awaiting_file_count"], 0)

    def test_unlinked_discovered_and_awaiting_rows_without_deadlines_are_due(self) -> None:
        transcript_log.upsert_voice_memo_recording(
            280, label="discovered", raw_path="280.m4a", duration_seconds=1.0
        )
        transcript_log.upsert_voice_memo_recording(
            281, label="awaiting", raw_path="281.m4a", duration_seconds=1.0
        )
        transcript_log.mark_voice_memo_waiting_for_file(281)

        due = transcript_log.get_voice_memo_recordings_for_retry(
            now="2026-08-09T00:00:00Z", limit=10
        )

        self.assertEqual([row["recording_pk"] for row in due], [280, 281])

    def test_link_voice_memo_transcript_reports_failed_update(self) -> None:
        self.assertFalse(
            transcript_log.link_voice_memo_transcript(
                999,
                transcript_row_id=1,
                content_hash="missing",
                audio_path="missing.m4a",
            )
        )

    def test_terminal_voice_memo_states_preserve_semantics_and_health(self) -> None:
        for pk, state in ((282, "needs_review"), (283, "skipped_too_large"), (284, "routed")):
            transcript_log.upsert_voice_memo_recording(
                pk, label=state, raw_path=f"{pk}.m4a", duration_seconds=1.0
            )
            transcript_log.mark_voice_memo_terminal(pk, state)

        for _ in range(8):
            transcript_log.upsert_voice_memo_recording(
                285, label="exhausted", raw_path="285.m4a", duration_seconds=1.0
            )
            transcript_log.mark_voice_memo_retryable(
                285, "transcription_failed", now="2026-08-09T00:00:00Z"
            )

        conn = transcript_log._get_conn()
        try:
            statuses = dict(
                conn.execute(
                    "SELECT recording_pk, status FROM voice_memo_ingest "
                    "WHERE recording_pk BETWEEN 282 AND 284"
                ).fetchall()
            )
        finally:
            conn.close()
        health = transcript_log.get_voice_memo_health()
        self.assertEqual(statuses, {282: "needs_review", 283: "skipped_too_large", 284: "routed"})
        self.assertEqual(health["terminal_failure_count"], 1)
        self.assertEqual(health["max_attempt_count"], 1)
        self.assertEqual(health["source_watermark"], 0)

    def test_failed_voice_row_remains_retryable_after_watermark_advance(self) -> None:
        transcript_log.upsert_voice_memo_recording(
            293,
            label="retry me",
            raw_path="retry-293.m4a",
            duration_seconds=12.0,
            recorded_at="2026-08-08T23:00:00Z",
        )
        transcript_log.mark_voice_memo_retryable(
            293, "transcription_failed", now="2026-08-09T00:00:00Z"
        )
        self.assertTrue(transcript_log.advance_source_watermark("voice_memos", 400))

        due = transcript_log.get_voice_memo_recordings_for_retry(
            now="2026-08-10T00:00:00Z", limit=10
        )

        self.assertEqual([row["recording_pk"] for row in due], [293])

    def test_terminal_quality_row_is_not_retranscribed(self) -> None:
        transcript_log.upsert_voice_memo_recording(
            294,
            label="review terminal",
            raw_path="review-294.m4a",
            duration_seconds=8.0,
        )
        row_id = transcript_log.insert_transcript(
            content_hash="review-294",
            source="iCloud",
            transcript="needs review",
            ingest_state="needs_review",
            quality_status="needs_review",
            enqueue_slack=False,
        )
        transcript_log.link_voice_memo_transcript(
            294,
            transcript_row_id=int(row_id),
            content_hash="review-294",
            audio_path="review-294.m4a",
        )
        transcript_log.mark_voice_memo_terminal(294, "needs_review")

        due = transcript_log.get_voice_memo_recordings_for_retry(
            now="2026-08-10T00:00:00Z", limit=10
        )

        self.assertNotIn(294, [row["recording_pk"] for row in due])

    def test_voice_memo_retry_uses_bounded_exponential_backoff(self) -> None:
        transcript_log.upsert_voice_memo_recording(
            295, label="retry", raw_path="retry-295.m4a", duration_seconds=1.0
        )
        transcript_log.mark_voice_memo_retryable(
            295, "transcription_failed", now="2026-08-09T00:00:00Z"
        )
        first = transcript_log.get_voice_memo_recordings_for_retry(
            now="2026-08-09T00:00:29Z", limit=10
        )
        self.assertEqual(first, [])
        due = transcript_log.get_voice_memo_recordings_for_retry(
            now="2026-08-09T00:00:30Z", limit=10
        )
        self.assertEqual([row["attempt_count"] for row in due], [1])

        for attempt in range(2, 8):
            transcript_log.mark_voice_memo_retryable(
                295, "transcription_failed", now="2026-08-10T00:00:00Z"
            )
            row = transcript_log.get_voice_memo_recordings_for_retry(
                now="2026-08-11T00:00:00Z", limit=10
            )[0]
            self.assertEqual(row["attempt_count"], attempt)

        transcript_log.mark_voice_memo_retryable(
            295, "transcription_failed", now="2026-08-12T00:00:00Z"
        )
        self.assertEqual(
            transcript_log.get_voice_memo_recordings_for_retry(
                now="2026-08-13T00:00:00Z", limit=10
            ),
            [],
        )

    def test_voice_memo_health_counts_same_day_iso_due_rows(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        due_at = (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        future_at = (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        for pk, next_attempt_at in ((297, due_at), (298, future_at)):
            transcript_log.upsert_voice_memo_recording(
                pk, label="health", raw_path=f"{pk}.m4a", duration_seconds=1.0
            )
            conn = transcript_log._get_conn()
            try:
                conn.execute(
                    """UPDATE voice_memo_ingest
                       SET retryable = 1, attempt_count = 1, next_attempt_at = ?
                       WHERE recording_pk = ?""",
                    (next_attempt_at, pk),
                )
                conn.commit()
            finally:
                conn.close()

        due = transcript_log.get_voice_memo_recordings_for_retry(
            now=now.isoformat().replace("+00:00", "Z"), limit=10
        )
        health = transcript_log.get_voice_memo_health()

        self.assertEqual([row["recording_pk"] for row in due], [297])
        self.assertEqual(health["retry_due_count"], 1)

    def test_source_watermark_is_monotonic(self) -> None:
        self.assertEqual(transcript_log.get_source_watermark("voice_memos"), 0)
        self.assertTrue(transcript_log.advance_source_watermark("voice_memos", 42))
        self.assertFalse(transcript_log.advance_source_watermark("voice_memos", 41))
        self.assertEqual(transcript_log.get_source_watermark("voice_memos"), 42)

    def test_legacy_cursor_migrates_once_and_sqlite_remains_authoritative(self) -> None:
        legacy_cursor = Path(self.db_dir) / "last_pk.txt"
        legacy_cursor.write_text("777", encoding="utf-8")
        new_db = Path(self.db_dir) / "migrated.db"
        with (
            patch.object(transcript_log, "TRANSCRIPT_DB_PATH", new_db),
            patch.object(transcript_log, "LEGACY_VOICE_MEMO_CURSOR_PATH", legacy_cursor),
        ):
            transcript_log.init_db()
            self.assertEqual(transcript_log.get_source_watermark("voice_memos"), 777)
            legacy_cursor.write_text("999", encoding="utf-8")
            transcript_log.init_db()
            self.assertEqual(transcript_log.get_source_watermark("voice_memos"), 777)

    def test_legacy_unlinked_failed_voice_row_is_due_for_retry(self) -> None:
        transcript_log.upsert_voice_memo_recording(
            296, label="legacy", raw_path="legacy.m4a", duration_seconds=1.0
        )
        conn = transcript_log._get_conn()
        try:
            conn.execute(
                "UPDATE voice_memo_ingest SET status = 'failed', retryable = 0, "
                "next_attempt_at = NULL WHERE recording_pk = 296"
            )
            conn.commit()
        finally:
            conn.close()
        transcript_log.init_db()

        due = transcript_log.get_voice_memo_recordings_for_retry(
            now="2100-01-01T00:00:00Z", limit=10
        )

        self.assertEqual([row["recording_pk"] for row in due], [296])

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
