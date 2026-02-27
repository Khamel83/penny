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
