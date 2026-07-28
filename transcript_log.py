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

import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

TRANSCRIPT_DB_PATH = Path("~/.penny/transcripts.db").expanduser()
DEFAULT_SLACK_CHANNEL_ID = "C0BKS0QT7FU"
SLACK_MAX_ATTEMPTS = 5
SLACK_API_ERROR_CODES = frozenset(
    {
        "channel_not_found",
        "fatal_error",
        "internal_error",
        "invalid_auth",
        "missing_scope",
        "not_authed",
        "not_in_channel",
        "rate_limited",
        "ratelimited",
        "request_timeout",
        "restricted_action",
        "service_unavailable",
        "token_expired",
        "token_revoked",
    }
)
_SAFE_DELIVERY_ERROR_VALUES = SLACK_API_ERROR_CODES | {
    "configuration_error",
    "destination_mismatch",
    "delivery_error",
    "message_truncated",
    "provider_warning",
    "slack_api_error",
}
_SAFE_CLASSIFIED_ERROR_RE = re.compile(
    r"(?:provider|acknowledgement)_error:[A-Za-z][A-Za-z0-9_]{0,47}"
)
_SAFE_EXCEPTION_CLASS_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,47}")

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
        conn.execute("BEGIN IMMEDIATE")
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
                routed_to       TEXT,
                quality_status  TEXT NOT NULL DEFAULT 'passed',
                quality_detail  TEXT,
                transcript_sha256 TEXT,
                maya_delivery_status TEXT NOT NULL DEFAULT 'pending',
                maya_drop_id    TEXT,
                maya_delivery_error TEXT,
                superseded_by_transcript_row_id INTEGER
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
                next_attempt_at TEXT,
                last_error TEXT,
                provider_ts TEXT,
                next_chunk_index INTEGER NOT NULL DEFAULT 0,
                chunk_attempt_count INTEGER NOT NULL DEFAULT 0,
                chunk_provider_ts TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                sent_at TEXT,
                UNIQUE(transcript_row_id),
                FOREIGN KEY(transcript_row_id) REFERENCES transcripts(id)
            )
            """
        )
        added_slack_columns = _ensure_slack_delivery_columns(conn)
        _migrate_slack_delivery_rows(conn, added_columns=added_slack_columns)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_slack_deliveries_due "
            "ON slack_deliveries(status, next_attempt_at)"
        )
        conn.commit()

        migrated = _migrate_processed_files(conn)
        if migrated:
            conn.commit()
            log.info("Migrated %d entries from old processed files", migrated)

    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(TRANSCRIPT_DB_PATH), timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column_if_missing(
    conn: sqlite3.Connection,
    *,
    table: str,
    column: str,
    sql: str,
) -> bool:
    existing = _table_columns(conn, table)
    if column in existing:
        return False

    try:
        conn.execute(sql)
    except sqlite3.OperationalError as original_error:
        try:
            existing = _table_columns(conn, table)
        except sqlite3.OperationalError:
            raise original_error from None
        if column in existing:
            return False
        raise
    return True


def _rename_column_if_present(
    conn: sqlite3.Connection,
    *,
    table: str,
    old_column: str,
    new_column: str,
) -> bool:
    existing = _table_columns(conn, table)
    if new_column in existing or old_column not in existing:
        return False

    try:
        conn.execute(
            f"ALTER TABLE {table} RENAME COLUMN {old_column} TO {new_column}"
        )
    except sqlite3.OperationalError as original_error:
        try:
            existing = _table_columns(conn, table)
        except sqlite3.OperationalError:
            raise original_error from None
        if new_column in existing and old_column not in existing:
            return False
        raise
    return True


def _ensure_unique_index(
    conn: sqlite3.Connection,
    *,
    table: str,
    index: str,
    column: str,
) -> None:
    matching = next(
        (
            row
            for row in conn.execute(f"PRAGMA index_list({table})").fetchall()
            if row[1] == index
        ),
        None,
    )
    if matching is not None:
        if int(matching[2]) != 1 or (len(matching) > 4 and int(matching[4]) != 0):
            raise sqlite3.IntegrityError(
                f"{index} must be a non-partial unique index on {table}"
            )
        indexed_columns = [
            row[2] for row in conn.execute(f"PRAGMA index_info({index})").fetchall()
        ]
        if indexed_columns != [column]:
            raise sqlite3.IntegrityError(
                f"{index} must cover only {table}.{column}"
            )
        return

    conn.execute(
        f"CREATE UNIQUE INDEX {index} ON {table}({column})"
    )


def _ensure_transcript_columns(conn: sqlite3.Connection) -> None:
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
        "quality_status": (
            "ALTER TABLE transcripts "
            "ADD COLUMN quality_status TEXT NOT NULL DEFAULT 'passed'"
        ),
        "quality_detail": "ALTER TABLE transcripts ADD COLUMN quality_detail TEXT",
        "transcript_sha256": "ALTER TABLE transcripts ADD COLUMN transcript_sha256 TEXT",
        "maya_delivery_status": (
            "ALTER TABLE transcripts "
            "ADD COLUMN maya_delivery_status TEXT NOT NULL DEFAULT 'pending'"
        ),
        "maya_drop_id": "ALTER TABLE transcripts ADD COLUMN maya_drop_id TEXT",
        "maya_delivery_error": (
            "ALTER TABLE transcripts ADD COLUMN maya_delivery_error TEXT"
        ),
        "superseded_by_transcript_row_id": (
            "ALTER TABLE transcripts "
            "ADD COLUMN superseded_by_transcript_row_id INTEGER"
        ),
    }
    for column, sql in required_columns.items():
        _add_column_if_missing(
            conn,
            table="transcripts",
            column=column,
            sql=sql,
        )

    rows = conn.execute(
        "SELECT id, transcript FROM transcripts WHERE transcript_sha256 IS NULL"
    ).fetchall()
    conn.executemany(
        "UPDATE transcripts SET transcript_sha256 = ? WHERE id = ?",
        [
            (hashlib.sha256(str(row[1]).encode("utf-8")).hexdigest(), row[0])
            for row in rows
        ],
    )


def _json_loads_or_default(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _safe_exception_class(exc: Exception) -> str:
    class_name = type(exc).__name__
    if _SAFE_EXCEPTION_CLASS_RE.fullmatch(class_name):
        return class_name
    return "Exception"


def _safe_delivery_error(error_message: str) -> str:
    if (
        error_message in _SAFE_DELIVERY_ERROR_VALUES
        or _SAFE_CLASSIFIED_ERROR_RE.fullmatch(error_message)
    ):
        return error_message
    return "delivery_error"


def _as_iso8601_utc(value: object) -> str:
    """Normalize a persisted capture timestamp for the Maya v2 contract."""
    try:
        captured_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Persisted capture timestamp is invalid") from exc
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    return captured_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _slack_channel_id() -> str:
    """Return Penny's only allowed transcript destination."""
    return DEFAULT_SLACK_CHANNEL_ID


def _ensure_slack_delivery_columns(conn: sqlite3.Connection) -> set[str]:
    _rename_column_if_present(
        conn,
        table="slack_deliveries",
        old_column="transcript_id",
        new_column="transcript_row_id",
    )
    columns = _table_columns(conn, "slack_deliveries")
    if {"transcript_id", "transcript_row_id"}.issubset(columns):
        raise sqlite3.IntegrityError(
            "slack_deliveries has conflicting transcript identity columns"
        )

    required_columns = {
        "transcript_row_id": (
            "ALTER TABLE slack_deliveries ADD COLUMN transcript_row_id INTEGER"
        ),
        "next_attempt_at": "ALTER TABLE slack_deliveries ADD COLUMN next_attempt_at TEXT",
        "provider_ts": "ALTER TABLE slack_deliveries ADD COLUMN provider_ts TEXT",
        "sent_at": "ALTER TABLE slack_deliveries ADD COLUMN sent_at TEXT",
        "channel_id": (
            "ALTER TABLE slack_deliveries ADD COLUMN channel_id TEXT "
            f"NOT NULL DEFAULT '{DEFAULT_SLACK_CHANNEL_ID}'"
        ),
        "message_text": (
            "ALTER TABLE slack_deliveries ADD COLUMN message_text TEXT NOT NULL DEFAULT ''"
        ),
        "next_chunk_index": (
            "ALTER TABLE slack_deliveries "
            "ADD COLUMN next_chunk_index INTEGER NOT NULL DEFAULT 0"
        ),
        "chunk_attempt_count": (
            "ALTER TABLE slack_deliveries "
            "ADD COLUMN chunk_attempt_count INTEGER NOT NULL DEFAULT 0"
        ),
        "chunk_provider_ts": (
            "ALTER TABLE slack_deliveries "
            "ADD COLUMN chunk_provider_ts TEXT NOT NULL DEFAULT '[]'"
        ),
    }
    added: set[str] = set()
    for column, sql in required_columns.items():
        if _add_column_if_missing(
            conn,
            table="slack_deliveries",
            column=column,
            sql=sql,
        ):
            added.add(column)

    _ensure_unique_index(
        conn,
        table="slack_deliveries",
        index="idx_slack_deliveries_transcript_row_id",
        column="transcript_row_id",
    )
    return added


def _migrate_slack_delivery_rows(
    conn: sqlite3.Connection,
    *,
    added_columns: set[str],
) -> None:
    """Normalize legacy outbox rows without reopening terminal failures."""
    orphan_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM slack_deliveries AS deliveries
        LEFT JOIN transcripts
          ON transcripts.id = deliveries.transcript_row_id
        WHERE transcripts.id IS NULL
        """
    ).fetchone()[0]
    if orphan_count:
        raise sqlite3.IntegrityError(
            f"slack_deliveries contains {orphan_count} orphan transcript reference(s)"
        )

    conn.execute(
        """
        UPDATE slack_deliveries
        SET message_text = (
                SELECT transcripts.transcript
                FROM transcripts
                WHERE transcripts.id = slack_deliveries.transcript_row_id
            ),
            updated_at = datetime('now')
        WHERE (message_text IS NULL OR message_text = '')
          AND EXISTS (
                SELECT 1
                FROM transcripts
                WHERE transcripts.id = slack_deliveries.transcript_row_id
            )
        """
    )

    if "chunk_attempt_count" in added_columns:
        conn.execute(
            """
            UPDATE slack_deliveries
            SET chunk_attempt_count = attempt_count
            WHERE status IN ('pending', 'failed')
              AND attempt_count > 0
            """
        )

    conn.execute(
        """
        UPDATE slack_deliveries
        SET channel_id = ?,
            updated_at = datetime('now')
        WHERE status != 'sent'
          AND channel_id != ?
        """,
        (DEFAULT_SLACK_CHANNEL_ID, DEFAULT_SLACK_CHANNEL_ID),
    )
    conn.execute(
        """
        UPDATE slack_deliveries
        SET status = 'pending',
            next_attempt_at = datetime('now'),
            updated_at = datetime('now')
        WHERE status = 'failed'
          AND attempt_count < ?
        """,
        (SLACK_MAX_ATTEMPTS,),
    )
    conn.execute(
        """
        UPDATE slack_deliveries
        SET next_attempt_at = NULL
        WHERE status = 'failed'
          AND attempt_count >= ?
        """,
        (SLACK_MAX_ATTEMPTS,),
    )


def _should_queue_slack_delivery(
    *,
    source: str,
    ingest_state: str | None,
    quality_status: str,
    enqueue_slack: bool,
) -> bool:
    return (
        enqueue_slack
        and source == "iCloud"
        and ingest_state != "skipped_too_large"
        and quality_status == "passed"
    )


def _queue_slack_delivery(
    conn: sqlite3.Connection,
    *,
    transcript_row_id: int,
    source: str,
    transcript: str,
    ingest_state: str | None,
    quality_status: str,
    enqueue_slack: bool,
) -> None:
    if not _should_queue_slack_delivery(
        source=source,
        ingest_state=ingest_state,
        quality_status=quality_status,
        enqueue_slack=enqueue_slack,
    ):
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
    error_message: str | None = None,
    quality_status: str | None = None,
    quality_detail: str | None = None,
    enqueue_slack: bool = True,
) -> int | None:
    """Insert a transcript. Returns row id if new, None if duplicate."""
    if quality_status is None:
        quality_status = "needs_review" if ingest_state == "needs_review" else "passed"
    transcript_sha256 = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    conn = None
    try:
        conn = _get_conn()
        cursor = conn.execute(
            """INSERT OR IGNORE INTO transcripts (
                   content_hash, source, transcript, audio_path,
                   duration_seconds, ingest_state, discovered_at, file_seen_at,
                   transcription_started_at, transcription_completed_at, error_message,
                   quality_status, quality_detail, transcript_sha256
               )
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                error_message,
                quality_status,
                quality_detail,
                transcript_sha256,
            ),
        )
        if cursor.lastrowid and cursor.rowcount > 0:
            _queue_slack_delivery(
                conn,
                transcript_row_id=int(cursor.lastrowid),
                source=source,
                transcript=transcript,
                ingest_state=ingest_state,
                quality_status=quality_status,
                enqueue_slack=enqueue_slack,
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


def queue_slack_delivery(transcript_id: int) -> None:
    conn = None
    try:
        conn = _get_conn()
        row = conn.execute(
            """
            SELECT source, transcript, ingest_state, quality_status
            FROM transcripts
            WHERE id = ?
            """,
            (transcript_id,),
        ).fetchone()
        if row is None:
            return
        _queue_slack_delivery(
            conn,
            transcript_row_id=transcript_id,
            source=str(row["source"]),
            transcript=str(row["transcript"]),
            ingest_state=row["ingest_state"],
            quality_status=str(row["quality_status"]),
            enqueue_slack=True,
        )
        conn.commit()
    except Exception as e:
        log.error("Failed to queue Slack delivery transcript=%s: %s", transcript_id, e)
    finally:
        if conn:
            conn.close()


def get_pending_slack_deliveries(
    limit: int = 20,
    transcript_id: int | None = None,
    *,
    routed_only: bool = False,
) -> list[dict[str, Any]]:
    conn = None
    try:
        conn = _get_conn()
        clauses = [
            "deliveries.status = 'pending'",
            "transcripts.quality_status = 'passed'",
            (
                "(deliveries.next_attempt_at IS NULL "
                "OR deliveries.next_attempt_at <= datetime('now'))"
            ),
        ]
        params: list[Any] = []
        if routed_only:
            clauses.append("transcripts.ingest_state = 'routed'")
        if transcript_id is not None:
            clauses.append("deliveries.transcript_row_id = ?")
            params.append(transcript_id)
        params.append(limit)
        rows = conn.execute(
            f"""SELECT deliveries.id, deliveries.transcript_row_id,
                       deliveries.channel_id, deliveries.message_text,
                       deliveries.status, deliveries.attempt_count,
                       deliveries.next_attempt_at, deliveries.last_error,
                       deliveries.provider_ts, deliveries.next_chunk_index,
                       deliveries.chunk_attempt_count,
                       deliveries.chunk_provider_ts, deliveries.created_at,
                       deliveries.updated_at, deliveries.sent_at
                FROM slack_deliveries AS deliveries
                LEFT JOIN transcripts
                  ON transcripts.id = deliveries.transcript_row_id
                WHERE {' AND '.join(clauses)}
                ORDER BY deliveries.created_at ASC, deliveries.id ASC
                LIMIT ?""",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        log.error("Failed to fetch pending Slack deliveries: %s", e)
        return []
    finally:
        if conn:
            conn.close()


def mark_slack_delivery_sent(delivery_id: int, provider_ts: str | None = None) -> None:
    conn = None
    try:
        conn = _get_conn()
        conn.execute(
            """UPDATE slack_deliveries
               SET status = 'sent',
                   last_error = NULL,
                   provider_ts = ?,
                   next_attempt_at = NULL,
                   chunk_attempt_count = 0,
                   sent_at = datetime('now'),
                   updated_at = datetime('now')
               WHERE id = ?""",
            (provider_ts, delivery_id),
        )
        conn.commit()
    except Exception as e:
        log.error(
            "Failed to mark Slack delivery sent id=%s: %s",
            delivery_id,
            _safe_exception_class(e),
        )
        raise
    finally:
        if conn:
            conn.close()


def mark_slack_delivery_failed(
    delivery_id: int,
    error_message: str,
    retry_after_seconds: int = 60,
) -> None:
    conn = None
    try:
        conn = _get_conn()
        safe_error = _safe_delivery_error(error_message)
        current = conn.execute(
            """
            SELECT attempt_count, chunk_attempt_count
            FROM slack_deliveries
            WHERE id = ?
            """,
            (delivery_id,),
        ).fetchone()
        attempt_count = int(current["attempt_count"]) + 1 if current else 1
        chunk_attempt_count = (
            int(current["chunk_attempt_count"]) + 1 if current else 1
        )
        terminal = chunk_attempt_count >= SLACK_MAX_ATTEMPTS
        delay = max(1, int(retry_after_seconds))
        conn.execute(
            """UPDATE slack_deliveries
               SET status = ?,
                   attempt_count = ?,
                   chunk_attempt_count = ?,
                   last_error = ?,
                   next_attempt_at = CASE
                       WHEN ? THEN NULL
                       ELSE datetime('now', '+' || ? || ' seconds')
                   END,
                   updated_at = datetime('now')
               WHERE id = ?""",
            (
                "failed" if terminal else "pending",
                attempt_count,
                chunk_attempt_count,
                safe_error,
                1 if terminal else 0,
                delay,
                delivery_id,
            ),
        )
        conn.commit()
    except Exception as e:
        log.error(
            "Failed to mark Slack delivery failed id=%s: %s",
            delivery_id,
            _safe_exception_class(e),
        )
        raise
    finally:
        if conn:
            conn.close()


def mark_slack_delivery_chunk_sent(
    delivery_id: int,
    *,
    chunk_index: int,
    chunk_count: int,
    provider_ts: str | None,
) -> None:
    """Persist one accepted chunk and mark the delivery sent only when complete."""
    conn = None
    try:
        conn = _get_conn()
        current = conn.execute(
            """
            SELECT next_chunk_index, chunk_provider_ts
            FROM slack_deliveries
            WHERE id = ?
            """,
            (delivery_id,),
        ).fetchone()
        if current is None:
            raise LookupError("Slack delivery row does not exist")

        next_chunk_index = int(current["next_chunk_index"] or 0)
        if next_chunk_index > chunk_index:
            return
        if next_chunk_index != chunk_index:
            raise ValueError("Slack chunk acknowledgement is out of order")

        timestamps = _json_loads_or_default(current["chunk_provider_ts"], [])
        if not isinstance(timestamps, list):
            timestamps = []
        timestamps.append(provider_ts)
        following_chunk = chunk_index + 1
        complete = following_chunk >= chunk_count
        conn.execute(
            """
            UPDATE slack_deliveries
            SET status = ?,
                next_chunk_index = ?,
                chunk_attempt_count = 0,
                chunk_provider_ts = ?,
                provider_ts = ?,
                last_error = NULL,
                next_attempt_at = NULL,
                sent_at = CASE WHEN ? THEN datetime('now') ELSE sent_at END,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                "sent" if complete else "pending",
                following_chunk,
                json.dumps(timestamps),
                provider_ts,
                1 if complete else 0,
                delivery_id,
            ),
        )
        conn.commit()
    except Exception as e:
        log.error(
            "Failed to record Slack chunk id=%s: %s",
            delivery_id,
            _safe_exception_class(e),
        )
        raise
    finally:
        if conn:
            conn.close()


def build_maya_v2_envelope(transcript_row_id: int) -> dict[str, object]:
    """Build the exact Penny-to-Maya v2 payload from one persisted row."""
    conn = None
    try:
        conn = _get_conn()
        conn.execute("BEGIN")
        row = conn.execute(
            """
            SELECT transcripts.id, transcripts.content_hash, transcripts.source,
                   transcripts.transcript, transcripts.audio_path,
                   transcripts.duration_seconds, transcripts.discovered_at,
                   transcripts.file_seen_at, transcripts.created_at,
                   transcripts.transcript_sha256, transcripts.quality_status,
                   transcripts.ingest_state,
                   (
                       SELECT recording_pk
                       FROM voice_memo_ingest
                       WHERE transcript_row_id = transcripts.id
                       ORDER BY recording_pk ASC
                       LIMIT 1
                   ) AS recording_pk
            FROM transcripts
            WHERE transcripts.id = ?
            """,
            (transcript_row_id,),
        ).fetchone()
        conn.rollback()
        if row is None:
            raise LookupError("Transcript row does not exist")
        if row["quality_status"] != "passed":
            raise ValueError("Only passed transcripts can be delivered to Maya")
        if row["ingest_state"] == "needs_review":
            raise ValueError("Only passed transcripts can be delivered to Maya")
        if str(row["source"]).lower().startswith("maya:"):
            raise ValueError("Maya-originated transcripts cannot be delivered to Maya")

        transcript = str(row["transcript"])
        transcript_sha256 = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
        persisted_sha256 = row["transcript_sha256"]
        if persisted_sha256 != transcript_sha256:
            raise ValueError("Persisted transcript SHA-256 does not match transcript bytes")
        captured_at = _as_iso8601_utc(
            row["discovered_at"] or row["file_seen_at"] or row["created_at"]
        )
        return {
            "schema_version": "penny-maya.v2",
            "transcript_id": str(row["id"]),
            "transcript_sha256": transcript_sha256,
            "transcript": transcript,
            "source": str(row["source"]).lower(),
            "captured_at": captured_at,
            "duration_seconds": row["duration_seconds"],
            "audio_provenance": {
                "content_hash": str(row["content_hash"]),
                "audio_path": None,
                "recording_pk": row["recording_pk"],
            },
            "source_spans": [],
            "client_ref": f"penny:{row['id']}",
        }
    finally:
        if conn:
            conn.close()


def get_pending_maya_deliveries(limit: int = 20) -> list[dict[str, Any]]:
    """Return eligible transcript rows that have not reached Maya durably."""
    conn = None
    try:
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT *
            FROM transcripts
            WHERE maya_delivery_status = 'pending'
              AND quality_status = 'passed'
              AND source NOT LIKE 'maya:%'
              AND COALESCE(ingest_state, '') != 'needs_review'
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        log.error("Failed to fetch pending Maya deliveries: %s", _safe_exception_class(e))
        return []
    finally:
        if conn:
            conn.close()


def mark_maya_delivery_sent(transcript_row_id: int, drop_id: str) -> None:
    """Persist Maya's durable receipt, accepting only exact Drop replays."""
    if not drop_id:
        raise ValueError("Maya Drop ID is required")
    conn = None
    try:
        conn = _get_conn()
        cursor = conn.execute(
            """
            UPDATE transcripts
            SET maya_delivery_status = 'sent',
                maya_drop_id = ?,
                maya_delivery_error = NULL,
                updated_at = datetime('now')
            WHERE id = ?
              AND (
                    (maya_delivery_status IN ('pending', 'failed')
                     AND maya_drop_id IS NULL)
                    OR (maya_delivery_status = 'sent' AND maya_drop_id = ?)
                  )
            """,
            (drop_id, transcript_row_id, drop_id),
        )
        if cursor.rowcount == 0:
            current = conn.execute(
                "SELECT maya_delivery_status, maya_drop_id FROM transcripts WHERE id = ?",
                (transcript_row_id,),
            ).fetchone()
            if current is None:
                raise LookupError("Transcript row does not exist")
            if current["maya_drop_id"] not in (None, drop_id):
                raise ValueError("Maya Drop ID conflicts with the durable receipt")
            raise ValueError("Maya receipt cannot transition the current delivery state")
        conn.commit()
    except Exception as e:
        log.error(
            "Failed to mark Maya delivery sent id=%s: %s",
            transcript_row_id,
            _safe_exception_class(e),
        )
        raise
    finally:
        if conn:
            conn.close()


def mark_maya_delivery_failed(transcript_row_id: int, error_message: str) -> None:
    """Persist a bounded Maya delivery failure without changing Slack state."""
    conn = None
    try:
        conn = _get_conn()
        cursor = conn.execute(
            """
            UPDATE transcripts
            SET maya_delivery_status = 'failed',
                maya_delivery_error = ?,
                updated_at = datetime('now')
            WHERE id = ?
              AND maya_delivery_status != 'sent'
              AND maya_drop_id IS NULL
            """,
            (_safe_delivery_error(error_message), transcript_row_id),
        )
        if cursor.rowcount == 0:
            current = conn.execute(
                "SELECT maya_delivery_status, maya_drop_id FROM transcripts WHERE id = ?",
                (transcript_row_id,),
            ).fetchone()
            if current is None:
                raise LookupError("Transcript row does not exist")
            if current["maya_delivery_status"] == "sent" or current["maya_drop_id"]:
                return
            raise ValueError("Maya failure cannot transition the current delivery state")
        conn.commit()
    except Exception as e:
        log.error(
            "Failed to mark Maya delivery failed id=%s: %s",
            transcript_row_id,
            _safe_exception_class(e),
        )
        raise
    finally:
        if conn:
            conn.close()


def get_slack_delivery_health() -> dict[str, int]:
    conn = None
    health = {
        "pending_count": 0,
        "sent_count": 0,
        "failed_count": 0,
        "health_error": 0,
    }
    try:
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM slack_deliveries
            GROUP BY status
            """
        ).fetchall()
        for row in rows:
            status = str(row["status"])
            count = int(row["count"])
            if status == "pending":
                health["pending_count"] = count
            elif status == "sent":
                health["sent_count"] = count
            elif status == "failed":
                health["failed_count"] = count
        return health
    except Exception as e:
        log.error(
            "Failed to fetch Slack delivery health: %s",
            _safe_exception_class(e),
        )
        health["health_error"] = 1
        return health
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
    """Fetch routable pending or failed transcripts, oldest first."""
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
                 AND COALESCE(ingest_state, '') != 'needs_review'
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


def mark_routed(row_id: int, routing_result: dict, routed_to: str) -> bool:
    """Mark a transcript as successfully routed."""
    conn = None
    try:
        conn = _get_conn()
        cursor = conn.execute(
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
        return cursor.rowcount > 0
    except Exception as e:
        log.error("Failed to mark routed id=%s: %s", row_id, e)
        return False
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


def update_transcript_progress(row_id: int, patch: dict[str, Any]) -> bool:
    conn = None
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT routing_progress FROM transcripts WHERE id = ?",
            (row_id,),
        ).fetchone()
        progress = _json_loads_or_default(row[0] if row else None, {})
        progress.update(patch)
        cursor = conn.execute(
            """UPDATE transcripts
               SET routing_progress = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (json.dumps(progress, default=str), row_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        log.error("Failed to update routing progress id=%s: %s", row_id, e)
        return False
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
                transcript = "(migrated — original transcript not preserved)"
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO transcripts (
                        content_hash, source, transcript, status, transcript_sha256
                    ) VALUES (?, ?, ?, 'routed', ?)
                    """,
                    (
                        hash_val,
                        source,
                        transcript,
                        hashlib.sha256(transcript.encode("utf-8")).hexdigest(),
                    ),
                )
                if cursor.rowcount > 0:
                    migrated += 1
            except Exception:
                pass
    return migrated
