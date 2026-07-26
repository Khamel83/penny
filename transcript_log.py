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
import os
import sqlite3
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

TRANSCRIPT_DB_PATH = Path("~/.penny/transcripts.db").expanduser()
DEFAULT_SLACK_CHANNEL_ID = "C0BKS0QT7FU"

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
                duration_seconds REAL,
                status          TEXT NOT NULL DEFAULT 'pending',
                ingest_state    TEXT,
                routing_result  TEXT,
                routing_progress TEXT,
                error_message   TEXT,
                discovered_at   TEXT,
                file_seen_at    TEXT,
                transcription_started_at TEXT,
                transcription_completed_at TEXT,
                routing_started_at TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
                last_error_at   TEXT,
                routed_at       TEXT,
                routed_to       TEXT
            )
        """)
        _ensure_transcript_columns(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_transcripts_status ON transcripts(status)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_memo_ingest (
                recording_pk INTEGER PRIMARY KEY,
                label TEXT,
                raw_path TEXT,
                duration_seconds REAL,
                audio_path TEXT,
                content_hash TEXT,
                transcript_row_id INTEGER,
                status TEXT NOT NULL DEFAULT 'discovered',
                error_message TEXT,
                file_missing_count INTEGER NOT NULL DEFAULT 0,
                discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
                file_seen_at TEXT,
                transcribed_at TEXT,
                routed_at TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(transcript_row_id) REFERENCES transcripts(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_voice_memo_ingest_status ON voice_memo_ingest(status)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS slack_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_row_id INTEGER NOT NULL,
                channel_id TEXT NOT NULL,
                message_text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                sent_at TEXT,
                UNIQUE(transcript_row_id),
                FOREIGN KEY(transcript_row_id) REFERENCES transcripts(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_slack_deliveries_status ON slack_deliveries(status)"
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


def _ensure_transcript_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(transcripts)").fetchall()
    }
    required_columns = {
        "duration_seconds": "ALTER TABLE transcripts ADD COLUMN duration_seconds REAL",
        "ingest_state": "ALTER TABLE transcripts ADD COLUMN ingest_state TEXT",
        "routing_progress": "ALTER TABLE transcripts ADD COLUMN routing_progress TEXT",
        "discovered_at": "ALTER TABLE transcripts ADD COLUMN discovered_at TEXT",
        "file_seen_at": "ALTER TABLE transcripts ADD COLUMN file_seen_at TEXT",
        "transcription_started_at": "ALTER TABLE transcripts ADD COLUMN transcription_started_at TEXT",
        "transcription_completed_at": "ALTER TABLE transcripts ADD COLUMN transcription_completed_at TEXT",
        "routing_started_at": "ALTER TABLE transcripts ADD COLUMN routing_started_at TEXT",
        "updated_at": "ALTER TABLE transcripts ADD COLUMN updated_at TEXT",
        "last_error_at": "ALTER TABLE transcripts ADD COLUMN last_error_at TEXT",
    }
    for column, sql in required_columns.items():
        if column not in existing:
            conn.execute(sql)


def _json_loads_or_default(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _slack_channel_id() -> str:
    return (
        os.environ.get("PENNY_SLACK_CHANNEL_ID")
        or os.environ.get("SLACK_CHANNEL_ID")
        or DEFAULT_SLACK_CHANNEL_ID
    )


def _queue_slack_delivery(
    conn: sqlite3.Connection,
    *,
    transcript_row_id: int,
    source: str,
    transcript: str,
    ingest_state: str | None,
) -> None:
    if source != "iCloud" or ingest_state == "skipped_too_large":
        return
    conn.execute(
        """INSERT OR IGNORE INTO slack_deliveries (
               transcript_row_id, channel_id, message_text
           )
           VALUES (?, ?, ?)""",
        (transcript_row_id, _slack_channel_id(), transcript),
    )


def insert_transcript(
    content_hash: str,
    source: str,
    transcript: str,
    audio_path: str | None = None,
    duration_seconds: float | None = None,
    ingest_state: str | None = None,
    discovered_at: str | None = None,
    file_seen_at: str | None = None,
    transcription_started_at: str | None = None,
    transcription_completed_at: str | None = None,
) -> int | None:
    """Insert a transcript. Returns row id if new, None if duplicate."""
    conn = None
    try:
        conn = _get_conn()
        cursor = conn.execute(
            """INSERT OR IGNORE INTO transcripts (
                   content_hash, source, transcript, audio_path,
                   duration_seconds, ingest_state, discovered_at, file_seen_at,
                   transcription_started_at, transcription_completed_at
               )
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                content_hash,
                source,
                transcript,
                audio_path,
                duration_seconds,
                ingest_state,
                discovered_at,
                file_seen_at,
                transcription_started_at,
                transcription_completed_at,
            ),
        )
        if cursor.lastrowid and cursor.rowcount > 0:
            _queue_slack_delivery(
                conn,
                transcript_row_id=int(cursor.lastrowid),
                source=source,
                transcript=transcript,
                ingest_state=ingest_state,
            )
            conn.commit()
            log.debug(
                "Logged transcript id=%s hash=%s source=%s (%d chars)",
                cursor.lastrowid,
                content_hash[:12],
                source,
                len(transcript),
            )
            return cursor.lastrowid
        conn.commit()
        return None
    except Exception as e:
        log.error("Failed to insert transcript: %s", e)
        return None
    finally:
        if conn:
            conn.close()


def get_pending_slack_deliveries(limit: int = 20) -> list[dict[str, Any]]:
    conn = None
    try:
        conn = _get_conn()
        rows = conn.execute(
            """SELECT *
               FROM slack_deliveries
               WHERE status IN ('pending', 'failed')
               ORDER BY created_at ASC, id ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        log.error("Failed to fetch pending Slack deliveries: %s", e)
        return []
    finally:
        if conn:
            conn.close()


def mark_slack_delivery_sent(delivery_id: int) -> None:
    conn = None
    try:
        conn = _get_conn()
        conn.execute(
            """UPDATE slack_deliveries
               SET status = 'sent',
                   last_error = NULL,
                   sent_at = datetime('now'),
                   updated_at = datetime('now')
               WHERE id = ?""",
            (delivery_id,),
        )
        conn.commit()
    except Exception as e:
        log.error("Failed to mark Slack delivery sent id=%s: %s", delivery_id, e)
    finally:
        if conn:
            conn.close()


def mark_slack_delivery_failed(delivery_id: int, error_message: str) -> None:
    conn = None
    try:
        conn = _get_conn()
        conn.execute(
            """UPDATE slack_deliveries
               SET status = 'failed',
                   attempt_count = attempt_count + 1,
                   last_error = ?,
                   updated_at = datetime('now')
               WHERE id = ?""",
            (error_message, delivery_id),
        )
        conn.commit()
    except Exception as e:
        log.error("Failed to mark Slack delivery failed id=%s: %s", delivery_id, e)
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


def get_transcript_by_hash(content_hash: str) -> dict[str, Any] | None:
    """Fetch a transcript row by content hash."""
    conn = None
    try:
        conn = _get_conn()
        row = conn.execute(
            """SELECT id, content_hash, source, transcript, audio_path, status,
                      duration_seconds, routing_result, routed_at, routed_to
               FROM transcripts
               WHERE content_hash = ?""",
            (content_hash,),
        ).fetchone()
        return dict(row) if row else None
    except Exception as e:
        log.error("Failed to fetch transcript by hash: %s", e)
        return None
    finally:
        if conn:
            conn.close()


def get_pending(limit: int = 20) -> list[dict]:
    """Fetch transcripts with status='pending' or 'failed', oldest first."""
    conn = None
    try:
        conn = _get_conn()
        rows = conn.execute(
            """SELECT id, content_hash, source, transcript, audio_path, duration_seconds,
                      discovered_at, file_seen_at, transcription_started_at,
                      transcription_completed_at, routing_started_at,
                      routing_progress, routing_result
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
                   ingest_state = 'routed',
                   routing_result = ?,
                   error_message = NULL,
                   routed_at = datetime('now'),
                   routed_to = ?,
                   updated_at = datetime('now')
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
               SET status = 'failed',
                   ingest_state = 'failed',
                   error_message = ?,
                   last_error_at = datetime('now'),
                   updated_at = datetime('now')
                WHERE id = ?""",
            (error_message, row_id),
        )
        conn.commit()
    except Exception as e:
        log.error("Failed to mark failed id=%s: %s", row_id, e)
    finally:
        if conn:
            conn.close()


def get_transcript(row_id: int) -> dict[str, Any] | None:
    conn = None
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM transcripts WHERE id = ?",
            (row_id,),
        ).fetchone()
        return dict(row) if row else None
    except Exception as e:
        log.error("Failed to get transcript id=%s: %s", row_id, e)
        return None
    finally:
        if conn:
            conn.close()


def update_transcript_progress(row_id: int, patch: dict[str, Any]) -> None:
    conn = None
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT routing_progress FROM transcripts WHERE id = ?",
            (row_id,),
        ).fetchone()
        progress = _json_loads_or_default(row[0] if row else None, {})
        progress.update(patch)
        conn.execute(
            """UPDATE transcripts
               SET routing_progress = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (json.dumps(progress, default=str), row_id),
        )
        conn.commit()
    except Exception as e:
        log.error("Failed to update routing progress id=%s: %s", row_id, e)
    finally:
        if conn:
            conn.close()


def update_transcript_stages(
    row_id: int,
    *,
    ingest_state: str | None = None,
    audio_path: str | None = None,
    duration_seconds: float | None = None,
    discovered_at: str | None = None,
    file_seen_at: str | None = None,
    transcription_started_at: str | None = None,
    transcription_completed_at: str | None = None,
    routing_started_at: str | None = None,
) -> None:
    updates: list[str] = []
    params: list[Any] = []

    def add(field: str, value: Any) -> None:
        updates.append(f"{field} = ?")
        params.append(value)

    if ingest_state is not None:
        add("ingest_state", ingest_state)
    if audio_path is not None:
        add("audio_path", audio_path)
    if duration_seconds is not None:
        add("duration_seconds", duration_seconds)
    if discovered_at is not None:
        add("discovered_at", discovered_at)
    if file_seen_at is not None:
        add("file_seen_at", file_seen_at)
    if transcription_started_at is not None:
        add("transcription_started_at", transcription_started_at)
    if transcription_completed_at is not None:
        add("transcription_completed_at", transcription_completed_at)
    if routing_started_at is not None:
        add("routing_started_at", routing_started_at)

    if not updates:
        return

    conn = None
    try:
        conn = _get_conn()
        updates.append("updated_at = datetime('now')")
        params.append(row_id)
        conn.execute(
            f"UPDATE transcripts SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
    except Exception as e:
        log.error("Failed to update transcript stages id=%s: %s", row_id, e)
    finally:
        if conn:
            conn.close()


def upsert_voice_memo_recording(
    recording_pk: int,
    *,
    label: str,
    raw_path: str,
    duration_seconds: float | None,
) -> None:
    conn = None
    try:
        conn = _get_conn()
        conn.execute(
            """INSERT INTO voice_memo_ingest (
                   recording_pk, label, raw_path, duration_seconds,
                   status, discovered_at, last_seen_at, updated_at
               )
               VALUES (?, ?, ?, ?, 'discovered', datetime('now'), datetime('now'), datetime('now'))
               ON CONFLICT(recording_pk) DO UPDATE SET
                   label = excluded.label,
                   raw_path = excluded.raw_path,
                   duration_seconds = excluded.duration_seconds,
                   last_seen_at = datetime('now'),
                   updated_at = datetime('now')""",
            (recording_pk, label, raw_path, duration_seconds),
        )
        conn.commit()
    except Exception as e:
        log.error("Failed to upsert voice memo state pk=%s: %s", recording_pk, e)
    finally:
        if conn:
            conn.close()


def mark_voice_memo_waiting_for_file(
    recording_pk: int, error_message: str | None = None
) -> None:
    conn = None
    try:
        conn = _get_conn()
        conn.execute(
            """UPDATE voice_memo_ingest
               SET status = 'awaiting_file',
                   error_message = ?,
                   file_missing_count = file_missing_count + 1,
                   updated_at = datetime('now')
               WHERE recording_pk = ?""",
            (error_message, recording_pk),
        )
        conn.commit()
    except Exception as e:
        log.error("Failed to mark voice memo awaiting file pk=%s: %s", recording_pk, e)
    finally:
        if conn:
            conn.close()


def mark_voice_memo_file_seen(recording_pk: int, audio_path: str) -> None:
    conn = None
    try:
        conn = _get_conn()
        conn.execute(
            """UPDATE voice_memo_ingest
               SET status = 'file_ready',
                   audio_path = ?,
                   file_seen_at = COALESCE(file_seen_at, datetime('now')),
                   error_message = NULL,
                   updated_at = datetime('now')
               WHERE recording_pk = ?""",
            (audio_path, recording_pk),
        )
        conn.commit()
    except Exception as e:
        log.error("Failed to mark voice memo file seen pk=%s: %s", recording_pk, e)
    finally:
        if conn:
            conn.close()


def link_voice_memo_transcript(
    recording_pk: int,
    *,
    transcript_row_id: int,
    content_hash: str,
    audio_path: str,
    routed: bool = False,
) -> None:
    conn = None
    try:
        conn = _get_conn()
        status = "routed" if routed else "transcribed"
        routed_sql = ", routed_at = datetime('now')" if routed else ""
        conn.execute(
            f"""UPDATE voice_memo_ingest
                SET transcript_row_id = ?,
                    content_hash = ?,
                    audio_path = ?,
                    status = ?,
                    transcribed_at = datetime('now'),
                    error_message = NULL,
                    updated_at = datetime('now')
                    {routed_sql}
                WHERE recording_pk = ?""",
            (transcript_row_id, content_hash, audio_path, status, recording_pk),
        )
        conn.commit()
    except Exception as e:
        log.error("Failed to link voice memo transcript pk=%s: %s", recording_pk, e)
    finally:
        if conn:
            conn.close()


def mark_voice_memo_routed(recording_pk: int) -> None:
    conn = None
    try:
        conn = _get_conn()
        conn.execute(
            """UPDATE voice_memo_ingest
               SET status = 'routed', routed_at = datetime('now'), error_message = NULL,
                   updated_at = datetime('now')
               WHERE recording_pk = ?""",
            (recording_pk,),
        )
        conn.commit()
    except Exception as e:
        log.error("Failed to mark voice memo routed pk=%s: %s", recording_pk, e)
    finally:
        if conn:
            conn.close()


def mark_voice_memo_routed_for_transcript(transcript_row_id: int) -> None:
    conn = None
    try:
        conn = _get_conn()
        conn.execute(
            """UPDATE voice_memo_ingest
               SET status = 'routed', routed_at = datetime('now'), error_message = NULL,
                   updated_at = datetime('now')
               WHERE transcript_row_id = ?""",
            (transcript_row_id,),
        )
        conn.commit()
    except Exception as e:
        log.error(
            "Failed to mark voice memo routed for transcript id=%s: %s",
            transcript_row_id,
            e,
        )
    finally:
        if conn:
            conn.close()


def mark_voice_memo_failed(recording_pk: int, error_message: str) -> None:
    conn = None
    try:
        conn = _get_conn()
        conn.execute(
            """UPDATE voice_memo_ingest
               SET status = 'failed', error_message = ?, updated_at = datetime('now')
               WHERE recording_pk = ?""",
            (error_message, recording_pk),
        )
        conn.commit()
    except Exception as e:
        log.error("Failed to mark voice memo failed pk=%s: %s", recording_pk, e)
    finally:
        if conn:
            conn.close()


def get_voice_memo_recordings_waiting_for_file(limit: int = 20) -> list[dict[str, Any]]:
    conn = None
    try:
        conn = _get_conn()
        rows = conn.execute(
            """SELECT * FROM voice_memo_ingest
               WHERE status IN ('discovered', 'awaiting_file')
                  OR (status = 'file_ready' AND transcript_row_id IS NULL)
               ORDER BY discovered_at ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        log.error("Failed to fetch waiting voice memos: %s", e)
        return []
    finally:
        if conn:
            conn.close()


def get_voice_memo_health() -> dict[str, Any]:
    conn = None
    health = {
        "latest_recording_pk": 0,
        "awaiting_file_count": 0,
        "failed_count": 0,
        "oldest_waiting_discovered_at": None,
    }
    try:
        conn = _get_conn()
        latest = conn.execute(
            "SELECT MAX(recording_pk) FROM voice_memo_ingest"
        ).fetchone()
        health["latest_recording_pk"] = int(latest[0] or 0)

        awaiting = conn.execute(
            "SELECT COUNT(*), MIN(discovered_at) FROM voice_memo_ingest WHERE status IN ('discovered', 'awaiting_file')"
        ).fetchone()
        health["awaiting_file_count"] = int(awaiting[0] or 0)
        health["oldest_waiting_discovered_at"] = awaiting[1] if awaiting else None

        failed = conn.execute(
            "SELECT COUNT(*) FROM voice_memo_ingest WHERE status = 'failed'"
        ).fetchone()
        health["failed_count"] = int(failed[0] or 0)
        return health
    except Exception as e:
        log.error("Failed to fetch voice memo health: %s", e)
        return health
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
