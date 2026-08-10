"""
Test that sqlite3 connections are properly closed.

This catches the bug where `with sqlite3.connect()` was used incorrectly -
it only manages transactions, not connection lifecycle.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["HOME"] = "/tmp/penny_test_home"
os.environ["OPENROUTER_API_KEY"] = "test-key"

# Don't import watcher until after env is set


class SQLiteConnectionLeakTests(unittest.TestCase):
    """Verify sqlite3 connections are closed properly."""

    def test_typed_transcript_insert_closes_connections_on_all_database_paths(self):
        """Typed insert preserves closure for new, duplicate, and failed writes."""
        import transcript_log

        class TrackingConnection:
            def __init__(self, connection):
                self.connection = connection
                self.closed = False

            def __getattr__(self, name):
                return getattr(self.connection, name)

            def close(self):
                self.closed = True
                self.connection.close()

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "transcripts.db"
            with patch.object(transcript_log, "TRANSCRIPT_DB_PATH", db_path):
                transcript_log.init_db()
                real_get_conn = transcript_log._get_conn
                connections = []

                def tracked_get_conn():
                    connection = TrackingConnection(real_get_conn())
                    connections.append(connection)
                    return connection

                with patch.object(transcript_log, "_get_conn", tracked_get_conn):
                    inserted = transcript_log.insert_transcript_result(
                        content_hash="close-inserted", source="test", transcript="first"
                    )
                    duplicate = transcript_log.insert_transcript_result(
                        content_hash="close-inserted", source="test", transcript="first"
                    )

                self.assertEqual(inserted.outcome.value, "inserted")
                self.assertEqual(duplicate.outcome.value, "duplicate")
                self.assertTrue(connections)
                self.assertTrue(all(connection.closed for connection in connections))

                failed_connection = TrackingConnection(real_get_conn())
                with patch.object(
                    transcript_log,
                    "_get_conn",
                    return_value=failed_connection,
                ), patch.object(
                    failed_connection,
                    "execute",
                    side_effect=sqlite3.OperationalError("locked"),
                ):
                    failed = transcript_log.insert_transcript_result(
                        content_hash="close-failed", source="test", transcript="never stored"
                    )

                self.assertEqual(failed.outcome.value, "failed")
                self.assertTrue(failed_connection.closed)

    def test_connections_closed_after_query(self):
        """Each query should close its connection, not leak it."""
        # Create a temp database that looks like CloudRecordings.db
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "CloudRecordings.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE ZCLOUDRECORDING (
                    Z_PK INTEGER PRIMARY KEY,
                    ZCUSTOMLABEL TEXT,
                    ZDATE REAL,
                    ZDURATION REAL,
                    ZPATH TEXT
                )
            """)
            conn.execute("INSERT INTO ZCLOUDRECORDING VALUES (1, 'Test', 0, 1.0, 'test.m4a')")
            conn.commit()
            conn.close()

            # Patch the db path in watcher
            import watcher
            original_db = watcher.CLOUDRECORDINGS_DB
            watcher.CLOUDRECORDINGS_DB = db_path

            try:
                # Run many queries - if connections leak, db will be locked
                for _ in range(50):
                    result = watcher.get_new_recordings()
                    self.assertEqual(len(result), 1)

                # If connections were leaked, this will fail with "database is locked"
                # because Windows/SQLite won't let you delete an open database
                conn2 = sqlite3.connect(str(db_path))
                conn2.execute("INSERT INTO ZCLOUDRECORDING VALUES (2, 'Test2', 0, 1.0, 'test2.m4a')")
                conn2.commit()
                conn2.close()

            finally:
                watcher.CLOUDRECORDINGS_DB = original_db

    def test_get_recordings_by_pk_refreshes_existing_metadata(self):
        """Already-seen recordings can be refreshed after ZPATH appears later."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "CloudRecordings.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE ZCLOUDRECORDING (
                    Z_PK INTEGER PRIMARY KEY,
                    ZCUSTOMLABEL TEXT,
                    ZDATE REAL,
                    ZDURATION REAL,
                    ZPATH TEXT
                )
            """)
            conn.execute(
                "INSERT INTO ZCLOUDRECORDING VALUES (7, 'Late path', 0, 12.5, 'late.m4a')"
            )
            conn.commit()
            conn.close()

            import watcher
            original_db = watcher.CLOUDRECORDINGS_DB
            watcher.CLOUDRECORDINGS_DB = db_path

            try:
                result = watcher.get_recordings_by_pk([7])
                self.assertEqual(result[7]["ZPATH"], "late.m4a")
                self.assertEqual(result[7]["ZDURATION"], 12.5)
            finally:
                watcher.CLOUDRECORDINGS_DB = original_db

    def test_retry_waiting_for_files_uses_refreshed_cloudrecordings_row(self):
        """Retry should not keep using stale empty raw_path from local ingest state."""
        import watcher

        stale = {
            "recording_pk": 7,
            "label": "Late path",
            "raw_path": "",
            "duration_seconds": None,
        }
        fresh = {
            "Z_PK": 7,
            "ZCUSTOMLABEL": "Late path",
            "ZDATE": 0,
            "ZDURATION": 12.5,
            "ZPATH": "late.m4a",
        }

        with patch.object(
            watcher, "get_voice_memo_recordings_waiting_for_file", return_value=[stale]
        ), patch.object(
            watcher, "get_recordings_by_pk", return_value={7: fresh}
        ), patch.object(
            watcher, "upsert_voice_memo_recording"
        ) as upsert_mock, patch.object(
            watcher, "process_recording"
        ) as process_mock:
            watcher._retry_waiting_for_files(limit=5)

        upsert_mock.assert_called_once_with(
            7,
            label="Late path",
            raw_path="late.m4a",
            duration_seconds=12.5,
            recorded_at="2001-01-01T00:00:00Z",
        )
        process_mock.assert_called_once_with(fresh)

    def test_process_audio_file_links_already_logged_voice_memo(self):
        """A refreshed waiting row should leave ingest state linked when hash exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "late.m4a"
            audio_path.write_bytes(b"audio")

            import watcher

            with patch.object(watcher, "get_file_hash", return_value="hash7"), patch.object(
                watcher,
                "get_transcript_by_hash",
                return_value={"id": 9, "status": "routed"},
            ), patch.object(
                watcher, "mark_voice_memo_file_seen"
            ) as file_seen_mock, patch.object(
                watcher, "link_voice_memo_transcript"
            ) as link_mock, patch.object(
                watcher, "transcribe_with_quality"
            ) as transcribe_mock:
                result = watcher._process_audio_file(audio_path, recording_pk=7)

            self.assertTrue(result)
            transcribe_mock.assert_not_called()
            file_seen_mock.assert_called_once_with(7, str(audio_path))
            link_mock.assert_called_once_with(
                7,
                transcript_row_id=9,
                content_hash="hash7",
                audio_path=str(audio_path),
                routed=True,
            )

    def test_db_recordings_count_closes_connection(self):
        """_db_recordings_count should close its connection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "CloudRecordings.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE ZCLOUDRECORDING (Z_PK INTEGER PRIMARY KEY)
            """)
            conn.execute("INSERT INTO ZCLOUDRECORDING VALUES (1)")
            conn.execute("INSERT INTO ZCLOUDRECORDING VALUES (2)")
            conn.commit()
            conn.close()

            import watcher
            original_db = watcher.CLOUDRECORDINGS_DB
            watcher.CLOUDRECORDINGS_DB = db_path

            try:
                # Run many times
                for _ in range(100):
                    count = watcher._db_recordings_count()
                    self.assertEqual(count, 2)

                # Should still be able to write (not locked)
                conn2 = sqlite3.connect(str(db_path))
                conn2.execute("INSERT INTO ZCLOUDRECORDING VALUES (3)")
                conn2.commit()
                conn2.close()

            finally:
                watcher.CLOUDRECORDINGS_DB = original_db


if __name__ == "__main__":
    unittest.main()
