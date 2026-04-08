#!/usr/bin/env python3
"""
Canonical transcript log — the single source of truth for all transcriptions.

Every voice memo, webhook upload, and text ingestion is recorded here with
its transcript text, source, and routing status. This replaces the old
processed.txt / processed_webhook.txt / synced_tasks.txt dedup files.

The log serves two purposes:
1. Deduplication (content_hash UNIQUE constraint)
2. Persistence (full transcript saved before routing, so nothing is lost)
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

TRANSCRIPT_DB_PATH = Path("~/.penny/transcripts.db").expanduser()

_MIGRATION_SOURCES = [
    (Path("~/.penny/processed.txt").expanduser(), "iCloud"),
    (Path("~/.penny/processed_webhook.txt").expanduser(), "Shortcut"),
    (Path("~/.penny/synced_tasks.txt").expanduser(), "Google Tasks"),
]


def init_db() -> None:
    """Create tables and run one-time migration from old processed files."""
    TRANSCRIPT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = None
    try:
        conn = sqlite3.connect(str(TRANSCRIPT_DB_PATH), timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transcripts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                content_hash    TEXT NOT NULL UNIQUE,
                source          TEXT NOT NULL,
                transcript      TEXT NOT NULL,
                audio_path      TEXT,
                status          TEXT NOT NULL DEFAULT 'pending',
                routing_result  TEXT,
                error_message   TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                routed_at       TEXT,
                routed_to       TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_transcripts_status ON transcripts(status)"
        )
        conn.commit()

        migrated = _migrate_processed_files(conn)
        if migrated:
            conn.commit()
            log.info("Migrated %d entries from old processed files", migrated)

    finally:
        if conn:
            conn.close()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(TRANSCRIPT_DB_PATH), timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def insert_transcript(
    content_hash: str,
    source: str,
    transcript: str,
    audio_path: str | None = None,
) -> int | None:
    """Insert a transcript. Returns row id if new, None if duplicate."""
    conn = None
    try:
        conn = _get_conn()
        cursor = conn.execute(
            """INSERT OR IGNORE INTO transcripts (content_hash, source, transcript, audio_path)
               VALUES (?, ?, ?, ?)""",
            (content_hash, source, transcript, audio_path),
        )
        conn.commit()
        if cursor.lastrowid and cursor.rowcount > 0:
            log.debug(
                "Logged transcript id=%s hash=%s source=%s (%d chars)",
                cursor.lastrowid,
                content_hash[:12],
                source,
                len(transcript),
            )
            return cursor.lastrowid
        return None
    except Exception as e:
        log.error("Failed to insert transcript: %s", e)
        return None
    finally:
        if conn:
            conn.close()


def is_already_logged(content_hash: str) -> bool:
    """Check if a content hash exists in the transcript log."""
    conn = None
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT 1 FROM transcripts WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        return row is not None
    except Exception as e:
        log.error("Failed to check transcript log: %s", e)
        return False
    finally:
        if conn:
            conn.close()


def get_pending(limit: int = 20) -> list[dict]:
    """Fetch transcripts with status='pending' or 'failed', oldest first."""
    conn = None
    try:
        conn = _get_conn()
        rows = conn.execute(
            """SELECT id, content_hash, source, transcript, audio_path
               FROM transcripts
               WHERE status IN ('pending', 'failed')
               ORDER BY created_at ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        log.error("Failed to fetch pending transcripts: %s", e)
        return []
    finally:
        if conn:
            conn.close()


def mark_routed(row_id: int, routing_result: dict, routed_to: str) -> None:
    """Mark a transcript as successfully routed."""
    conn = None
    try:
        conn = _get_conn()
        conn.execute(
            """UPDATE transcripts
               SET status = 'routed',
                   routing_result = ?,
                   routed_at = datetime('now'),
                   routed_to = ?
               WHERE id = ?""",
            (json.dumps(routing_result, default=str), routed_to, row_id),
        )
        conn.commit()
    except Exception as e:
        log.error("Failed to mark routed id=%s: %s", row_id, e)
    finally:
        if conn:
            conn.close()


def mark_failed(row_id: int, error_message: str) -> None:
    """Mark a transcript as failed routing."""
    conn = None
    try:
        conn = _get_conn()
        conn.execute(
            """UPDATE transcripts
               SET status = 'failed', error_message = ?
               WHERE id = ?""",
            (error_message, row_id),
        )
        conn.commit()
    except Exception as e:
        log.error("Failed to mark failed id=%s: %s", row_id, e)
    finally:
        if conn:
            conn.close()


def _migrate_processed_files(conn: sqlite3.Connection) -> int:
    """Import hashes from old processed.txt files into the transcript log."""
    migrated = 0
    for path, source in _MIGRATION_SOURCES:
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            log.warning("Could not read migration source %s: %s", path, e)
            continue

        for line in lines:
            hash_val = line.strip()
            if not hash_val:
                continue
            try:
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO transcripts (content_hash, source, transcript, status)
                       VALUES (?, ?, ?, 'routed')""",
                    (
                        hash_val,
                        source,
                        "(migrated — original transcript not preserved)",
                    ),
                )
                if cursor.rowcount > 0:
                    migrated += 1
            except Exception:
                pass
    return migrated
