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
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

TRANSCRIPT_DB_PATH = Path("~/.penny/transcripts.db").expanduser()
DEFAULT_SLACK_CHANNEL_ID = "C0BKS0QT7FU"
SLACK_MAX_ATTEMPTS = 5
SLACK_HTTP_TIMEOUT_SECONDS = 10
SLACK_CLAIM_LEASE_MARGIN_SECONDS = 5
SLACK_CLAIM_LEASE_SECONDS = 30
QUALITY_FAILURE_CONTENT_KIND = "transcript_quality_failure"
QUALITY_FAILURE_DESTINATION = "maya-ledger"
MAX_QUALITY_DETAIL_CHARACTERS = 255
VOICE_MEMO_MAX_ATTEMPTS = 8
ARCHIVE_MAX_ATTEMPTS = 5
MAYA_MAX_ATTEMPTS = 20
MAYA_MAX_AGE_DAYS = 7
# Descriptive aliases retained for callers that prefer the delivery namespace.
MAYA_DELIVERY_MAX_ATTEMPTS = MAYA_MAX_ATTEMPTS
MAYA_DELIVERY_MAX_AGE_DAYS = MAYA_MAX_AGE_DAYS
MAYA_CLAIM_LEASE_SECONDS = 120
MAYA_DEAD_LETTER_REASONS = frozenset(
    {
        "attempt_cap",
        "age_cap",
        "invalid_schedule",
        "operator_replay",
        "delivery_error",
    }
)
VOICE_MEMO_RETRY_ERROR_CODES = frozenset(
    {
        "file_not_downloaded",
        "file_too_large",
        "needs_review",
        "persistence_failed",
        "processing_error",
        "routed",
        "skipped_too_large",
        "source_changed",
        "transcription_failed",
    }
)
LEGACY_VOICE_MEMO_CURSOR_PATH = Path("~/.penny/last_pk.txt").expanduser()
SLACK_DELIVERY_PLAN_LEGACY_TOP_LEVEL_V1 = "legacy_top_level_v1"
SLACK_DELIVERY_PLAN_BLOCK_KIT_V2 = "block_kit_v2"
SLACK_LEGACY_PARTIAL_RECONCILIATION_ERROR = (
    "legacy_partial_reconciliation_required"
)
APPLE_EFFECT_STATES = frozenset(
    {"reserved", "in_flight", "uncertain", "succeeded", "failed", "quarantined"}
)
APPLE_EFFECT_TYPES = frozenset({"note", "reminder"})
APPLE_EFFECT_LEASE_SECONDS = 120
APPLE_EFFECT_SAFE_ERROR_CODES = frozenset(
    {
        "provider_error",
        "permission_denied",
        "timeout_uncertain",
        "database_unavailable",
        "marker_conflict",
        "provider_conflict",
        "canonical_id_required",
        "invalid_effect",
        "effect_not_found",
        "active_claim",
        "effect_key_conflict",
        "migration_invalid_state",
    }
)
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
    "provider_response_error",
    "provider_warning",
    "slack_api_error",
    SLACK_LEGACY_PARTIAL_RECONCILIATION_ERROR,
}
_SAFE_CLASSIFIED_ERROR_RE = re.compile(
    r"(?:(?:provider|acknowledgement)_error|uncertain_delivery):"
    r"[A-Za-z][A-Za-z0-9_]{0,47}"
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
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
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
                recorded_at     TEXT,
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
                quality_status  TEXT NOT NULL DEFAULT 'pending',
                quality_detail  TEXT,
                transcript_sha256 TEXT,
                audio_sha256   TEXT,
                transcription_backend TEXT,
                transcription_model TEXT,
                maya_delivery_status TEXT NOT NULL DEFAULT 'ineligible',
                maya_delivery_eligible INTEGER NOT NULL DEFAULT 0,
                maya_drop_id    TEXT,
                maya_delivery_error TEXT,
                maya_delivery_attempt_count INTEGER NOT NULL DEFAULT 0,
                maya_next_attempt_at TEXT,
                maya_first_attempt_at TEXT,
                maya_last_attempt_at TEXT,
                maya_dead_letter_at TEXT,
                maya_dead_letter_reason TEXT,
                maya_claim_token TEXT,
                maya_claim_owner TEXT,
                maya_claimed_at TEXT,
                maya_claim_expires_at TEXT,
                superseded_by_transcript_row_id INTEGER
            )
        """)
        _ensure_transcript_columns(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_transcripts_status ON transcripts(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_transcripts_maya_delivery_due "
            "ON transcripts(maya_delivery_status, maya_next_attempt_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_memo_ingest (
                recording_pk INTEGER PRIMARY KEY,
                label TEXT,
                raw_path TEXT,
                duration_seconds REAL,
                recorded_at TEXT,
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
        _ensure_voice_memo_columns(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_voice_memo_ingest_status ON voice_memo_ingest(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_voice_memo_ingest_retry_due "
            "ON voice_memo_ingest(retryable, next_attempt_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS source_watermarks (
                source TEXT PRIMARY KEY,
                last_discovered_id INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )
        _migrate_legacy_voice_memo_cursor(conn)
        _migrate_legacy_voice_memo_retry_state(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS slack_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_row_id INTEGER NOT NULL,
                channel_id TEXT NOT NULL,
                message_text TEXT NOT NULL,
                delivery_plan_version TEXT NOT NULL DEFAULT 'block_kit_v2',
                status TEXT NOT NULL DEFAULT 'pending',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT,
                last_error TEXT,
                provider_ts TEXT,
                next_chunk_index INTEGER NOT NULL DEFAULT 0,
                chunk_attempt_count INTEGER NOT NULL DEFAULT 0,
                chunk_provider_ts TEXT NOT NULL DEFAULT '[]',
                slack_claim_token TEXT,
                slack_claim_owner TEXT,
                slack_claimed_at TEXT,
                slack_claim_expires_at TEXT,
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quality_failure_slack_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_row_id INTEGER NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                content_kind TEXT NOT NULL,
                destination TEXT NOT NULL,
                message_text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT,
                last_error TEXT,
                provider_ts TEXT,
                slack_claim_token TEXT,
                slack_claim_owner TEXT,
                slack_claimed_at TEXT,
                slack_claim_expires_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                sent_at TEXT,
                UNIQUE(transcript_row_id, content_kind),
                FOREIGN KEY(transcript_row_id) REFERENCES transcripts(id)
            )
            """
        )
        _ensure_quality_failure_slack_delivery_columns(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_quality_failure_slack_due "
            "ON quality_failure_slack_deliveries(status, next_attempt_at)"
        )
        _ensure_archive_delivery_schema(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_archive_deliveries_due "
            "ON archive_deliveries(status, next_attempt_at)"
        )
        _ensure_apple_effects_schema(conn)
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
    conn.execute("PRAGMA foreign_keys=ON")
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


_ARCHIVE_DELIVERY_COLUMNS = {
    "id",
    "transcript_row_id",
    "local_object_path",
    "audio_sha256",
    "byte_length",
    "extension",
    "archive_source",
    "source_aliases",
    "original_name",
    "recorded_at",
    "ingested_at",
    "archive_duration_seconds",
    "mime_type",
    "status",
    "availability_status",
    "unavailable_reason",
    "attempt_count",
    "next_attempt_at",
    "last_error_code",
    "destination_audio_path",
    "destination_markdown_path",
    "destination_manifest_path",
    "receipt_sha256",
    "publication_scope",
    "publication_generation",
    "alias_set_sha256",
    "validation_status",
    "validation_error_code",
    "last_validated_at",
    "rebuild_needed",
    "created_at",
    "updated_at",
    "published_at",
    "local_mirror_published_at",
}


def _create_archive_delivery_table(
    conn: sqlite3.Connection, table: str = "archive_deliveries"
) -> None:
    conn.execute(
        f"""
        CREATE TABLE {table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transcript_row_id INTEGER NOT NULL UNIQUE,
            local_object_path TEXT,
            audio_sha256 TEXT,
            byte_length INTEGER,
            extension TEXT,
            archive_source TEXT NOT NULL,
            source_aliases TEXT NOT NULL DEFAULT '[]',
            original_name TEXT,
            recorded_at TEXT,
            ingested_at TEXT,
            archive_duration_seconds REAL,
            mime_type TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            availability_status TEXT NOT NULL DEFAULT 'available',
            unavailable_reason TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT,
            last_error_code TEXT,
            destination_audio_path TEXT,
            destination_markdown_path TEXT,
            destination_manifest_path TEXT,
            receipt_sha256 TEXT,
            publication_scope TEXT NOT NULL DEFAULT 'local_mirror',
            publication_generation INTEGER NOT NULL DEFAULT 1,
            alias_set_sha256 TEXT,
            validation_status TEXT NOT NULL DEFAULT 'pending',
            validation_error_code TEXT,
            last_validated_at TEXT,
            rebuild_needed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            published_at TEXT,
            local_mirror_published_at TEXT,
            FOREIGN KEY(transcript_row_id) REFERENCES transcripts(id)
        )
        """
    )


def _archive_schema_is_current(conn: sqlite3.Connection) -> bool:
    if not _ARCHIVE_DELIVERY_COLUMNS.issubset(
        _table_columns(conn, "archive_deliveries")
    ):
        return False
    foreign_keys = conn.execute(
        "PRAGMA foreign_key_list(archive_deliveries)"
    ).fetchall()
    has_foreign_key = any(
        row[2] == "transcripts"
        and row[3] == "transcript_row_id"
        and row[4] == "id"
        for row in foreign_keys
    )
    unique_transcript_index = False
    for index in conn.execute("PRAGMA index_list(archive_deliveries)").fetchall():
        if not int(index[2]) or (len(index) > 4 and int(index[4])):
            continue
        columns = [
            row[2]
            for row in conn.execute(f"PRAGMA index_info({index[1]})").fetchall()
        ]
        if columns == ["transcript_row_id"]:
            unique_transcript_index = True
            break
    return has_foreign_key and unique_transcript_index


def _quarantine_archive_orphans(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT deliveries.*
        FROM archive_deliveries AS deliveries
        LEFT JOIN transcripts ON transcripts.id = deliveries.transcript_row_id
        WHERE transcripts.id IS NULL
        """
    ).fetchall()
    for row in rows:
        snapshot = dict(row)
        conn.execute(
            """
            INSERT INTO archive_delivery_quarantine (
                legacy_delivery_id, transcript_row_id, reason_code, row_snapshot
            ) VALUES (?, ?, 'orphan_transcript', ?)
            """,
            (
                snapshot.get("id"),
                snapshot.get("transcript_row_id"),
                json.dumps(snapshot, default=str, sort_keys=True),
            ),
        )
        conn.execute(
            "DELETE FROM archive_deliveries WHERE id = ?", (snapshot["id"],)
        )


def _ensure_archive_delivery_schema(conn: sqlite3.Connection) -> None:
    legacy_publication_rows: list[dict[str, Any]] = []
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS archive_delivery_quarantine (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            legacy_delivery_id INTEGER,
            transcript_row_id INTEGER,
            reason_code TEXT NOT NULL,
            row_snapshot TEXT NOT NULL,
            quarantined_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    existing_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='archive_deliveries'"
    ).fetchone()
    if existing_table is None:
        _create_archive_delivery_table(conn)
    elif not _archive_schema_is_current(conn):
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='archive_publications'"
        ).fetchone():
            legacy_publication_rows = [
                dict(row) for row in conn.execute("SELECT * FROM archive_publications")
            ]
            conn.execute("DROP TABLE archive_publications")
        legacy_rows = [
            dict(row) for row in conn.execute("SELECT * FROM archive_deliveries")
        ]
        legacy_name = "archive_deliveries_legacy_migration"
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (legacy_name,),
        ).fetchone():
            raise sqlite3.IntegrityError("stale archive migration table")
        conn.execute(f"ALTER TABLE archive_deliveries RENAME TO {legacy_name}")
        _create_archive_delivery_table(conn)
        seen_transcripts: set[int] = set()
        for legacy in legacy_rows:
            raw_transcript_id = legacy.get("transcript_row_id", legacy.get("transcript_id"))
            try:
                transcript_id = int(raw_transcript_id)
            except (TypeError, ValueError):
                transcript_id = 0
            canonical = conn.execute(
                "SELECT source, recorded_at, duration_seconds FROM transcripts WHERE id = ?",
                (transcript_id,),
            ).fetchone()
            reason: str | None = None
            if canonical is None:
                reason = "orphan_transcript"
            elif transcript_id in seen_transcripts:
                reason = "duplicate_transcript"
            if reason is not None:
                conn.execute(
                    """
                    INSERT INTO archive_delivery_quarantine (
                        legacy_delivery_id, transcript_row_id, reason_code, row_snapshot
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        legacy.get("id"),
                        transcript_id or None,
                        reason,
                        json.dumps(legacy, default=str, sort_keys=True),
                    ),
                )
                continue
            seen_transcripts.add(transcript_id)
            local_path = legacy.get("local_object_path")
            audio_sha256 = legacy.get("audio_sha256")
            byte_length = legacy.get("byte_length")
            extension = legacy.get("extension")
            materialized = bool(
                local_path and audio_sha256 and byte_length is not None and extension
            )
            old_status = str(legacy.get("status") or "pending")
            availability = str(
                legacy.get("availability_status")
                or ("available" if materialized else "unavailable")
            )
            status = old_status if materialized else "unavailable"
            validation_status = str(
                legacy.get("validation_status")
                or ("pending" if materialized else "invalid")
            )
            conn.execute(
                """
                INSERT INTO archive_deliveries (
                    id, transcript_row_id, local_object_path, audio_sha256,
                    byte_length, extension, archive_source, source_aliases,
                    original_name, recorded_at, ingested_at,
                    archive_duration_seconds, mime_type, status,
                    availability_status, unavailable_reason, attempt_count,
                    next_attempt_at, last_error_code, destination_audio_path,
                    destination_markdown_path, destination_manifest_path,
                    receipt_sha256, publication_scope, publication_generation,
                    alias_set_sha256, validation_status, validation_error_code,
                    last_validated_at, rebuild_needed, created_at, updated_at,
                    published_at, local_mirror_published_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    COALESCE(?, datetime('now')), COALESCE(?, datetime('now')),
                    ?, ?
                )
                """,
                (
                    legacy.get("id"), transcript_id, local_path, audio_sha256,
                    byte_length, extension,
                    legacy.get("archive_source") or canonical["source"],
                    legacy.get("source_aliases") or "[]",
                    legacy.get("original_name"),
                    legacy.get("recorded_at") or canonical["recorded_at"],
                    legacy.get("ingested_at"),
                    legacy.get("archive_duration_seconds") or canonical["duration_seconds"],
                    legacy.get("mime_type"), status, availability,
                    legacy.get("unavailable_reason")
                    or (None if materialized else "migration_missing_archive_metadata"),
                    int(legacy.get("attempt_count") or 0),
                    legacy.get("next_attempt_at"), legacy.get("last_error_code"),
                    legacy.get("destination_audio_path"),
                    legacy.get("destination_markdown_path"),
                    legacy.get("destination_manifest_path"),
                    legacy.get("receipt_sha256"),
                    legacy.get("publication_scope") or "local_mirror",
                    int(legacy.get("publication_generation") or 1),
                    legacy.get("alias_set_sha256"), validation_status,
                    legacy.get("validation_error_code")
                    or (None if materialized else "migration_missing_archive_metadata"),
                    legacy.get("last_validated_at"),
                    int(legacy.get("rebuild_needed") or (old_status == "published")),
                    legacy.get("created_at"), legacy.get("updated_at"),
                    legacy.get("published_at"),
                    legacy.get("local_mirror_published_at") or legacy.get("published_at"),
                ),
            )
        conn.execute(f"DROP TABLE {legacy_name}")

    _quarantine_archive_orphans(conn)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS archive_publications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            archive_delivery_id INTEGER NOT NULL,
            transcript_row_id INTEGER NOT NULL,
            publication_generation INTEGER NOT NULL,
            alias_set_sha256 TEXT NOT NULL,
            source_aliases TEXT NOT NULL,
            destination_audio_path TEXT NOT NULL,
            destination_markdown_path TEXT NOT NULL,
            destination_manifest_path TEXT NOT NULL,
            receipt_sha256 TEXT NOT NULL,
            publication_scope TEXT NOT NULL DEFAULT 'local_mirror',
            published_at TEXT NOT NULL DEFAULT (datetime('now')),
            superseded_at TEXT,
            UNIQUE(archive_delivery_id, publication_generation),
            FOREIGN KEY(archive_delivery_id) REFERENCES archive_deliveries(id),
            FOREIGN KEY(transcript_row_id) REFERENCES transcripts(id)
        )
        """
    )
    for publication in legacy_publication_rows:
        delivery = conn.execute(
            "SELECT transcript_row_id, publication_generation, alias_set_sha256, "
            "source_aliases FROM archive_deliveries WHERE id = ?",
            (publication.get("archive_delivery_id"),),
        ).fetchone()
        if delivery is None:
            continue
        values = (
            publication.get("id"),
            publication.get("archive_delivery_id"),
            publication.get("transcript_row_id") or delivery["transcript_row_id"],
            publication.get("publication_generation")
            or delivery["publication_generation"],
            publication.get("alias_set_sha256") or delivery["alias_set_sha256"],
            publication.get("source_aliases") or delivery["source_aliases"],
            publication.get("destination_audio_path"),
            publication.get("destination_markdown_path"),
            publication.get("destination_manifest_path"),
            publication.get("receipt_sha256"),
            publication.get("publication_scope") or "local_mirror",
            publication.get("published_at"),
            publication.get("superseded_at"),
        )
        if any(value is None for value in values[3:10]):
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO archive_publications (
                id, archive_delivery_id, transcript_row_id, publication_generation,
                alias_set_sha256, source_aliases, destination_audio_path,
                destination_markdown_path, destination_manifest_path,
                receipt_sha256, publication_scope, published_at, superseded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')), ?)
            """,
            values,
        )
    conn.execute(
        """
        INSERT OR IGNORE INTO archive_publications (
            archive_delivery_id, transcript_row_id, publication_generation,
            alias_set_sha256, source_aliases, destination_audio_path,
            destination_markdown_path, destination_manifest_path,
            receipt_sha256, publication_scope, published_at
        )
        SELECT id, transcript_row_id, publication_generation,
               alias_set_sha256, source_aliases, destination_audio_path,
               destination_markdown_path, destination_manifest_path,
               receipt_sha256, 'local_mirror',
               COALESCE(local_mirror_published_at, published_at, datetime('now'))
        FROM archive_deliveries
        WHERE status = 'published'
          AND publication_scope = 'local_mirror'
          AND alias_set_sha256 IS NOT NULL
          AND destination_audio_path IS NOT NULL
          AND destination_markdown_path IS NOT NULL
          AND destination_manifest_path IS NOT NULL
          AND receipt_sha256 IS NOT NULL
        """
    )


def _create_apple_effects_table(
    conn: sqlite3.Connection, table: str = "apple_effects"
) -> None:
    conn.execute(
        f"""
        CREATE TABLE {table} (
            effect_key TEXT PRIMARY KEY,
            transcript_id INTEGER NOT NULL,
            effect_type TEXT NOT NULL CHECK (effect_type IN ('note', 'reminder')),
            requested_target TEXT NOT NULL,
            fallback_target TEXT NOT NULL DEFAULT '',
            payload_sha256 TEXT NOT NULL
                CHECK (length(payload_sha256) = 64),
            state TEXT NOT NULL DEFAULT 'reserved'
                CHECK (state IN ('reserved', 'in_flight', 'uncertain',
                                 'succeeded', 'failed', 'quarantined')),
            provider_id TEXT,
            actual_target TEXT,
            reconciled INTEGER NOT NULL DEFAULT 0
                CHECK (reconciled IN (0, 1)),
            attempt_count INTEGER NOT NULL DEFAULT 0
                CHECK (attempt_count >= 0),
            lease_owner TEXT,
            lease_expires_at TEXT,
            stale_attempt_at TEXT,
            last_error_code TEXT,
            created_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            ),
            updated_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            ),
            succeeded_at TEXT,
            FOREIGN KEY(transcript_id) REFERENCES transcripts(id),
            CHECK (state != 'succeeded' OR provider_id IS NOT NULL),
            CHECK (state != 'quarantined' OR last_error_code IS NOT NULL)
        )
        """
    )


def _ensure_apple_effects_schema(conn: sqlite3.Connection) -> None:
    """Create or additively migrate the receipt-backed Apple effect ledger.

    Older development builds may have created a reduced ``apple_effects``
    table.  SQLite cannot add CHECK/FK constraints with ``ALTER TABLE``; in
    that case rows are copied into the current shape inside the surrounding
    ``BEGIN IMMEDIATE`` migration transaction.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS apple_effect_quarantine (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            effect_key TEXT NOT NULL,
            transcript_id INTEGER,
            effect_type TEXT,
            requested_target TEXT,
            payload_sha256 TEXT,
            state TEXT,
            provider_id TEXT,
            actual_target TEXT,
            reason_code TEXT NOT NULL,
            quarantined_at TEXT NOT NULL,
            UNIQUE(effect_key, reason_code)
        )
        """
    )
    existing = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='apple_effects'"
    ).fetchone()
    expected = {
        "effect_key", "transcript_id", "effect_type", "requested_target",
        "fallback_target", "payload_sha256", "state", "provider_id",
        "actual_target", "reconciled", "attempt_count", "lease_owner",
        "lease_expires_at", "stale_attempt_at", "last_error_code", "created_at",
        "updated_at", "succeeded_at",
    }
    foreign_keys = (
        conn.execute("PRAGMA foreign_key_list(apple_effects)").fetchall()
        if existing is not None
        else []
    )
    has_transcript_fk = any(
        row[2] == "transcripts" and row[3] == "transcript_id" and row[4] == "id"
        for row in foreign_keys
    )
    current_columns = _table_columns(conn, "apple_effects") if existing is not None else set()
    column_defaults = {
        row[1]: str(row[4] or "")
        for row in (
            conn.execute("PRAGMA table_info(apple_effects)").fetchall()
            if existing is not None else []
        )
    }
    has_iso_defaults = all(
        "strftime" in column_defaults.get(column, "").lower()
        for column in ("created_at", "updated_at")
    )
    if existing is None:
        _create_apple_effects_table(conn)
    elif (
        not expected.issubset(current_columns)
        or not has_transcript_fk
        or not has_iso_defaults
    ):
        legacy_rows = [
            dict(row) for row in conn.execute("SELECT * FROM apple_effects").fetchall()
        ]
        legacy_name = "apple_effects_legacy_migration"
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (legacy_name,)
        ).fetchone():
            raise sqlite3.IntegrityError("stale Apple effect migration table")
        conn.execute("DROP INDEX IF EXISTS idx_apple_effects_transcript")
        conn.execute("DROP INDEX IF EXISTS idx_apple_effects_health")
        conn.execute("ALTER TABLE apple_effects RENAME TO " + legacy_name)
        _create_apple_effects_table(conn)
        for legacy in legacy_rows:
            effect_key = str(legacy.get("effect_key") or "")
            transcript_id = legacy.get("transcript_id")
            effect_type = str(legacy.get("effect_type") or "note")
            requested = str(legacy.get("requested_target") or "Penny")
            payload_hash = str(legacy.get("payload_sha256") or "")
            if not effect_key or not transcript_id or effect_type not in APPLE_EFFECT_TYPES:
                continue
            if conn.execute(
                "SELECT 1 FROM transcripts WHERE id = ?", (transcript_id,)
            ).fetchone() is None:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO apple_effect_quarantine (
                        effect_key, transcript_id, effect_type, requested_target,
                        payload_sha256, state, provider_id, actual_target,
                        reason_code, quarantined_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'orphan_transcript', ?)
                    """,
                    (
                        effect_key[:128], transcript_id, effect_type[:24], requested[:255],
                        payload_hash if re.fullmatch(r"[0-9a-f]{64}", payload_hash) else None,
                        str(legacy.get("state") or "reserved")[:24],
                        str(legacy.get("provider_id") or "")[:255] or None,
                        str(legacy.get("actual_target") or "")[:255] or None,
                        _apple_effect_now(),
                    ),
                )
                continue
            if not re.fullmatch(r"[0-9a-f]{64}", payload_hash):
                payload_hash = hashlib.sha256(effect_key.encode("utf-8")).hexdigest()
            state = str(legacy.get("state") or "reserved")
            if state not in APPLE_EFFECT_STATES:
                state = "failed"
            provider_id = legacy.get("provider_id")
            if state == "succeeded" and not provider_id:
                state = "failed"
            error_code = legacy.get("last_error_code")
            if state == "quarantined" and not error_code:
                error_code = "migration_invalid_state"
            if error_code:
                error_code = _apple_effect_safe_code(str(error_code))
            try:
                created_at = _apple_effect_now(legacy.get("created_at"))
            except (TypeError, ValueError):
                created_at = _apple_effect_now()
            try:
                updated_at = _apple_effect_now(legacy.get("updated_at"))
            except (TypeError, ValueError):
                updated_at = created_at
            try:
                succeeded_at = (
                    _apple_effect_now(legacy.get("succeeded_at"))
                    if legacy.get("succeeded_at") else None
                )
            except (TypeError, ValueError):
                succeeded_at = None
            if state == "succeeded" and succeeded_at is None:
                succeeded_at = updated_at
            try:
                lease_expires_at = (
                    _apple_effect_now(legacy.get("lease_expires_at"))
                    if legacy.get("lease_expires_at") else None
                )
            except (TypeError, ValueError):
                lease_expires_at = None
            try:
                stale_attempt_at = (
                    _apple_effect_now(legacy.get("stale_attempt_at"))
                    if legacy.get("stale_attempt_at") else None
                )
            except (TypeError, ValueError):
                stale_attempt_at = None
            conn.execute(
                """INSERT OR IGNORE INTO apple_effects (
                    effect_key, transcript_id, effect_type, requested_target,
                    fallback_target, payload_sha256, state, provider_id,
                    actual_target, reconciled, attempt_count, lease_owner,
                    lease_expires_at, stale_attempt_at, last_error_code,
                    created_at, updated_at, succeeded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    effect_key, int(transcript_id), effect_type, requested,
                    str(legacy.get("fallback_target") or ""), payload_hash, state,
                    provider_id, legacy.get("actual_target"),
                    int(bool(legacy.get("reconciled", 0))),
                    max(0, int(legacy.get("attempt_count") or 0)),
                    legacy.get("lease_owner"), lease_expires_at,
                    stale_attempt_at, error_code,
                    created_at, updated_at, succeeded_at,
                ),
            )
        conn.execute("DROP TABLE " + legacy_name)
    orphan_rows = conn.execute(
        """
        SELECT effects.* FROM apple_effects AS effects
        LEFT JOIN transcripts ON transcripts.id = effects.transcript_id
        WHERE transcripts.id IS NULL
        """
    ).fetchall()
    for orphan in orphan_rows:
        data = dict(orphan)
        conn.execute(
            """
            INSERT OR IGNORE INTO apple_effect_quarantine (
                effect_key, transcript_id, effect_type, requested_target,
                payload_sha256, state, provider_id, actual_target,
                reason_code, quarantined_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'orphan_transcript', ?)
            """,
            (
                data["effect_key"], data["transcript_id"], data["effect_type"],
                data["requested_target"], data["payload_sha256"], data["state"],
                data["provider_id"], data["actual_target"], _apple_effect_now(),
            ),
        )
        conn.execute(
            "DELETE FROM apple_effects WHERE effect_key = ?", (data["effect_key"],)
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_apple_effects_transcript "
        "ON apple_effects(transcript_id, effect_type)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_apple_effects_health "
        "ON apple_effects(state, updated_at)"
    )


def _ensure_transcript_columns(conn: sqlite3.Connection) -> None:
    required_columns = {
        "duration_seconds": "ALTER TABLE transcripts ADD COLUMN duration_seconds REAL",
        "ingest_state": "ALTER TABLE transcripts ADD COLUMN ingest_state TEXT",
        "routing_progress": "ALTER TABLE transcripts ADD COLUMN routing_progress TEXT",
        "recorded_at": "ALTER TABLE transcripts ADD COLUMN recorded_at TEXT",
        "discovered_at": "ALTER TABLE transcripts ADD COLUMN discovered_at TEXT",
        "file_seen_at": "ALTER TABLE transcripts ADD COLUMN file_seen_at TEXT",
        "transcription_started_at": "ALTER TABLE transcripts ADD COLUMN transcription_started_at TEXT",
        "transcription_completed_at": "ALTER TABLE transcripts ADD COLUMN transcription_completed_at TEXT",
        "routing_started_at": "ALTER TABLE transcripts ADD COLUMN routing_started_at TEXT",
        "updated_at": "ALTER TABLE transcripts ADD COLUMN updated_at TEXT",
        "last_error_at": "ALTER TABLE transcripts ADD COLUMN last_error_at TEXT",
        "quality_status": (
            "ALTER TABLE transcripts "
            "ADD COLUMN quality_status TEXT NOT NULL DEFAULT 'pending'"
        ),
        "quality_detail": "ALTER TABLE transcripts ADD COLUMN quality_detail TEXT",
        "transcript_sha256": "ALTER TABLE transcripts ADD COLUMN transcript_sha256 TEXT",
        "audio_sha256": "ALTER TABLE transcripts ADD COLUMN audio_sha256 TEXT",
        "transcription_backend": (
            "ALTER TABLE transcripts ADD COLUMN transcription_backend TEXT"
        ),
        "transcription_model": (
            "ALTER TABLE transcripts ADD COLUMN transcription_model TEXT"
        ),
        "maya_delivery_status": (
            "ALTER TABLE transcripts "
            "ADD COLUMN maya_delivery_status TEXT NOT NULL DEFAULT 'ineligible'"
        ),
        "maya_delivery_eligible": (
            "ALTER TABLE transcripts "
            "ADD COLUMN maya_delivery_eligible INTEGER NOT NULL DEFAULT 0"
        ),
        "maya_drop_id": "ALTER TABLE transcripts ADD COLUMN maya_drop_id TEXT",
        "maya_delivery_error": (
            "ALTER TABLE transcripts ADD COLUMN maya_delivery_error TEXT"
        ),
        "maya_delivery_attempt_count": (
            "ALTER TABLE transcripts "
            "ADD COLUMN maya_delivery_attempt_count INTEGER NOT NULL DEFAULT 0"
        ),
        "maya_next_attempt_at": (
            "ALTER TABLE transcripts ADD COLUMN maya_next_attempt_at TEXT"
        ),
        "maya_first_attempt_at": (
            "ALTER TABLE transcripts ADD COLUMN maya_first_attempt_at TEXT"
        ),
        "maya_last_attempt_at": (
            "ALTER TABLE transcripts ADD COLUMN maya_last_attempt_at TEXT"
        ),
        "maya_dead_letter_at": (
            "ALTER TABLE transcripts ADD COLUMN maya_dead_letter_at TEXT"
        ),
        "maya_dead_letter_reason": (
            "ALTER TABLE transcripts ADD COLUMN maya_dead_letter_reason TEXT"
        ),
        "maya_claim_token": (
            "ALTER TABLE transcripts ADD COLUMN maya_claim_token TEXT"
        ),
        "maya_claim_owner": (
            "ALTER TABLE transcripts ADD COLUMN maya_claim_owner TEXT"
        ),
        "maya_claimed_at": (
            "ALTER TABLE transcripts ADD COLUMN maya_claimed_at TEXT"
        ),
        "maya_claim_expires_at": (
            "ALTER TABLE transcripts ADD COLUMN maya_claim_expires_at TEXT"
        ),
        "superseded_by_transcript_row_id": (
            "ALTER TABLE transcripts "
            "ADD COLUMN superseded_by_transcript_row_id INTEGER"
        ),
    }
    added_columns: set[str] = set()
    for column, sql in required_columns.items():
        if _add_column_if_missing(
            conn,
            table="transcripts",
            column=column,
            sql=sql,
        ):
            added_columns.add(column)

    if "maya_delivery_eligible" in added_columns:
        conn.execute(
            """
            UPDATE transcripts
            SET maya_delivery_status = 'ineligible',
                maya_delivery_eligible = 0
            WHERE maya_delivery_status != 'sent'
              AND maya_drop_id IS NULL
            """
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


def _ensure_voice_memo_columns(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(
        conn,
        table="voice_memo_ingest",
        column="recorded_at",
        sql="ALTER TABLE voice_memo_ingest ADD COLUMN recorded_at TEXT",
    )
    _add_column_if_missing(
        conn,
        table="voice_memo_ingest",
        column="attempt_count",
        sql=(
            "ALTER TABLE voice_memo_ingest "
            "ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
        ),
    )
    _add_column_if_missing(
        conn,
        table="voice_memo_ingest",
        column="last_attempt_at",
        sql="ALTER TABLE voice_memo_ingest ADD COLUMN last_attempt_at TEXT",
    )
    _add_column_if_missing(
        conn,
        table="voice_memo_ingest",
        column="next_attempt_at",
        sql="ALTER TABLE voice_memo_ingest ADD COLUMN next_attempt_at TEXT",
    )
    _add_column_if_missing(
        conn,
        table="voice_memo_ingest",
        column="retryable",
        sql=(
            "ALTER TABLE voice_memo_ingest "
            "ADD COLUMN retryable INTEGER NOT NULL DEFAULT 1"
        ),
    )
    _add_column_if_missing(
        conn,
        table="voice_memo_ingest",
        column="terminal_at",
        sql="ALTER TABLE voice_memo_ingest ADD COLUMN terminal_at TEXT",
    )


def _read_legacy_voice_memo_cursor() -> int:
    try:
        return max(0, int(LEGACY_VOICE_MEMO_CURSOR_PATH.read_text().strip()))
    except (OSError, ValueError):
        return 0


def _migrate_legacy_voice_memo_cursor(conn: sqlite3.Connection) -> None:
    """Seed SQLite once from the old compatibility mirror, never the reverse."""
    existing = conn.execute(
        "SELECT 1 FROM source_watermarks WHERE source = 'voice_memos'"
    ).fetchone()
    if existing is None:
        conn.execute(
            """INSERT INTO source_watermarks(source, last_discovered_id, updated_at)
               VALUES ('voice_memos', ?, datetime('now'))""",
            (_read_legacy_voice_memo_cursor(),),
        )


def _migrate_legacy_voice_memo_retry_state(conn: sqlite3.Connection) -> None:
    """Make old unlinked failures retryable without retranscribing linked rows."""
    conn.execute(
        """UPDATE voice_memo_ingest
           SET retryable = 0,
               next_attempt_at = NULL,
               terminal_at = COALESCE(terminal_at, datetime('now'))
           WHERE transcript_row_id IS NOT NULL OR status = 'routed'"""
    )
    conn.execute(
        """UPDATE voice_memo_ingest
           SET retryable = 1,
               next_attempt_at = COALESCE(next_attempt_at, datetime('now'))
           WHERE transcript_row_id IS NULL
             AND status = 'failed'
             AND attempt_count < ?""",
        (VOICE_MEMO_MAX_ATTEMPTS,),
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


def _maya_now(value: datetime | str | None = None) -> str:
    """Normalize Maya delivery timestamps to an unambiguous UTC ISO value."""
    if value is None:
        parsed = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Maya delivery timestamp is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _maya_age_seconds(first_attempt_at: str | None, now: str) -> float | None:
    if not first_attempt_at:
        return 0.0
    try:
        first = datetime.fromisoformat(
            str(first_attempt_at).replace("Z", "+00:00")
        )
        current = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
    except ValueError:
        return None
    if first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max(
        0.0,
        (
            current.astimezone(timezone.utc)
            - first.astimezone(timezone.utc)
        ).total_seconds(),
    )


def _maya_limits(max_attempts: int | None, max_age_days: int | None) -> tuple[int, int]:
    try:
        attempts = int(max_attempts if max_attempts is not None else MAYA_MAX_ATTEMPTS)
    except (TypeError, ValueError):
        attempts = MAYA_MAX_ATTEMPTS
    try:
        age_days = int(max_age_days if max_age_days is not None else MAYA_MAX_AGE_DAYS)
    except (TypeError, ValueError):
        age_days = MAYA_MAX_AGE_DAYS
    return (
        max(1, min(attempts, MAYA_MAX_ATTEMPTS)),
        max(1, min(age_days, MAYA_MAX_AGE_DAYS)),
    )


def _safe_maya_dead_letter_reason(reason: str) -> str:
    normalized = str(reason or "").strip().casefold()
    aliases = {
        "max_attempts": "attempt_cap",
        "attempts": "attempt_cap",
        "max_age": "age_cap",
        "age": "age_cap",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in MAYA_DEAD_LETTER_REASONS else "delivery_error"


def _validate_maya_claim_arguments(
    claim_token: str | None,
    claim_owner: str | None,
) -> None:
    if (claim_token is None) != (claim_owner is None):
        raise ValueError("Maya claim token and owner are both required")


def _require_maya_claim_arguments(
    claim_token: str | None,
    claim_owner: str | None,
) -> None:
    """Require a non-empty claim pair for every pending worker transition."""
    _validate_maya_claim_arguments(claim_token, claim_owner)
    if (
        not isinstance(claim_token, str)
        or not claim_token.strip()
        or not isinstance(claim_owner, str)
        or not claim_owner.strip()
    ):
        raise ValueError("Maya claim token and owner are required")


def _maya_claim_matches(
    row: sqlite3.Row,
    claim_token: str | None,
    claim_owner: str | None,
) -> bool:
    _require_maya_claim_arguments(claim_token, claim_owner)
    return (
        row["maya_claim_token"] == claim_token
        and row["maya_claim_owner"] == claim_owner
    )


def _maya_claim_is_active(row: sqlite3.Row, now: str) -> bool:
    """Return whether a complete claim lease is valid at the supplied UTC time."""
    token = row["maya_claim_token"]
    owner = row["maya_claim_owner"]
    expires_at = row["maya_claim_expires_at"]
    if not token or not owner or not expires_at:
        return False
    try:
        expires = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        current = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
    except ValueError:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return expires.astimezone(timezone.utc) > current.astimezone(timezone.utc)


def _maya_schedule_is_due(value: object, now: str) -> bool:
    """Return whether a nullable next-attempt value permits dispatch."""
    if value is None:
        return True
    try:
        scheduled = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        current = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
    except ValueError:
        return False
    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return scheduled.astimezone(timezone.utc) <= current.astimezone(timezone.utc)


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


def _is_maya_delivery_eligible(
    *,
    requested: bool,
    source: str,
    transcript: str,
    ingest_state: str | None,
    quality_status: str,
    recorded_at: str | None,
) -> bool:
    """Require an explicit, complete post-cutover capture before Maya dequeue."""
    body = transcript.strip()
    lowered_body = body.casefold()
    return (
        requested
        and quality_status == "passed"
        and ingest_state in {"transcribed", "routed"}
        and not source.casefold().startswith("maya:")
        and bool(recorded_at)
        and bool(body)
        and not lowered_body.startswith("(migrated ")
        and not lowered_body.startswith("(skipped:")
    )


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
        "last_error": "ALTER TABLE slack_deliveries ADD COLUMN last_error TEXT",
        "provider_ts": "ALTER TABLE slack_deliveries ADD COLUMN provider_ts TEXT",
        "sent_at": "ALTER TABLE slack_deliveries ADD COLUMN sent_at TEXT",
        "channel_id": (
            "ALTER TABLE slack_deliveries ADD COLUMN channel_id TEXT "
            f"NOT NULL DEFAULT '{DEFAULT_SLACK_CHANNEL_ID}'"
        ),
        "message_text": (
            "ALTER TABLE slack_deliveries ADD COLUMN message_text TEXT NOT NULL DEFAULT ''"
        ),
        "delivery_plan_version": (
            "ALTER TABLE slack_deliveries ADD COLUMN delivery_plan_version TEXT"
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
        "slack_claim_token": (
            "ALTER TABLE slack_deliveries ADD COLUMN slack_claim_token TEXT"
        ),
        "slack_claim_owner": (
            "ALTER TABLE slack_deliveries ADD COLUMN slack_claim_owner TEXT"
        ),
        "slack_claimed_at": (
            "ALTER TABLE slack_deliveries ADD COLUMN slack_claimed_at TEXT"
        ),
        "slack_claim_expires_at": (
            "ALTER TABLE slack_deliveries ADD COLUMN slack_claim_expires_at TEXT"
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
        SET delivery_plan_version = ?,
            updated_at = datetime('now')
        WHERE delivery_plan_version IS NULL
          AND status = 'sent'
        """,
        (SLACK_DELIVERY_PLAN_LEGACY_TOP_LEVEL_V1,),
    )
    conn.execute(
        """
        UPDATE slack_deliveries
        SET delivery_plan_version = ?,
            updated_at = datetime('now')
        WHERE delivery_plan_version IS NULL
          AND status IN ('pending', 'failed')
          AND COALESCE(next_chunk_index, 0) = 0
          AND provider_ts IS NULL
          AND COALESCE(chunk_provider_ts, '[]') = '[]'
        """,
        (SLACK_DELIVERY_PLAN_BLOCK_KIT_V2,),
    )
    conn.execute(
        """
        UPDATE slack_deliveries
        SET delivery_plan_version = ?,
            status = 'failed',
            last_error = ?,
            next_attempt_at = NULL,
            updated_at = datetime('now')
        WHERE delivery_plan_version IS NULL
        """,
        (
            SLACK_DELIVERY_PLAN_LEGACY_TOP_LEVEL_V1,
            SLACK_LEGACY_PARTIAL_RECONCILIATION_ERROR,
        ),
    )
    conn.execute(
        """
        UPDATE slack_deliveries
        SET status = 'failed',
            last_error = ?,
            next_attempt_at = NULL,
            updated_at = datetime('now')
        WHERE status = 'pending'
          AND delivery_plan_version != ?
        """,
        (
            SLACK_LEGACY_PARTIAL_RECONCILIATION_ERROR,
            SLACK_DELIVERY_PLAN_BLOCK_KIT_V2,
        ),
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


def _ensure_quality_failure_slack_delivery_columns(
    conn: sqlite3.Connection,
) -> None:
    required_columns = {
        "slack_claim_token": (
            "ALTER TABLE quality_failure_slack_deliveries "
            "ADD COLUMN slack_claim_token TEXT"
        ),
        "slack_claim_owner": (
            "ALTER TABLE quality_failure_slack_deliveries "
            "ADD COLUMN slack_claim_owner TEXT"
        ),
        "slack_claimed_at": (
            "ALTER TABLE quality_failure_slack_deliveries "
            "ADD COLUMN slack_claimed_at TEXT"
        ),
        "slack_claim_expires_at": (
            "ALTER TABLE quality_failure_slack_deliveries "
            "ADD COLUMN slack_claim_expires_at TEXT"
        ),
    }
    for column, sql in required_columns.items():
        _add_column_if_missing(
            conn,
            table="quality_failure_slack_deliveries",
            column=column,
            sql=sql,
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


def _bounded_quality_detail(quality_detail: str | None) -> str | None:
    if quality_detail is None:
        return None
    bounded = str(quality_detail).strip()[:MAX_QUALITY_DETAIL_CHARACTERS]
    return bounded or None


def _safe_quality_receipt_detail(quality_detail: str | None) -> str:
    """Allow only bounded machine reason tuples into the operational receipt."""
    bounded = _bounded_quality_detail(quality_detail)
    if bounded and re.fullmatch(
        r"attempt_[12]=[a-z0-9_]{1,48}"
        r"(?:;attempt_2=[a-z0-9_]{1,48})?",
        bounded,
    ):
        return bounded
    return "needs_review"


def _queue_quality_failure_delivery(
    conn: sqlite3.Connection,
    *,
    transcript_row_id: int,
    content_hash: str,
    quality_status: str,
    quality_detail: str | None,
) -> None:
    if quality_status != "needs_review" or not quality_detail:
        return
    safe_detail = _safe_quality_receipt_detail(quality_detail)
    message_text = (
        "Penny quality review required\n"
        f"transcript_id: {transcript_row_id}\n"
        f"content_hash_prefix: {content_hash[:12]}\n"
        f"quality_detail: {safe_detail}"
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO quality_failure_slack_deliveries (
            transcript_row_id, idempotency_key, content_kind,
            destination, message_text
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            transcript_row_id,
            f"penny:quality-failure:{content_hash}",
            QUALITY_FAILURE_CONTENT_KIND,
            QUALITY_FAILURE_DESTINATION,
            message_text,
        ),
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
               transcript_row_id, channel_id, message_text,
               delivery_plan_version
           )
           VALUES (?, ?, ?, ?)""",
        (
            transcript_row_id,
            _slack_channel_id(),
            transcript,
            SLACK_DELIVERY_PLAN_BLOCK_KIT_V2,
        ),
    )


class InsertOutcome(str, Enum):
    INSERTED = "inserted"
    DUPLICATE = "duplicate"
    FAILED = "failed"


@dataclass(frozen=True)
class TranscriptInsertResult:
    outcome: InsertOutcome
    row_id: int | None = None
    existing_status: str | None = None
    error_code: str | None = None


def _insert_transcript_transaction(
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
    recorded_at: str | None = None,
    quality_status: str | None = None,
    quality_detail: str | None = None,
    maya_delivery_eligible: bool = False,
    enqueue_slack: bool = True,
    archive_staged: Any | None = None,
    archive_metadata: dict[str, Any] | None = None,
    archive_unavailable_reason: str | None = None,
) -> int | None:
    """Insert a transcript and related outbox rows in one transaction."""
    if quality_status is None:
        quality_status = "needs_review" if ingest_state == "needs_review" else "passed"
    quality_detail = _bounded_quality_detail(quality_detail)
    normalized_recorded_at = (
        _as_iso8601_utc(recorded_at) if recorded_at is not None else None
    )
    maya_eligible = _is_maya_delivery_eligible(
        requested=maya_delivery_eligible,
        source=source,
        transcript=transcript,
        ingest_state=ingest_state,
        quality_status=quality_status,
        recorded_at=normalized_recorded_at,
    )
    maya_delivery_status = "pending" if maya_eligible else "ineligible"
    transcript_sha256 = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    conn = None
    try:
        conn = _get_conn()
        cursor = conn.execute(
            """INSERT OR IGNORE INTO transcripts (
                   content_hash, source, transcript, audio_path,
                   duration_seconds, ingest_state, discovered_at, file_seen_at,
                   transcription_started_at, transcription_completed_at, error_message,
                   recorded_at, quality_status, quality_detail, transcript_sha256,
                   maya_delivery_status, maya_delivery_eligible
               )
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                normalized_recorded_at,
                quality_status,
                quality_detail,
                transcript_sha256,
                maya_delivery_status,
                1 if maya_eligible else 0,
            ),
        )
        if cursor.lastrowid and cursor.rowcount > 0:
            if archive_staged is not None:
                _queue_archive_delivery_conn(
                    conn,
                    int(cursor.lastrowid),
                    archive_staged,
                    archive_metadata,
                )
            elif archive_unavailable_reason is not None:
                _record_archive_unavailable_conn(
                    conn,
                    int(cursor.lastrowid),
                    availability_status="not_applicable",
                    reason_code=archive_unavailable_reason,
                )
            _queue_slack_delivery(
                conn,
                transcript_row_id=int(cursor.lastrowid),
                source=source,
                transcript=transcript,
                ingest_state=ingest_state,
                quality_status=quality_status,
                enqueue_slack=enqueue_slack,
            )
            _queue_quality_failure_delivery(
                conn,
                transcript_row_id=int(cursor.lastrowid),
                content_hash=content_hash,
                quality_status=quality_status,
                quality_detail=quality_detail,
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
    finally:
        if conn:
            conn.close()


def insert_transcript_result(**kwargs: Any) -> TranscriptInsertResult:
    """Insert a transcript while distinguishing duplicate and database failure."""
    content_hash = str(kwargs["content_hash"])
    try:
        row_id = _insert_transcript_transaction(**kwargs)
        if row_id is not None:
            return TranscriptInsertResult(InsertOutcome.INSERTED, row_id=int(row_id))

        existing = _get_transcript_by_hash_strict(content_hash)
        if existing is None:
            return TranscriptInsertResult(
                InsertOutcome.FAILED,
                error_code="duplicate_without_canonical_row",
            )
        return TranscriptInsertResult(
            InsertOutcome.DUPLICATE,
            row_id=int(existing["id"]),
            existing_status=str(existing["status"]),
        )
    except sqlite3.Error:
        log.error("Failed to insert transcript due to a database error")
        return TranscriptInsertResult(
            InsertOutcome.FAILED,
            error_code="database_unavailable",
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
    recorded_at: str | None = None,
    quality_status: str | None = None,
    quality_detail: str | None = None,
    maya_delivery_eligible: bool = False,
    enqueue_slack: bool = True,
    archive_staged: Any | None = None,
    archive_metadata: dict[str, Any] | None = None,
    archive_unavailable_reason: str | None = None,
) -> int | None:
    """Compatibility wrapper returning an id only for a newly inserted row."""
    result = insert_transcript_result(
        content_hash=content_hash,
        source=source,
        transcript=transcript,
        audio_path=audio_path,
        duration_seconds=duration_seconds,
        ingest_state=ingest_state,
        discovered_at=discovered_at,
        file_seen_at=file_seen_at,
        transcription_started_at=transcription_started_at,
        transcription_completed_at=transcription_completed_at,
        error_message=error_message,
        recorded_at=recorded_at,
        quality_status=quality_status,
        quality_detail=quality_detail,
        maya_delivery_eligible=maya_delivery_eligible,
        enqueue_slack=enqueue_slack,
        archive_staged=archive_staged,
        archive_metadata=archive_metadata,
        archive_unavailable_reason=archive_unavailable_reason,
    )
    return result.row_id if result.outcome is InsertOutcome.INSERTED else None


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
        if transcript_id is not None:
            clauses.append("deliveries.transcript_row_id = ?")
            params.append(transcript_id)
        params.append(limit)
        rows = conn.execute(
            f"""SELECT deliveries.id, deliveries.transcript_row_id,
                       deliveries.channel_id, deliveries.message_text,
                       deliveries.delivery_plan_version,
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


def _validate_slack_claim_arguments(
    claim_token: str | None,
    claim_owner: str | None,
) -> None:
    if (claim_token is None) != (claim_owner is None):
        raise ValueError("Slack claim token and owner must be provided together")
    if claim_token is not None and (
        not str(claim_token).strip() or not str(claim_owner).strip()
    ):
        raise ValueError("Slack claim token and owner must be nonempty")


def _slack_claim_matches(
    row: sqlite3.Row,
    claim_token: str | None,
    claim_owner: str | None,
) -> bool:
    return (
        claim_token is not None
        and claim_owner is not None
        and row["slack_claim_token"] == claim_token
        and row["slack_claim_owner"] == claim_owner
    )


def claim_next_slack_delivery(
    claim_owner: str,
    *,
    lease_seconds: int = SLACK_CLAIM_LEASE_SECONDS,
) -> dict[str, Any] | None:
    """Atomically lease one due Slack row, including an expired prior lease."""
    owner = str(claim_owner).strip()
    if not owner:
        raise ValueError("Slack claim owner is required")
    lease = max(SLACK_CLAIM_LEASE_SECONDS, min(int(lease_seconds), 3600))
    claim_token = secrets.token_hex(16)
    conn = None
    try:
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT deliveries.id
            FROM slack_deliveries AS deliveries
            LEFT JOIN transcripts
              ON transcripts.id = deliveries.transcript_row_id
            WHERE transcripts.quality_status = 'passed'
              AND (
                    (
                        deliveries.status = 'pending'
                        AND (
                            deliveries.next_attempt_at IS NULL
                            OR deliveries.next_attempt_at <= datetime('now')
                        )
                    )
                    OR (
                        deliveries.status = 'delivering'
                        AND deliveries.slack_claim_expires_at <= datetime('now')
                    )
                  )
            ORDER BY deliveries.created_at ASC, deliveries.id ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            conn.rollback()
            return None
        delivery_id = int(row["id"])
        cursor = conn.execute(
            """
            UPDATE slack_deliveries
            SET status = 'delivering',
                slack_claim_token = ?,
                slack_claim_owner = ?,
                slack_claimed_at = datetime('now'),
                slack_claim_expires_at = datetime('now', '+' || ? || ' seconds'),
                updated_at = datetime('now')
            WHERE id = ?
              AND (
                    (
                        status = 'pending'
                        AND (next_attempt_at IS NULL OR next_attempt_at <= datetime('now'))
                    )
                    OR (
                        status = 'delivering'
                        AND slack_claim_expires_at <= datetime('now')
                    )
                  )
            """,
            (claim_token, owner, lease, delivery_id),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return None
        claimed = conn.execute(
            """
            SELECT id, transcript_row_id, channel_id, message_text,
                   delivery_plan_version, status, attempt_count,
                   next_attempt_at, last_error, provider_ts, next_chunk_index,
                   chunk_attempt_count, chunk_provider_ts,
                   slack_claim_token, slack_claim_owner, slack_claimed_at,
                   slack_claim_expires_at, created_at, updated_at, sent_at
            FROM slack_deliveries
            WHERE id = ?
            """,
            (delivery_id,),
        ).fetchone()
        conn.commit()
        return dict(claimed) if claimed is not None else None
    except Exception as e:
        if conn:
            conn.rollback()
        log.error(
            "Failed to claim Slack delivery: %s",
            _safe_exception_class(e),
        )
        raise
    finally:
        if conn:
            conn.close()


def get_pending_quality_failure_deliveries(
    limit: int = 20,
) -> list[dict[str, Any]]:
    conn = None
    try:
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT id, transcript_row_id, idempotency_key, content_kind,
                   destination, message_text, status, attempt_count,
                   next_attempt_at, last_error, provider_ts,
                   created_at, updated_at, sent_at
            FROM quality_failure_slack_deliveries
            WHERE status = 'pending'
              AND (
                    next_attempt_at IS NULL
                    OR next_attempt_at <= datetime('now')
                  )
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        log.error(
            "Failed to fetch quality-failure deliveries: %s",
            _safe_exception_class(e),
        )
        return []
    finally:
        if conn:
            conn.close()


def claim_next_quality_failure_delivery(
    claim_owner: str,
    *,
    lease_seconds: int = SLACK_CLAIM_LEASE_SECONDS,
) -> dict[str, Any] | None:
    """Atomically lease one due body-free quality-failure projection."""
    owner = str(claim_owner).strip()
    if not owner:
        raise ValueError("Slack claim owner is required")
    lease = max(SLACK_CLAIM_LEASE_SECONDS, min(int(lease_seconds), 3600))
    claim_token = secrets.token_hex(16)
    conn = None
    try:
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT id
            FROM quality_failure_slack_deliveries
            WHERE (
                    status = 'pending'
                    AND (next_attempt_at IS NULL OR next_attempt_at <= datetime('now'))
                  )
               OR (
                    status = 'delivering'
                    AND slack_claim_expires_at <= datetime('now')
                  )
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            conn.rollback()
            return None
        delivery_id = int(row["id"])
        cursor = conn.execute(
            """
            UPDATE quality_failure_slack_deliveries
            SET status = 'delivering',
                slack_claim_token = ?,
                slack_claim_owner = ?,
                slack_claimed_at = datetime('now'),
                slack_claim_expires_at = datetime('now', '+' || ? || ' seconds'),
                updated_at = datetime('now')
            WHERE id = ?
              AND (
                    (
                        status = 'pending'
                        AND (next_attempt_at IS NULL OR next_attempt_at <= datetime('now'))
                    )
                    OR (
                        status = 'delivering'
                        AND slack_claim_expires_at <= datetime('now')
                    )
                  )
            """,
            (claim_token, owner, lease, delivery_id),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return None
        claimed = conn.execute(
            """
            SELECT id, transcript_row_id, idempotency_key, content_kind,
                   destination, message_text, status, attempt_count,
                   next_attempt_at, last_error, provider_ts,
                   slack_claim_token, slack_claim_owner, slack_claimed_at,
                   slack_claim_expires_at, created_at, updated_at, sent_at
            FROM quality_failure_slack_deliveries
            WHERE id = ?
            """,
            (delivery_id,),
        ).fetchone()
        conn.commit()
        return dict(claimed) if claimed is not None else None
    except Exception as e:
        if conn:
            conn.rollback()
        log.error(
            "Failed to claim quality-failure delivery: %s",
            _safe_exception_class(e),
        )
        raise
    finally:
        if conn:
            conn.close()


def _renew_slack_claim(
    table: str,
    delivery_id: int,
    *,
    claim_token: str,
    claim_owner: str,
    lease_seconds: int = SLACK_CLAIM_LEASE_SECONDS,
) -> None:
    _validate_slack_claim_arguments(claim_token, claim_owner)
    if table not in {"slack_deliveries", "quality_failure_slack_deliveries"}:
        raise ValueError("Unsupported Slack delivery table")
    lease = max(SLACK_CLAIM_LEASE_SECONDS, min(int(lease_seconds), 3600))
    conn = None
    try:
        conn = _get_conn()
        cursor = conn.execute(
            f"""
            UPDATE {table}
            SET slack_claim_expires_at = datetime('now', '+' || ? || ' seconds'),
                updated_at = datetime('now')
            WHERE id = ?
              AND status = 'delivering'
              AND sent_at IS NULL
              AND slack_claim_token = ?
              AND slack_claim_owner = ?
              AND slack_claim_expires_at > datetime('now')
            """,
            (lease, delivery_id, claim_token, claim_owner),
        )
        if cursor.rowcount != 1:
            raise ValueError("Slack claim owner mismatch or lease expired")
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        log.error(
            "Failed to renew Slack delivery claim id=%s: %s",
            delivery_id,
            _safe_exception_class(e),
        )
        raise
    finally:
        if conn:
            conn.close()


def renew_slack_delivery_claim(
    delivery_id: int,
    *,
    claim_token: str,
    claim_owner: str,
    lease_seconds: int = SLACK_CLAIM_LEASE_SECONDS,
) -> None:
    _renew_slack_claim(
        "slack_deliveries",
        delivery_id,
        claim_token=claim_token,
        claim_owner=claim_owner,
        lease_seconds=lease_seconds,
    )


def renew_quality_failure_delivery_claim(
    delivery_id: int,
    *,
    claim_token: str,
    claim_owner: str,
    lease_seconds: int = SLACK_CLAIM_LEASE_SECONDS,
) -> None:
    _renew_slack_claim(
        "quality_failure_slack_deliveries",
        delivery_id,
        claim_token=claim_token,
        claim_owner=claim_owner,
        lease_seconds=lease_seconds,
    )


def mark_quality_failure_delivery_sent(
    delivery_id: int,
    provider_ts: str,
    *,
    claim_token: str | None = None,
    claim_owner: str | None = None,
) -> None:
    _validate_slack_claim_arguments(claim_token, claim_owner)
    conn = None
    try:
        conn = _get_conn()
        current = conn.execute(
            "SELECT status, provider_ts, sent_at, "
            "slack_claim_token, slack_claim_owner "
            "FROM quality_failure_slack_deliveries WHERE id = ?",
            (delivery_id,),
        ).fetchone()
        if current is None:
            raise LookupError("Quality-failure Slack delivery row does not exist")
        if current["status"] == "sent" or current["sent_at"] is not None:
            if (
                current["status"] == "sent"
                and current["sent_at"] is not None
                and current["provider_ts"] == provider_ts
            ):
                return
            raise ValueError("Slack receipt conflicts with terminal state")
        if current["status"] not in {"pending", "delivering"}:
            raise ValueError("Slack receipt conflicts with terminal state")
        if current["status"] == "delivering" and not _slack_claim_matches(
            current, claim_token, claim_owner
        ):
            raise ValueError("Slack claim owner mismatch")
        cursor = conn.execute(
            """
            UPDATE quality_failure_slack_deliveries
            SET status = 'sent',
                last_error = NULL,
                provider_ts = ?,
                next_attempt_at = NULL,
                slack_claim_token = NULL,
                slack_claim_owner = NULL,
                slack_claimed_at = NULL,
                slack_claim_expires_at = NULL,
                sent_at = datetime('now'),
                updated_at = datetime('now')
            WHERE id = ?
              AND status IN ('pending', 'delivering')
              AND sent_at IS NULL
              AND (
                    status != 'delivering'
                    OR (slack_claim_token = ? AND slack_claim_owner = ?)
                  )
            """,
            (provider_ts, delivery_id, claim_token, claim_owner),
        )
        if cursor.rowcount != 1:
            terminal = conn.execute(
                "SELECT status, provider_ts, sent_at "
                "FROM quality_failure_slack_deliveries WHERE id = ?",
                (delivery_id,),
            ).fetchone()
            if (
                terminal is not None
                and terminal["status"] == "sent"
                and terminal["sent_at"] is not None
                and terminal["provider_ts"] == provider_ts
            ):
                conn.rollback()
                return
            raise ValueError("Slack receipt conflicts with terminal state")
        conn.commit()
    except Exception as e:
        log.error(
            "Failed to mark quality-failure delivery sent id=%s: %s",
            delivery_id,
            _safe_exception_class(e),
        )
        raise
    finally:
        if conn:
            conn.close()


def mark_quality_failure_delivery_failed(
    delivery_id: int,
    error_message: str,
    retry_after_seconds: int = 60,
    *,
    claim_token: str | None = None,
    claim_owner: str | None = None,
) -> None:
    _validate_slack_claim_arguments(claim_token, claim_owner)
    conn = None
    try:
        conn = _get_conn()
        safe_error = _safe_delivery_error(error_message)
        delay = max(1, min(int(retry_after_seconds), 3600))
        cursor = conn.execute(
            """
            UPDATE quality_failure_slack_deliveries
            SET status = CASE
                    WHEN attempt_count + 1 >= ? THEN 'failed'
                    ELSE 'pending'
                END,
                attempt_count = attempt_count + 1,
                last_error = ?,
                next_attempt_at = CASE
                    WHEN attempt_count + 1 >= ? THEN NULL
                    ELSE datetime('now', '+' || ? || ' seconds')
                END,
                slack_claim_token = NULL,
                slack_claim_owner = NULL,
                slack_claimed_at = NULL,
                slack_claim_expires_at = NULL,
                updated_at = datetime('now')
            WHERE id = ?
              AND status != 'sent'
              AND sent_at IS NULL
              AND (
                    status != 'delivering'
                    OR (slack_claim_token = ? AND slack_claim_owner = ?)
                  )
            """,
            (
                SLACK_MAX_ATTEMPTS,
                safe_error,
                SLACK_MAX_ATTEMPTS,
                delay,
                delivery_id,
                claim_token,
                claim_owner,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("Slack claim owner mismatch")
        conn.commit()
    except Exception as e:
        log.error(
            "Failed to mark quality-failure delivery failed id=%s: %s",
            delivery_id,
            _safe_exception_class(e),
        )
        raise
    finally:
        if conn:
            conn.close()


def mark_slack_delivery_sent(
    delivery_id: int,
    provider_ts: str | None = None,
    *,
    claim_token: str | None = None,
    claim_owner: str | None = None,
) -> None:
    _validate_slack_claim_arguments(claim_token, claim_owner)
    conn = None
    try:
        conn = _get_conn()
        current = conn.execute(
            "SELECT status, provider_ts, sent_at, "
            "slack_claim_token, slack_claim_owner "
            "FROM slack_deliveries WHERE id = ?",
            (delivery_id,),
        ).fetchone()
        if current is None:
            raise LookupError("Slack delivery row does not exist")
        if current["status"] == "sent" or current["sent_at"] is not None:
            if (
                current["status"] == "sent"
                and current["sent_at"] is not None
                and current["provider_ts"] == provider_ts
            ):
                return
            raise ValueError("Slack sent receipt conflicts with terminal state")
        if current["status"] not in {"pending", "delivering"}:
            raise ValueError("Slack receipt conflicts with terminal state")
        if current["status"] == "delivering" and not _slack_claim_matches(
            current, claim_token, claim_owner
        ):
            raise ValueError("Slack claim owner mismatch")
        cursor = conn.execute(
            """UPDATE slack_deliveries
               SET status = 'sent',
                   last_error = NULL,
                   provider_ts = ?,
                   next_attempt_at = NULL,
                   chunk_attempt_count = 0,
                   slack_claim_token = NULL,
                   slack_claim_owner = NULL,
                   slack_claimed_at = NULL,
                   slack_claim_expires_at = NULL,
                   sent_at = datetime('now'),
                   updated_at = datetime('now')
               WHERE id = ?
                 AND status IN ('pending', 'delivering')
                 AND sent_at IS NULL
                 AND (
                       status != 'delivering'
                       OR (slack_claim_token = ? AND slack_claim_owner = ?)
                     )""",
            (provider_ts, delivery_id, claim_token, claim_owner),
        )
        if cursor.rowcount != 1:
            terminal = conn.execute(
                "SELECT status, provider_ts, sent_at FROM slack_deliveries WHERE id = ?",
                (delivery_id,),
            ).fetchone()
            if (
                terminal is not None
                and terminal["status"] == "sent"
                and terminal["sent_at"] is not None
                and terminal["provider_ts"] == provider_ts
            ):
                conn.rollback()
                return
            raise ValueError("Slack receipt conflicts with terminal state")
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
    *,
    claim_token: str | None = None,
    claim_owner: str | None = None,
) -> None:
    _validate_slack_claim_arguments(claim_token, claim_owner)
    conn = None
    try:
        conn = _get_conn()
        safe_error = _safe_delivery_error(error_message)
        delay = max(1, min(int(retry_after_seconds), 3600))
        current = conn.execute(
            "SELECT status, sent_at, slack_claim_token, slack_claim_owner "
            "FROM slack_deliveries WHERE id = ?",
            (delivery_id,),
        ).fetchone()
        if current is None:
            raise LookupError("Slack delivery row does not exist")
        if current["status"] == "delivering" and not _slack_claim_matches(
            current, claim_token, claim_owner
        ):
            raise ValueError("Slack claim owner mismatch")
        cursor = conn.execute(
            """UPDATE slack_deliveries
               SET status = CASE
                       WHEN COALESCE(chunk_attempt_count, 0) + 1 >= ?
                           THEN 'failed'
                       ELSE 'pending'
                   END,
                   attempt_count = COALESCE(attempt_count, 0) + 1,
                   chunk_attempt_count = COALESCE(chunk_attempt_count, 0) + 1,
                   last_error = ?,
                   next_attempt_at = CASE
                       WHEN COALESCE(chunk_attempt_count, 0) + 1 >= ?
                           THEN NULL
                       ELSE datetime('now', '+' || ? || ' seconds')
                   END,
                   slack_claim_token = NULL,
                   slack_claim_owner = NULL,
                   slack_claimed_at = NULL,
                   slack_claim_expires_at = NULL,
                   updated_at = datetime('now')
               WHERE id = ?
                 AND status != 'sent'
                 AND sent_at IS NULL
                 AND (
                       status != 'delivering'
                       OR (slack_claim_token = ? AND slack_claim_owner = ?)
                     )""",
            (
                SLACK_MAX_ATTEMPTS,
                safe_error,
                SLACK_MAX_ATTEMPTS,
                delay,
                delivery_id,
                claim_token,
                claim_owner,
            ),
        )
        if cursor.rowcount == 0:
            current = conn.execute(
                """
                SELECT status, sent_at
                FROM slack_deliveries
                WHERE id = ?
                """,
                (delivery_id,),
            ).fetchone()
            if current is not None and (
                current["status"] == "sent" or current["sent_at"] is not None
            ):
                conn.rollback()
                return
            raise ValueError("Slack claim owner mismatch")
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


def mark_slack_delivery_reconciliation_required(
    delivery_id: int,
    *,
    claim_token: str | None = None,
    claim_owner: str | None = None,
) -> None:
    """Fail closed when persisted progress cannot use the current plan."""
    _validate_slack_claim_arguments(claim_token, claim_owner)
    conn = None
    try:
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT status, slack_claim_token, slack_claim_owner "
            "FROM slack_deliveries WHERE id = ?",
            (delivery_id,),
        ).fetchone()
        if current is None:
            raise LookupError("Slack delivery row does not exist")
        if current["status"] == "delivering" and not _slack_claim_matches(
            current, claim_token, claim_owner
        ):
            raise ValueError("Slack claim owner mismatch")
        cursor = conn.execute(
            """
            UPDATE slack_deliveries
            SET status = 'failed',
                last_error = ?,
                next_attempt_at = NULL,
                slack_claim_token = NULL,
                slack_claim_owner = NULL,
                slack_claimed_at = NULL,
                slack_claim_expires_at = NULL,
                updated_at = datetime('now')
            WHERE id = ?
              AND status != 'sent'
              AND (
                    status != 'delivering'
                    OR (slack_claim_token = ? AND slack_claim_owner = ?)
                  )
            """,
            (
                SLACK_LEGACY_PARTIAL_RECONCILIATION_ERROR,
                delivery_id,
                claim_token,
                claim_owner,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("Slack claim owner mismatch")
        conn.commit()
    except Exception as e:
        log.error(
            "Failed to mark Slack reconciliation required id=%s: %s",
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
    claim_token: str | None = None,
    claim_owner: str | None = None,
) -> None:
    """Persist one accepted chunk and mark the delivery sent only when complete."""
    _validate_slack_claim_arguments(claim_token, claim_owner)
    conn = None
    try:
        conn = _get_conn()
        current = conn.execute(
            """
            SELECT status, sent_at, next_chunk_index, chunk_provider_ts,
                   slack_claim_token, slack_claim_owner
            FROM slack_deliveries
            WHERE id = ?
            """,
            (delivery_id,),
        ).fetchone()
        if current is None:
            raise LookupError("Slack delivery row does not exist")
        if current["status"] == "delivering" and not _slack_claim_matches(
            current, claim_token, claim_owner
        ):
            raise ValueError("Slack claim owner mismatch")

        next_chunk_index = int(current["next_chunk_index"] or 0)
        existing_timestamps = _json_loads_or_default(current["chunk_provider_ts"], [])
        if not isinstance(existing_timestamps, list):
            existing_timestamps = []
        exact_existing_receipt = (
            next_chunk_index > chunk_index
            and chunk_index < len(existing_timestamps)
            and existing_timestamps[chunk_index] == provider_ts
        )
        if current["status"] == "sent" or current["sent_at"] is not None:
            if (
                current["status"] == "sent"
                and current["sent_at"] is not None
                and exact_existing_receipt
                and next_chunk_index == chunk_count
            ):
                return
            raise ValueError("Slack chunk receipt conflicts with terminal state")
        if current["status"] not in {"pending", "delivering"}:
            raise ValueError("Slack chunk receipt conflicts with terminal state")
        if next_chunk_index > chunk_index:
            if exact_existing_receipt:
                return
            raise ValueError("Slack chunk receipt conflicts with persisted progress")
        if next_chunk_index != chunk_index:
            raise ValueError("Slack chunk acknowledgement is out of order")

        timestamps = existing_timestamps
        timestamps.append(provider_ts)
        following_chunk = chunk_index + 1
        complete = following_chunk >= chunk_count
        cursor = conn.execute(
            """
            UPDATE slack_deliveries
            SET status = ?,
                next_chunk_index = ?,
                chunk_attempt_count = 0,
                chunk_provider_ts = ?,
                provider_ts = COALESCE(provider_ts, ?),
                last_error = NULL,
                next_attempt_at = NULL,
                slack_claim_token = NULL,
                slack_claim_owner = NULL,
                slack_claimed_at = NULL,
                slack_claim_expires_at = NULL,
                sent_at = CASE WHEN ? THEN datetime('now') ELSE sent_at END,
                updated_at = datetime('now')
            WHERE id = ?
              AND status IN ('pending', 'delivering')
              AND sent_at IS NULL
              AND (
                    status != 'delivering'
                    OR (slack_claim_token = ? AND slack_claim_owner = ?)
                  )
            """,
            (
                "sent" if complete else "pending",
                following_chunk,
                json.dumps(timestamps),
                provider_ts,
                1 if complete else 0,
                delivery_id,
                claim_token,
                claim_owner,
            ),
        )
        if cursor.rowcount != 1:
            terminal = conn.execute(
                "SELECT status, sent_at, next_chunk_index, chunk_provider_ts "
                "FROM slack_deliveries WHERE id = ?",
                (delivery_id,),
            ).fetchone()
            terminal_timestamps = (
                _json_loads_or_default(terminal["chunk_provider_ts"], [])
                if terminal is not None
                else []
            )
            if (
                terminal is not None
                and terminal["status"] == "sent"
                and terminal["sent_at"] is not None
                and int(terminal["next_chunk_index"] or 0) > chunk_index
                and int(terminal["next_chunk_index"] or 0) == chunk_count
                and isinstance(terminal_timestamps, list)
                and chunk_index < len(terminal_timestamps)
                and terminal_timestamps[chunk_index] == provider_ts
            ):
                conn.rollback()
                return
            raise ValueError("Slack chunk receipt conflicts with terminal state")
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
                   transcripts.ingest_state, transcripts.recorded_at,
                   transcripts.maya_delivery_eligible,
                   transcripts.superseded_by_transcript_row_id,
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
        if row["superseded_by_transcript_row_id"] is not None:
            raise ValueError("Superseded transcripts cannot be delivered to Maya")
        if str(row["source"]).casefold().startswith("maya:"):
            raise ValueError("Maya-originated transcripts cannot be delivered to Maya")
        if not _is_maya_delivery_eligible(
            requested=bool(row["maya_delivery_eligible"]),
            source=str(row["source"]),
            transcript=str(row["transcript"]),
            ingest_state=row["ingest_state"],
            quality_status=str(row["quality_status"]),
            recorded_at=row["recorded_at"],
        ):
            raise ValueError("Transcript is not explicitly eligible for Maya delivery")

        transcript = str(row["transcript"])
        transcript_sha256 = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
        persisted_sha256 = row["transcript_sha256"]
        if persisted_sha256 != transcript_sha256:
            raise ValueError("Persisted transcript SHA-256 does not match transcript bytes")
        captured_at = _as_iso8601_utc(row["recorded_at"])
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


def _maya_eligible_predicate() -> str:
    return """
        maya_delivery_eligible = 1
        AND quality_status = 'passed'
        AND source NOT LIKE 'maya:%'
        AND ingest_state IN ('transcribed', 'routed')
        AND recorded_at IS NOT NULL
        AND superseded_by_transcript_row_id IS NULL
        AND TRIM(transcript) != ''
        AND LOWER(TRIM(transcript)) NOT LIKE '(migrated %'
        AND LOWER(TRIM(transcript)) NOT LIKE '(skipped:%'
    """


def _maya_health_predicate() -> str:
    """Metadata-only Maya eligibility predicate for operator health probes."""
    return """
        maya_delivery_eligible = 1
        AND quality_status = 'passed'
        AND source NOT LIKE 'maya:%'
        AND ingest_state IN ('transcribed', 'routed')
        AND recorded_at IS NOT NULL
        AND superseded_by_transcript_row_id IS NULL
    """


def _terminalize_maya_delivery_limits(
    conn: sqlite3.Connection,
    *,
    now: str,
    max_attempts: int,
    max_age_days: int,
) -> int:
    """Move capped/stale pending rows to dead-letter in one transaction."""
    cursor = conn.execute(
        f"""
        UPDATE transcripts
        SET maya_delivery_status = 'dead_letter',
            maya_delivery_error = COALESCE(maya_delivery_error, 'delivery_error'),
            maya_next_attempt_at = NULL,
            maya_claim_token = NULL,
            maya_claim_owner = NULL,
            maya_claimed_at = NULL,
            maya_claim_expires_at = NULL,
            maya_dead_letter_at = ?,
            maya_dead_letter_reason = CASE
                WHEN COALESCE(maya_delivery_attempt_count, 0) >= ?
                    THEN 'attempt_cap'
                WHEN maya_first_attempt_at IS NOT NULL
                     AND julianday(maya_first_attempt_at) IS NULL
                    THEN 'age_cap'
                WHEN maya_next_attempt_at IS NOT NULL
                     AND julianday(maya_next_attempt_at) IS NULL
                    THEN 'invalid_schedule'
                ELSE 'age_cap'
            END,
            updated_at = ?
        WHERE maya_delivery_status = 'pending'
          AND maya_drop_id IS NULL
          AND ({_maya_eligible_predicate()})
          AND (
                maya_claim_token IS NULL
                OR maya_claim_owner IS NULL
                OR maya_claim_expires_at IS NULL
                OR julianday(maya_claim_expires_at) IS NULL
                OR julianday(maya_claim_expires_at) <= julianday(?)
              )
          AND (
                COALESCE(maya_delivery_attempt_count, 0) >= ?
                OR (
                    maya_first_attempt_at IS NOT NULL
                    AND (
                        julianday(maya_first_attempt_at) IS NULL
                        OR julianday(?) - julianday(maya_first_attempt_at) >= ?
                    )
                )
                OR (
                    maya_next_attempt_at IS NOT NULL
                    AND julianday(maya_next_attempt_at) IS NULL
                )
              )
        """,
        (
            now,
            max_attempts,
            now,
            now,
            max_attempts,
            now,
            max_age_days,
        ),
    )
    return int(cursor.rowcount)


def claim_maya_delivery(
    transcript_id: int,
    owner: str,
    *,
    now: datetime | str | None = None,
    lease_seconds: int = MAYA_CLAIM_LEASE_SECONDS,
) -> dict[str, str] | None:
    """Atomically claim one due pending row before any provider request.

    A claim is available only to one owner at a time. A valid, unexpired claim
    blocks other workers; an expired or malformed lease can be reclaimed. The
    returned token must accompany every worker-side state transition.
    """
    normalized_owner = str(owner or "").strip()
    if not normalized_owner:
        raise ValueError("Maya claim owner is required")
    normalized_now = _maya_now(now)
    try:
        lease = max(1, min(int(lease_seconds), 3600))
    except (TypeError, ValueError):
        lease = MAYA_CLAIM_LEASE_SECONDS
    expires_at = _maya_now(
        datetime.fromisoformat(normalized_now.replace("Z", "+00:00"))
        + timedelta(seconds=lease)
    )
    claim_token = secrets.token_hex(24)
    conn = None
    try:
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            f"""
            UPDATE transcripts
            SET maya_claim_token = ?,
                maya_claim_owner = ?,
                maya_claimed_at = ?,
                maya_claim_expires_at = ?,
                updated_at = ?
            WHERE id = ?
              AND maya_delivery_status = 'pending'
              AND maya_drop_id IS NULL
              AND ({_maya_eligible_predicate()})
              AND (
                    maya_next_attempt_at IS NULL
                    OR julianday(maya_next_attempt_at) <= julianday(?)
                  )
              AND (
                    maya_claim_token IS NULL
                    OR maya_claim_owner IS NULL
                    OR maya_claim_expires_at IS NULL
                    OR julianday(maya_claim_expires_at) IS NULL
                    OR julianday(maya_claim_expires_at) <= julianday(?)
                  )
            """,
            (
                claim_token,
                normalized_owner,
                normalized_now,
                expires_at,
                normalized_now,
                transcript_id,
                normalized_now,
                normalized_now,
            ),
        )
        if cursor.rowcount == 0:
            current = conn.execute(
                f"""
                SELECT id, maya_delivery_status, maya_drop_id,
                       maya_next_attempt_at, maya_claim_token, maya_claim_owner,
                       maya_claimed_at, maya_claim_expires_at
                FROM transcripts
                WHERE id = ?
                  AND ({_maya_eligible_predicate()})
                """,
                (transcript_id,),
            ).fetchone()
            if (
                current is not None
                and current["maya_delivery_status"] == "pending"
                and current["maya_drop_id"] is None
                and _maya_schedule_is_due(current["maya_next_attempt_at"], normalized_now)
                and current["maya_claim_owner"] == normalized_owner
                and _maya_claim_is_active(current, normalized_now)
            ):
                conn.commit()
                return {
                    "transcript_id": str(transcript_id),
                    "maya_claim_token": str(current["maya_claim_token"]),
                    "maya_claim_owner": str(current["maya_claim_owner"]),
                    "maya_claimed_at": str(current["maya_claimed_at"]),
                    "maya_claim_expires_at": str(current["maya_claim_expires_at"]),
                }
            conn.rollback()
            return None
        conn.commit()
        return {
            "transcript_id": str(transcript_id),
            "maya_claim_token": claim_token,
            "maya_claim_owner": normalized_owner,
            "maya_claimed_at": normalized_now,
            "maya_claim_expires_at": expires_at,
        }
    except Exception as exc:
        if conn:
            conn.rollback()
        log.error(
            "Failed to claim Maya delivery id=%s: %s",
            transcript_id,
            _safe_exception_class(exc),
        )
        return None
    finally:
        if conn:
            conn.close()


def release_maya_delivery_claim(
    transcript_id: int,
    claim_token: str | None,
    claim_owner: str | None,
) -> bool:
    """Release one matching pending claim after receipt persistence fails."""
    _validate_maya_claim_arguments(claim_token, claim_owner)
    if claim_token is None or claim_owner is None:
        return False
    conn = None
    try:
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            UPDATE transcripts
            SET maya_claim_token = NULL,
                maya_claim_owner = NULL,
                maya_claimed_at = NULL,
                maya_claim_expires_at = NULL,
                updated_at = ?
            WHERE id = ?
              AND maya_delivery_status = 'pending'
              AND maya_drop_id IS NULL
              AND maya_claim_token = ?
              AND maya_claim_owner = ?
            """,
            (_maya_now(), transcript_id, claim_token, claim_owner),
        )
        conn.commit()
        return bool(cursor.rowcount)
    except Exception as exc:
        if conn:
            conn.rollback()
        log.error(
            "Failed to release Maya claim id=%s: %s",
            transcript_id,
            _safe_exception_class(exc),
        )
        return False
    finally:
        if conn:
            conn.close()


def get_pending_maya_deliveries(
    limit: int = 20,
    *,
    now: datetime | str | None = None,
    max_attempts: int | None = None,
    max_age_days: int | None = None,
) -> list[dict[str, Any]]:
    """Return due eligible rows after terminalizing capped/stale pending work."""
    conn = None
    try:
        normalized_now = _maya_now(now)
        attempts, age_days = _maya_limits(max_attempts, max_age_days)
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        _terminalize_maya_delivery_limits(
            conn,
            now=normalized_now,
            max_attempts=attempts,
            max_age_days=age_days,
        )
        conn.commit()
        rows = conn.execute(
            f"""
            SELECT *
            FROM transcripts
            WHERE maya_delivery_status = 'pending'
              AND ({_maya_eligible_predicate()})
              AND (
                    maya_next_attempt_at IS NULL
                    OR julianday(maya_next_attempt_at) <= julianday(?)
                  )
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (normalized_now, max(0, int(limit))),
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        if conn:
            conn.rollback()
        log.error("Failed to fetch pending Maya deliveries: %s", _safe_exception_class(e))
        return []
    finally:
        if conn:
            conn.close()


def mark_maya_delivery_sent(
    transcript_row_id: int,
    drop_id: str,
    *,
    claim_token: str | None = None,
    claim_owner: str | None = None,
) -> None:
    """Persist Maya's durable receipt, accepting only exact Drop replays."""
    if not drop_id:
        raise ValueError("Maya Drop ID is required")
    _validate_maya_claim_arguments(claim_token, claim_owner)
    conn = None
    try:
        normalized_now = _maya_now()
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            """
            SELECT maya_delivery_status, maya_drop_id,
                   maya_claim_token, maya_claim_owner
            FROM transcripts WHERE id = ?
            """,
            (transcript_row_id,),
        ).fetchone()
        if current is None:
            raise LookupError("Transcript row does not exist")
        if current["maya_delivery_status"] == "sent":
            if current["maya_drop_id"] != drop_id:
                raise ValueError("Maya Drop ID conflicts with the durable receipt")
            conn.commit()
            return
        if (
            current["maya_delivery_status"] != "pending"
            or current["maya_drop_id"] is not None
        ):
            raise ValueError("Maya receipt cannot transition the current delivery state")
        if not _maya_claim_matches(current, claim_token, claim_owner):
            raise ValueError("Maya claim owner mismatch")
        cursor = conn.execute(
            """
            UPDATE transcripts
            SET maya_delivery_status = 'sent',
                maya_drop_id = ?,
                maya_delivery_error = NULL,
                maya_next_attempt_at = NULL,
                maya_claim_token = NULL,
                maya_claim_owner = NULL,
                maya_claimed_at = NULL,
                maya_claim_expires_at = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (drop_id, normalized_now, transcript_row_id),
        )
        if cursor.rowcount == 0:
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


def mark_maya_delivery_failed(
    transcript_row_id: int,
    error_message: str,
    *,
    claim_token: str | None = None,
    claim_owner: str | None = None,
) -> None:
    """Persist a bounded Maya delivery failure without changing Slack state."""
    _validate_maya_claim_arguments(claim_token, claim_owner)
    conn = None
    try:
        normalized_now = _maya_now()
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            """
            SELECT maya_delivery_status, maya_drop_id,
                   maya_claim_token, maya_claim_owner
            FROM transcripts WHERE id = ?
            """,
            (transcript_row_id,),
        ).fetchone()
        if current is None:
            raise LookupError("Transcript row does not exist")
        if current["maya_delivery_status"] == "sent" or current["maya_drop_id"]:
            conn.rollback()
            return
        if current["maya_delivery_status"] in {"failed", "dead_letter"}:
            conn.rollback()
            return
        if current["maya_delivery_status"] != "pending":
            raise ValueError("Maya failure cannot transition the current delivery state")
        if not _maya_claim_matches(current, claim_token, claim_owner):
            raise ValueError("Maya claim owner mismatch")
        cursor = conn.execute(
            """
            UPDATE transcripts
            SET maya_delivery_status = 'failed',
                maya_delivery_error = ?,
                maya_next_attempt_at = NULL,
                maya_claim_token = NULL,
                maya_claim_owner = NULL,
                maya_claimed_at = NULL,
                maya_claim_expires_at = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (_safe_delivery_error(error_message), normalized_now, transcript_row_id),
        )
        if cursor.rowcount == 0:
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


def mark_maya_delivery_retryable_at(
    transcript_row_id: int,
    error_message: str,
    retry_after_seconds: int = 60,
    *,
    now: datetime | str | None = None,
    max_attempts: int | None = None,
    max_age_days: int | None = None,
    claim_token: str | None = None,
    claim_owner: str | None = None,
) -> None:
    """Persist a transient Maya failure with an injectable UTC clock."""
    _validate_maya_claim_arguments(claim_token, claim_owner)
    conn = None
    try:
        normalized_now = _maya_now(now)
        attempts_limit, age_limit = _maya_limits(max_attempts, max_age_days)
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        delay = max(1, min(int(retry_after_seconds), 3600))
        current = conn.execute(
            """
            SELECT maya_delivery_status, maya_drop_id,
                   maya_delivery_attempt_count, maya_first_attempt_at,
                   maya_claim_token, maya_claim_owner
            FROM transcripts WHERE id = ?
            """,
            (transcript_row_id,),
        ).fetchone()
        if current is None:
            raise LookupError("Transcript row does not exist")
        if current["maya_delivery_status"] == "sent" or current["maya_drop_id"]:
            conn.rollback()
            return
        if current["maya_delivery_status"] != "pending":
            raise ValueError("Maya retry requires an explicitly replayed pending row")
        if not _maya_claim_matches(current, claim_token, claim_owner):
            raise ValueError("Maya claim owner mismatch")

        post_attempt_count = max(0, int(current["maya_delivery_attempt_count"] or 0)) + 1
        first_attempt_at = current["maya_first_attempt_at"] or normalized_now
        age_seconds = _maya_age_seconds(first_attempt_at, normalized_now)
        dead_letter_reason: str | None = None
        if post_attempt_count >= attempts_limit:
            dead_letter_reason = "attempt_cap"
        elif age_seconds is None or age_seconds >= age_limit * 86400:
            dead_letter_reason = "age_cap"

        if dead_letter_reason is not None:
            conn.execute(
                """
                UPDATE transcripts
                SET maya_delivery_status = 'dead_letter',
                    maya_delivery_attempt_count = ?,
                    maya_first_attempt_at = ?,
                    maya_last_attempt_at = ?,
                    maya_delivery_error = ?,
                    maya_next_attempt_at = NULL,
                    maya_claim_token = NULL,
                    maya_claim_owner = NULL,
                    maya_claimed_at = NULL,
                    maya_claim_expires_at = NULL,
                    maya_dead_letter_at = ?,
                    maya_dead_letter_reason = ?,
                    updated_at = ?
                WHERE id = ?
                  AND maya_delivery_status = 'pending'
                  AND maya_drop_id IS NULL
                """,
                (
                    post_attempt_count,
                    first_attempt_at,
                    normalized_now,
                    _safe_delivery_error(error_message),
                    normalized_now,
                    dead_letter_reason,
                    normalized_now,
                    transcript_row_id,
                ),
            )
        else:
            next_attempt_at = _maya_now(
                datetime.fromisoformat(normalized_now.replace("Z", "+00:00"))
                + timedelta(seconds=delay)
            )
            conn.execute(
                """
                UPDATE transcripts
                SET maya_delivery_status = 'pending',
                    maya_delivery_attempt_count = ?,
                    maya_first_attempt_at = ?,
                    maya_last_attempt_at = ?,
                    maya_delivery_error = ?,
                    maya_next_attempt_at = ?,
                    maya_claim_token = NULL,
                    maya_claim_owner = NULL,
                    maya_claimed_at = NULL,
                    maya_claim_expires_at = NULL,
                    maya_dead_letter_at = NULL,
                    maya_dead_letter_reason = NULL,
                    updated_at = ?
                WHERE id = ?
                  AND maya_delivery_status = 'pending'
                  AND maya_drop_id IS NULL
                """,
                (
                    post_attempt_count,
                    first_attempt_at,
                    normalized_now,
                    _safe_delivery_error(error_message),
                    next_attempt_at,
                    normalized_now,
                    transcript_row_id,
                ),
            )
        conn.commit()
    except Exception as e:
        log.error(
            "Failed to schedule Maya delivery retry id=%s: %s",
            transcript_row_id,
            _safe_exception_class(e),
        )
        raise
    finally:
        if conn:
            conn.close()


def mark_maya_delivery_retryable(
    transcript_row_id: int,
    error_message: str,
    retry_after_seconds: int = 60,
    *,
    now: datetime | str | None = None,
    max_attempts: int | None = None,
    max_age_days: int | None = None,
    claim_token: str | None = None,
    claim_owner: str | None = None,
) -> None:
    """Compatibility entry point for bounded Maya retry state."""
    mark_maya_delivery_retryable_at(
        transcript_row_id,
        error_message,
        retry_after_seconds=retry_after_seconds,
        now=now,
        max_attempts=max_attempts,
        max_age_days=max_age_days,
        claim_token=claim_token,
        claim_owner=claim_owner,
    )


def mark_maya_delivery_dead_letter(
    transcript_id: int,
    error_code: str,
    now: datetime | str | None = None,
) -> bool:
    """Explicitly terminalize one pending Maya row without replaying it."""
    conn = None
    try:
        normalized_now = _maya_now(now)
        conn = _get_conn()
        cursor = conn.execute(
            """
            UPDATE transcripts
            SET maya_delivery_status = 'dead_letter',
                maya_delivery_error = COALESCE(maya_delivery_error, 'delivery_error'),
                maya_next_attempt_at = NULL,
                maya_claim_token = NULL,
                maya_claim_owner = NULL,
                maya_claimed_at = NULL,
                maya_claim_expires_at = NULL,
                maya_dead_letter_at = ?,
                maya_dead_letter_reason = ?,
                updated_at = ?
            WHERE id = ?
              AND maya_delivery_status = 'pending'
              AND maya_drop_id IS NULL
              AND (
                    maya_claim_token IS NULL
                    OR maya_claim_owner IS NULL
                    OR maya_claim_expires_at IS NULL
                    OR julianday(maya_claim_expires_at) IS NULL
                    OR julianday(maya_claim_expires_at) <= julianday(?)
                  )
            """,
            (
                normalized_now,
                _safe_maya_dead_letter_reason(error_code),
                normalized_now,
                transcript_id,
                normalized_now,
            ),
        )
        conn.commit()
        return bool(cursor.rowcount)
    except Exception as e:
        if conn:
            conn.rollback()
        log.error(
            "Failed to mark Maya delivery dead-letter id=%s: %s",
            transcript_id,
            _safe_exception_class(e),
        )
        return False
    finally:
        if conn:
            conn.close()


def replay_maya_delivery(
    transcript_id: int,
    now: datetime | str | None = None,
) -> bool:
    """Explicitly reopen one failed/dead-letter row for a fresh bounded run."""
    conn = None
    try:
        normalized_now = _maya_now(now)
        conn = _get_conn()
        cursor = conn.execute(
            f"""
            UPDATE transcripts
            SET maya_delivery_status = 'pending',
                maya_delivery_attempt_count = 0,
                maya_first_attempt_at = NULL,
                maya_last_attempt_at = NULL,
                maya_dead_letter_at = NULL,
                maya_dead_letter_reason = NULL,
                maya_delivery_error = NULL,
                maya_next_attempt_at = NULL,
                maya_claim_token = NULL,
                maya_claim_owner = NULL,
                maya_claimed_at = NULL,
                maya_claim_expires_at = NULL,
                updated_at = ?
            WHERE id = ?
              AND maya_delivery_status IN ('failed', 'dead_letter')
              AND maya_drop_id IS NULL
              AND ({_maya_eligible_predicate()})
              AND (
                    maya_claim_token IS NULL
                    OR maya_claim_owner IS NULL
                    OR maya_claim_expires_at IS NULL
                    OR julianday(maya_claim_expires_at) IS NULL
                    OR julianday(maya_claim_expires_at) <= julianday(?)
                  )
            """,
            (normalized_now, transcript_id, normalized_now),
        )
        conn.commit()
        return bool(cursor.rowcount)
    except Exception as e:
        if conn:
            conn.rollback()
        log.error(
            "Failed to replay Maya delivery id=%s: %s",
            transcript_id,
            _safe_exception_class(e),
        )
        return False
    finally:
        if conn:
            conn.close()


def get_slack_delivery_health() -> dict[str, int]:
    conn = None
    health = {
        "pending_count": 0,
        "leased_count": 0,
        "expired_lease_count": 0,
        "uncertain_count": 0,
        "sent_count": 0,
        "failed_count": 0,
        "quality_failure_pending_count": 0,
        "quality_failure_leased_count": 0,
        "quality_failure_expired_lease_count": 0,
        "quality_failure_uncertain_count": 0,
        "quality_failure_failed_count": 0,
        "query_ok": 1,
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
            elif status == "delivering":
                health["leased_count"] = count
            elif status == "sent":
                health["sent_count"] = count
            elif status == "failed":
                health["failed_count"] = count
        health["expired_lease_count"] = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM slack_deliveries
                WHERE status = 'delivering'
                  AND slack_claim_expires_at <= datetime('now')
                """
            ).fetchone()[0]
        )
        health["uncertain_count"] = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM slack_deliveries
                WHERE last_error LIKE 'uncertain_delivery:%'
                  AND status != 'sent'
                """
            ).fetchone()[0]
        )
        quality_rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM quality_failure_slack_deliveries
            GROUP BY status
            """
        ).fetchall()
        for row in quality_rows:
            status = str(row["status"])
            if status == "pending":
                health["quality_failure_pending_count"] = int(row["count"])
            elif status == "delivering":
                health["quality_failure_leased_count"] = int(row["count"])
            elif status == "failed":
                health["quality_failure_failed_count"] = int(row["count"])
        health["quality_failure_expired_lease_count"] = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM quality_failure_slack_deliveries
                WHERE status = 'delivering'
                  AND slack_claim_expires_at <= datetime('now')
                """
            ).fetchone()[0]
        )
        health["quality_failure_uncertain_count"] = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM quality_failure_slack_deliveries
                WHERE last_error LIKE 'uncertain_delivery:%'
                  AND status != 'sent'
                """
            ).fetchone()[0]
        )
        return health
    except Exception as e:
        log.error(
            "Failed to fetch Slack delivery health: %s",
            _safe_exception_class(e),
        )
        health["health_error"] = 1
        health["query_ok"] = 0
        return health
    finally:
        if conn:
            conn.close()


def get_maya_delivery_health() -> dict[str, int]:
    """Return bounded, non-secret Maya outbox and quality-review health."""
    conn = None
    health = {
        "pending_count": 0,
        "due_count": 0,
        "failed_count": 0,
        "dead_letter_count": 0,
        "oldest_due_age_seconds": 0,
        "oldest_pending_age_seconds": 0,
        "max_attempt_count": 0,
        "quality_needs_review_count": 0,
        "query_ok": 1,
        "health_error": 0,
    }
    eligible_predicate = _maya_health_predicate()
    try:
        conn = _get_conn()
        row = conn.execute(
            f"""
            SELECT
                SUM(CASE
                    WHEN maya_delivery_status = 'pending'
                         AND {eligible_predicate}
                    THEN 1 ELSE 0 END
                ) AS pending_count,
                SUM(CASE
                    WHEN maya_delivery_status = 'pending'
                         AND {eligible_predicate}
                        AND (
                              maya_next_attempt_at IS NULL
                              OR julianday(maya_next_attempt_at) <= julianday('now')
                         )
                    THEN 1 ELSE 0 END
                ) AS due_count,
                SUM(CASE
                    WHEN maya_delivery_status = 'failed'
                         AND {eligible_predicate}
                    THEN 1 ELSE 0 END
                ) AS failed_count,
                SUM(CASE
                    WHEN maya_delivery_status = 'dead_letter'
                         AND {eligible_predicate}
                    THEN 1 ELSE 0 END
                ) AS dead_letter_count,
                MIN(CASE
                    WHEN maya_delivery_status = 'pending'
                         AND {eligible_predicate}
                         AND (
                              maya_next_attempt_at IS NULL
                              OR julianday(maya_next_attempt_at) <= julianday('now')
                         )
                    THEN created_at ELSE NULL END
                ) AS oldest_due_at,
                MIN(CASE
                    WHEN maya_delivery_status = 'pending'
                         AND {eligible_predicate}
                    THEN COALESCE(maya_first_attempt_at, created_at) ELSE NULL END
                ) AS oldest_pending_at,
                MAX(CASE
                    WHEN {eligible_predicate}
                    THEN COALESCE(maya_delivery_attempt_count, 0) ELSE 0 END
                ) AS max_attempt_count,
                SUM(CASE WHEN quality_status = 'needs_review' THEN 1 ELSE 0 END)
                    AS quality_needs_review_count
            FROM transcripts
            """
        ).fetchone()
        if row is None:
            return health
        health["pending_count"] = int(row["pending_count"] or 0)
        health["due_count"] = int(row["due_count"] or 0)
        health["failed_count"] = int(row["failed_count"] or 0)
        health["dead_letter_count"] = int(row["dead_letter_count"] or 0)
        health["max_attempt_count"] = int(row["max_attempt_count"] or 0)
        health["quality_needs_review_count"] = int(
            row["quality_needs_review_count"] or 0
        )
        for field, output_key in (
            ("oldest_due_at", "oldest_due_age_seconds"),
            ("oldest_pending_at", "oldest_pending_age_seconds"),
        ):
            timestamp = row[field]
            if not timestamp:
                continue
            age_row = conn.execute(
                """
                SELECT CAST(
                    MAX(0, (julianday('now') - julianday(?)) * 86400)
                    AS INTEGER
                )
                """,
                (timestamp,),
            ).fetchone()
            health[output_key] = min(int(age_row[0] or 0), 2_147_483_647)
        return health
    except Exception as e:
        log.error(
            "Failed to fetch Maya delivery health: %s",
            _safe_exception_class(e),
        )
        health["query_ok"] = 0
        health["health_error"] = 1
        return health
    finally:
        if conn:
            conn.close()


def _queue_archive_delivery_conn(
    conn: sqlite3.Connection,
    transcript_id: int,
    staged: Any,
    metadata: dict[str, Any] | None = None,
) -> None:
    metadata = dict(metadata or {})
    canonical = conn.execute(
        "SELECT source, audio_sha256, recorded_at, duration_seconds "
        "FROM transcripts WHERE id = ?",
        (transcript_id,),
    ).fetchone()
    if canonical is None:
        raise LookupError("Canonical transcript row does not exist")
    existing_hash = canonical["audio_sha256"]
    if existing_hash and existing_hash != staged.audio_sha256:
        raise ValueError("Canonical archive audio hash conflict")

    existing = conn.execute(
        "SELECT source_aliases, status, alias_set_sha256, publication_generation, "
        "availability_status "
        "FROM archive_deliveries "
        "WHERE transcript_row_id = ?",
        (transcript_id,),
    ).fetchone()
    aliases = {
        str(canonical["source"]),
        str(metadata.get("source") or canonical["source"]),
    }
    alias = metadata.get("source_alias")
    if alias:
        aliases.add(str(alias))
    aliases.update(str(value) for value in metadata.get("source_aliases", []) if value)
    if existing is not None:
        aliases.update(_json_loads_or_default(existing["source_aliases"], []))
    aliases_json = json.dumps(
        sorted(aliases), separators=(",", ":"), ensure_ascii=False
    )
    alias_set_sha256 = hashlib.sha256(aliases_json.encode("utf-8")).hexdigest()

    backend = metadata.get("backend")
    model = metadata.get("model")
    conn.execute(
        """
        UPDATE transcripts
        SET audio_sha256 = ?,
            transcription_backend = COALESCE(?, transcription_backend),
            transcription_model = COALESCE(?, transcription_model),
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (staged.audio_sha256, backend, model, transcript_id),
    )
    values = (
        str(staged.path),
        staged.audio_sha256,
        int(staged.byte_length),
        staged.extension,
        str(metadata.get("source") or canonical["source"]),
        aliases_json,
        metadata.get("original_name"),
        metadata.get("captured_at") or canonical["recorded_at"],
        metadata.get("ingested_at"),
        metadata.get("duration_seconds")
        if metadata.get("duration_seconds") is not None
        else canonical["duration_seconds"],
        metadata.get("mime_type"),
    )
    if existing is None:
        conn.execute(
            """
            INSERT INTO archive_deliveries (
                transcript_row_id, local_object_path, audio_sha256, byte_length,
                extension, archive_source, source_aliases, original_name,
                recorded_at, ingested_at, archive_duration_seconds, mime_type,
                alias_set_sha256, availability_status, publication_scope
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'available', 'local_mirror')
            """,
            (transcript_id, *values, alias_set_sha256),
        )
    elif (
        existing["alias_set_sha256"] != alias_set_sha256
        or existing["availability_status"] != "available"
    ):
        next_generation = int(existing["publication_generation"] or 1)
        if existing["status"] == "published":
            next_generation += 1
        conn.execute(
            """
            UPDATE archive_deliveries
            SET local_object_path = ?, audio_sha256 = ?, byte_length = ?,
                extension = ?, archive_source = ?, source_aliases = ?,
                original_name = COALESCE(original_name, ?),
                recorded_at = COALESCE(recorded_at, ?),
                ingested_at = COALESCE(ingested_at, ?),
                archive_duration_seconds = COALESCE(archive_duration_seconds, ?),
                mime_type = COALESCE(mime_type, ?), alias_set_sha256 = ?,
                publication_generation = ?, status = 'pending',
                availability_status = 'available', unavailable_reason = NULL,
                validation_status = 'pending', validation_error_code = NULL,
                rebuild_needed = 0, next_attempt_at = NULL,
                updated_at = datetime('now')
            WHERE transcript_row_id = ?
            """,
            (*values, alias_set_sha256, next_generation, transcript_id),
        )


def queue_archive_delivery(
    transcript_id: int,
    staged: Any,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Persist or reconcile the unique archive job after its canonical row exists."""
    conn = None
    try:
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        _queue_archive_delivery_conn(conn, transcript_id, staged, metadata)
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def get_pending_archive_deliveries(limit: int = 5) -> list[dict[str, Any]]:
    conn = None
    try:
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT deliveries.*, transcripts.source, transcripts.transcript,
                   transcripts.created_at, transcripts.recorded_at AS canonical_recorded_at,
                   deliveries.recorded_at AS archive_recorded_at,
                   transcripts.quality_status,
                   transcripts.transcription_backend, transcripts.transcription_model
            FROM archive_deliveries AS deliveries
            JOIN transcripts ON transcripts.id = deliveries.transcript_row_id
            WHERE deliveries.status = 'pending'
              AND (deliveries.next_attempt_at IS NULL
                   OR deliveries.next_attempt_at <= datetime('now'))
            ORDER BY deliveries.id
            LIMIT ?
            """,
            (max(0, min(int(limit), 100)),),
        ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        log.error("Failed to fetch archive deliveries due to a database error")
        return []
    finally:
        if conn:
            conn.close()


def get_published_archive_deliveries(limit: int = 10) -> list[dict[str, Any]]:
    conn = None
    try:
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT * FROM archive_deliveries
            WHERE status = 'published' AND publication_scope = 'local_mirror'
            ORDER BY COALESCE(last_validated_at, local_mirror_published_at, created_at)
            LIMIT ?
            """,
            (max(0, min(int(limit), 100)),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        if conn:
            conn.close()


def mark_archive_delivery_validated(delivery_id: int) -> None:
    conn = None
    try:
        conn = _get_conn()
        conn.execute(
            """
            UPDATE archive_deliveries
            SET validation_status = 'valid', validation_error_code = NULL,
                last_validated_at = datetime('now'), rebuild_needed = 0,
                updated_at = datetime('now')
            WHERE id = ? AND status = 'published'
            """,
            (delivery_id,),
        )
        conn.commit()
    finally:
        if conn:
            conn.close()


def mark_archive_delivery_rebuild_needed(
    delivery_id: int, reason_code: str = "local_mirror_validation_failed"
) -> None:
    safe_reason = (
        reason_code
        if reason_code in {
            "local_mirror_validation_failed",
            "local_mirror_missing",
            "local_mirror_receipt_mismatch",
            "local_mirror_path_outside_root",
        }
        else "local_mirror_validation_failed"
    )
    conn = None
    try:
        conn = _get_conn()
        cursor = conn.execute(
            """
            UPDATE archive_deliveries
            SET status = 'pending', publication_generation = publication_generation + 1,
                validation_status = 'invalid', validation_error_code = ?,
                last_validated_at = datetime('now'), rebuild_needed = 1,
                destination_audio_path = NULL, destination_markdown_path = NULL,
                destination_manifest_path = NULL, receipt_sha256 = NULL,
                next_attempt_at = NULL, updated_at = datetime('now')
            WHERE id = ? AND status = 'published'
            """,
            (safe_reason, delivery_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Archive delivery is not published")
        conn.commit()
    finally:
        if conn:
            conn.close()


def get_archive_backfill_candidates(limit: int = 10) -> list[dict[str, Any]]:
    """Return a bounded historical set lacking any archive applicability row."""
    conn = None
    try:
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT transcripts.id AS transcript_row_id, transcripts.source,
                   transcripts.transcript, transcripts.audio_path AS transcript_audio_path,
                   transcripts.audio_sha256, transcripts.recorded_at,
                   transcripts.created_at, transcripts.duration_seconds,
                   transcripts.quality_status, transcripts.transcription_backend,
                   transcripts.transcription_model,
                   (
                       SELECT voice_memo_ingest.audio_path
                       FROM voice_memo_ingest
                       WHERE voice_memo_ingest.transcript_row_id = transcripts.id
                         AND voice_memo_ingest.audio_path IS NOT NULL
                       ORDER BY voice_memo_ingest.recording_pk
                       LIMIT 1
                   ) AS voice_audio_path
            FROM transcripts
            LEFT JOIN archive_deliveries
              ON archive_deliveries.transcript_row_id = transcripts.id
            WHERE archive_deliveries.id IS NULL
               OR (
                    archive_deliveries.status = 'backfill_pending'
                    AND (archive_deliveries.next_attempt_at IS NULL
                         OR archive_deliveries.next_attempt_at <= datetime('now'))
               )
               OR (
                    archive_deliveries.status = 'unavailable'
                    AND archive_deliveries.unavailable_reason =
                        'migration_missing_archive_metadata'
               )
            ORDER BY transcripts.id
            LIMIT ?
            """,
            (max(0, min(int(limit), 100)),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        if conn:
            conn.close()


_ARCHIVE_AVAILABILITY_REASONS = frozenset(
    {
        "legacy_placeholder",
        "missing_audio_source",
        "no_raw_audio",
        "source_unavailable",
        "unsafe_audio_source",
        "invalid_local_object",
    }
)


def _record_archive_unavailable_conn(
    conn: sqlite3.Connection,
    transcript_id: int,
    *,
    availability_status: str,
    reason_code: str,
) -> None:
    if availability_status not in {"unavailable", "not_applicable"}:
        raise ValueError("Invalid archive availability status")
    if reason_code not in _ARCHIVE_AVAILABILITY_REASONS:
        reason_code = "source_unavailable"
    canonical = conn.execute(
            "SELECT source, recorded_at, duration_seconds FROM transcripts WHERE id = ?",
            (transcript_id,),
        ).fetchone()
    if canonical is None:
        raise LookupError("Canonical transcript row does not exist")
    aliases_json = json.dumps(
        [str(canonical["source"])], separators=(",", ":"), ensure_ascii=False
    )
    alias_hash = hashlib.sha256(aliases_json.encode("utf-8")).hexdigest()
    conn.execute(
            """
            INSERT INTO archive_deliveries (
                transcript_row_id, archive_source, source_aliases, recorded_at,
                archive_duration_seconds, status, availability_status,
                unavailable_reason, alias_set_sha256, publication_scope,
                validation_status, validation_error_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'local_mirror', 'not_applicable', ?)
            ON CONFLICT(transcript_row_id) DO UPDATE SET
                status = excluded.status,
                availability_status = excluded.availability_status,
                unavailable_reason = excluded.unavailable_reason,
                validation_status = excluded.validation_status,
                validation_error_code = excluded.validation_error_code,
                updated_at = datetime('now')
            WHERE archive_deliveries.status IN ('unavailable', 'not_applicable')
              AND archive_deliveries.availability_status IN (
                  'unavailable', 'not_applicable'
              )
              AND archive_deliveries.local_object_path IS NULL
              AND archive_deliveries.audio_sha256 IS NULL
              AND archive_deliveries.receipt_sha256 IS NULL
            """,
            (
                transcript_id,
                canonical["source"],
                aliases_json,
                canonical["recorded_at"],
                canonical["duration_seconds"],
                availability_status,
                availability_status,
                reason_code,
                alias_hash,
                reason_code,
            ),
    )


def record_archive_unavailable(
    transcript_id: int,
    *,
    availability_status: str,
    reason_code: str,
) -> None:
    conn = None
    try:
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        _record_archive_unavailable_conn(
            conn,
            transcript_id,
            availability_status=availability_status,
            reason_code=reason_code,
        )
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


_ARCHIVE_BACKFILL_ERROR_CODES = frozenset(
    {"archive_backfill_queue_error", "archive_backfill_source_error"}
)


def record_archive_backfill_failure(transcript_id: int, error_code: str) -> None:
    """Persist a bounded retry state for recoverable historical archive work."""
    safe_code = (
        error_code
        if error_code in _ARCHIVE_BACKFILL_ERROR_CODES
        else "archive_backfill_source_error"
    )
    conn = None
    try:
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        canonical = conn.execute(
            "SELECT source, recorded_at, duration_seconds FROM transcripts WHERE id = ?",
            (transcript_id,),
        ).fetchone()
        if canonical is None:
            raise LookupError("Canonical transcript row does not exist")
        aliases_json = json.dumps(
            [str(canonical["source"])], separators=(",", ":"), ensure_ascii=False
        )
        alias_hash = hashlib.sha256(aliases_json.encode("utf-8")).hexdigest()
        conn.execute(
            """
            INSERT INTO archive_deliveries (
                transcript_row_id, archive_source, source_aliases, recorded_at,
                archive_duration_seconds, status, availability_status,
                attempt_count, next_attempt_at, last_error_code,
                alias_set_sha256, publication_scope, validation_status
            ) VALUES (?, ?, ?, ?, ?, 'backfill_pending', 'retryable', 1,
                      datetime('now', '+30 seconds'), ?, ?, 'local_mirror', 'pending')
            ON CONFLICT(transcript_row_id) DO UPDATE SET
                attempt_count = archive_deliveries.attempt_count + 1,
                status = CASE
                    WHEN archive_deliveries.attempt_count + 1 >= ?
                    THEN 'backfill_failed' ELSE 'backfill_pending' END,
                availability_status = 'retryable',
                next_attempt_at = CASE
                    WHEN archive_deliveries.attempt_count + 1 >= ? THEN NULL
                    ELSE datetime(
                        'now', '+' || MIN(
                            3600, 30 * (1 << archive_deliveries.attempt_count)
                        ) || ' seconds'
                    )
                END,
                last_error_code = excluded.last_error_code,
                updated_at = datetime('now')
            """,
            (
                transcript_id, canonical["source"], aliases_json,
                canonical["recorded_at"], canonical["duration_seconds"],
                safe_code, alias_hash, ARCHIVE_MAX_ATTEMPTS, ARCHIVE_MAX_ATTEMPTS,
            ),
        )
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def needs_archive_delivery(content_hash: str) -> bool:
    """Return whether a canonical row still lacks its durable archive job."""
    conn = None
    try:
        conn = _get_conn()
        row = conn.execute(
            """
            SELECT deliveries.id
            FROM transcripts
            LEFT JOIN archive_deliveries AS deliveries
              ON deliveries.transcript_row_id = transcripts.id
            WHERE transcripts.content_hash = ?
            """,
            (content_hash,),
        ).fetchone()
        return row is not None and row["id"] is None
    except sqlite3.Error:
        log.error("Failed to check archive reconciliation due to a database error")
        return True
    finally:
        if conn:
            conn.close()


def mark_archive_delivery_failed(delivery_id: int, error_message: str) -> None:
    """Record only a bounded operational class, never transcript/error content."""
    del error_message
    conn = None
    try:
        conn = _get_conn()
        conn.execute(
            """
            UPDATE archive_deliveries
            SET attempt_count = attempt_count + 1,
                status = CASE WHEN attempt_count + 1 >= ? THEN 'failed' ELSE 'pending' END,
                next_attempt_at = CASE
                    WHEN attempt_count + 1 >= ? THEN NULL
                    ELSE datetime('now', '+' || MIN(3600, 30 * (1 << attempt_count)) || ' seconds')
                END,
                last_error_code = 'archive_publish_error',
                updated_at = datetime('now')
            WHERE id = ? AND status != 'published'
            """,
            (ARCHIVE_MAX_ATTEMPTS, ARCHIVE_MAX_ATTEMPTS, delivery_id),
        )
        conn.commit()
    finally:
        if conn:
            conn.close()


def mark_archive_delivery_published(
    delivery_id: int,
    *,
    audio_path: str,
    markdown_path: str,
    manifest_path: str,
    receipt_sha256: str,
) -> None:
    conn = None
    try:
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT transcript_row_id, publication_generation, alias_set_sha256, "
            "source_aliases FROM archive_deliveries WHERE id = ?",
            (delivery_id,),
        ).fetchone()
        if row is None:
            raise LookupError("Archive delivery does not exist")
        existing_publication = conn.execute(
            """
            SELECT alias_set_sha256, source_aliases, destination_audio_path,
                   destination_markdown_path, destination_manifest_path,
                   receipt_sha256
            FROM archive_publications
            WHERE archive_delivery_id = ? AND publication_generation = ?
            """,
            (delivery_id, row["publication_generation"]),
        ).fetchone()
        expected_publication = (
            row["alias_set_sha256"], row["source_aliases"], audio_path,
            markdown_path, manifest_path, receipt_sha256,
        )
        if existing_publication is not None:
            if tuple(existing_publication) != expected_publication:
                raise sqlite3.IntegrityError(
                    "archive publication generation already has a different receipt"
                )
        else:
            conn.execute(
                "UPDATE archive_publications SET superseded_at = datetime('now') "
                "WHERE archive_delivery_id = ? AND superseded_at IS NULL",
                (delivery_id,),
            )
            conn.execute(
                """
                INSERT INTO archive_publications (
                    archive_delivery_id, transcript_row_id, publication_generation,
                    alias_set_sha256, source_aliases, destination_audio_path,
                    destination_markdown_path, destination_manifest_path,
                    receipt_sha256, publication_scope
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'local_mirror')
                """,
                (
                    delivery_id, row["transcript_row_id"], row["publication_generation"],
                    *expected_publication,
                ),
            )
        conn.execute(
            """
            UPDATE archive_deliveries
            SET status = 'published', next_attempt_at = NULL,
                last_error_code = NULL, destination_audio_path = ?,
                destination_markdown_path = ?, destination_manifest_path = ?,
                receipt_sha256 = ?, published_at = datetime('now'),
                local_mirror_published_at = datetime('now'),
                publication_scope = 'local_mirror', validation_status = 'valid',
                validation_error_code = NULL, last_validated_at = datetime('now'),
                rebuild_needed = 0,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (audio_path, markdown_path, manifest_path, receipt_sha256, delivery_id),
        )
        conn.commit()
    finally:
        if conn:
            conn.close()


def get_archive_delivery_health() -> dict[str, int]:
    health = {
        "pending_count": 0,
        "sent_count": 0,
        "local_mirror_published_count": 0,
        "failed_count": 0,
        "unavailable_count": 0,
        "not_applicable_count": 0,
        "invalid_count": 0,
        "rebuild_needed_count": 0,
        "backfill_pending_count": 0,
        "backfill_failed_count": 0,
        "oldest_pending_age_seconds": 0,
        "health_error": 0,
    }
    conn = None
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM archive_deliveries GROUP BY status"
        ).fetchall()
        for row in rows:
            key = {
                "pending": "pending_count",
                "published": "sent_count",
                "failed": "failed_count",
                "unavailable": "unavailable_count",
                "not_applicable": "not_applicable_count",
                "backfill_pending": "backfill_pending_count",
                "backfill_failed": "backfill_failed_count",
            }.get(str(row["status"]))
            if key:
                health[key] = int(row["count"])
                if str(row["status"]) == "published":
                    health["local_mirror_published_count"] = int(row["count"])
        age = conn.execute(
            """
            SELECT CAST(MAX(0, (julianday('now') - julianday(MIN(created_at))) * 86400)
                        AS INTEGER)
            FROM archive_deliveries WHERE status = 'pending'
            """
        ).fetchone()
        health["oldest_pending_age_seconds"] = int(age[0] or 0)
        validation = conn.execute(
            """
            SELECT
                SUM(CASE WHEN validation_status = 'invalid' THEN 1 ELSE 0 END),
                SUM(CASE WHEN rebuild_needed = 1 THEN 1 ELSE 0 END)
            FROM archive_deliveries
            """
        ).fetchone()
        health["invalid_count"] = int(validation[0] or 0)
        health["rebuild_needed_count"] = int(validation[1] or 0)
        return health
    except Exception as exc:
        log.error("Failed to fetch archive health: %s", _safe_exception_class(exc))
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


def _get_transcript_by_hash_strict(content_hash: str) -> dict[str, Any] | None:
    """Fetch a transcript row by hash while preserving SQLite failures."""
    conn = None
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM transcripts WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        if conn:
            conn.close()


def get_transcript_by_hash(content_hash: str) -> dict[str, Any] | None:
    """Fetch a transcript row by content hash."""
    try:
        return _get_transcript_by_hash_strict(content_hash)
    except Exception as e:
        log.error("Failed to fetch transcript by hash: %s", e)
        return None


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


def get_maya_delivery(transcript_id: int) -> dict[str, Any] | None:
    """Return the canonical row carrying one Maya delivery state."""
    return get_transcript(transcript_id)


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


def _apple_effect_now(value: datetime | str | None = None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, datetime):
        current = value
    else:
        current = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _apple_effect_safe_code(value: str | None, default: str = "provider_error") -> str:
    candidate = str(value or "").strip().lower()
    if candidate in APPLE_EFFECT_SAFE_ERROR_CODES:
        return candidate
    return default


def get_apple_effect(effect_key: str) -> dict[str, Any] | None:
    """Return one operational Apple-effect row without provider content."""
    if not isinstance(effect_key, str) or not effect_key:
        return None
    conn = None
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM apple_effects WHERE effect_key = ?", (effect_key,)
        ).fetchone()
        return dict(row) if row else None
    except sqlite3.Error:
        log.error("Failed to read Apple effect ledger")
        return None
    finally:
        if conn:
            conn.close()


def claim_apple_effect(
    *,
    effect_key: str,
    transcript_id: int,
    effect_type: str,
    requested_target: str,
    fallback_target: str = "",
    payload_sha256: str,
    now: datetime | str | None = None,
    lease_seconds: int = APPLE_EFFECT_LEASE_SECONDS,
    lease_owner: str | None = None,
) -> dict[str, Any]:
    """Insert or CAS-claim one effect while holding SQLite's write lock.

    The returned dictionary includes ``claimable``.  Callers must release the
    lock before invoking AppleScript; an active unexpired claim is never
    allowed to create a provider object concurrently.
    """
    if not isinstance(transcript_id, int) or transcript_id <= 0:
        return {"effect_key": effect_key, "state": "failed", "claimable": False,
                "error_code": "canonical_id_required"}
    if not re.fullmatch(r"[0-9a-f]{64}", str(effect_key or "")):
        return {"effect_key": str(effect_key or ""), "state": "failed",
                "claimable": False, "error_code": "invalid_effect"}
    if effect_type not in APPLE_EFFECT_TYPES:
        return {"effect_key": effect_key, "state": "failed", "claimable": False,
                "error_code": "invalid_effect"}
    if not re.fullmatch(r"[0-9a-f]{64}", str(payload_sha256 or "")):
        return {"effect_key": effect_key, "state": "failed", "claimable": False,
                "error_code": "invalid_effect"}
    requested_target = str(requested_target or "").strip()
    fallback_target = str(fallback_target or "").strip()
    if not requested_target:
        return {"effect_key": effect_key, "state": "failed", "claimable": False,
                "error_code": "invalid_effect"}
    now_iso = _apple_effect_now(now)
    try:
        now_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    except ValueError:
        now_dt = datetime.now(timezone.utc)
    try:
        lease_seconds = max(1, min(int(lease_seconds), 3600))
    except (TypeError, ValueError):
        lease_seconds = APPLE_EFFECT_LEASE_SECONDS
    lease_until = (
        now_dt + timedelta(seconds=lease_seconds)
    ).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    owner = str(lease_owner or hashlib.sha256(
        f"{effect_key}\0{now_iso}".encode("utf-8")
    ).hexdigest()[:32])
    conn = None
    try:
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM apple_effects WHERE effect_key = ?", (effect_key,)
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO apple_effects (
                    effect_key, transcript_id, effect_type, requested_target,
                    fallback_target, payload_sha256, state, attempt_count,
                    lease_owner, lease_expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'in_flight', 1, ?, ?, ?, ?)
                """,
                (effect_key, transcript_id, effect_type, requested_target,
                 fallback_target, payload_sha256, owner, lease_until,
                 now_iso, now_iso),
            )
            row = conn.execute(
                "SELECT * FROM apple_effects WHERE effect_key = ?", (effect_key,)
            ).fetchone()
            conn.commit()
            result = dict(row)
            result.update({"claimable": True, "lease_owner": owner})
            return result

        result = dict(row)
        dimensions_match = (
            int(result["transcript_id"]) == transcript_id
            and result["effect_type"] == effect_type
            and result["requested_target"] == requested_target
            and result["fallback_target"] == fallback_target
            and result["payload_sha256"] == payload_sha256
        )
        if result["state"] == "succeeded" and not dimensions_match:
            # A durable provider receipt is monotonic.  A later caller with a
            # conflicting dimension must fail closed without downgrading it.
            conn.commit()
            result.update({"claimable": False, "error_code": "effect_key_conflict"})
            return result
        if result["state"] == "quarantined":
            conn.commit()
            result.update({"claimable": False, "error_code": result.get("last_error_code") or "marker_conflict"})
            return result
        if not dimensions_match:
            foreign_lease_active = False
            if result["state"] == "in_flight" and result.get("lease_expires_at"):
                try:
                    foreign_lease_active = (
                        datetime.fromisoformat(
                            str(result["lease_expires_at"]).replace("Z", "+00:00")
                        ) > now_dt
                        and result.get("lease_owner") != owner
                    )
                except ValueError:
                    foreign_lease_active = False
            if foreign_lease_active:
                conn.commit()
                result.update(
                    {"claimable": False, "error_code": "effect_key_conflict"}
                )
                return result
            conn.execute(
                """UPDATE apple_effects
                   SET state = 'quarantined', last_error_code = ?,
                       lease_owner = NULL, lease_expires_at = NULL,
                       updated_at = ? WHERE effect_key = ?""",
                ("effect_key_conflict", now_iso, effect_key),
            )
            conn.commit()
            result.update({"state": "quarantined", "claimable": False,
                           "error_code": "effect_key_conflict"})
            return result
        if result["state"] == "succeeded":
            conn.commit()
            result["claimable"] = False
            return result
        lease_expired = True
        if result["state"] == "in_flight" and result.get("lease_expires_at"):
            try:
                lease_expired = datetime.fromisoformat(
                    str(result["lease_expires_at"]).replace("Z", "+00:00")
                ) <= now_dt
            except ValueError:
                lease_expired = True
        if result["state"] == "in_flight" and not lease_expired:
            conn.commit()
            result.update({"claimable": False, "error_code": "active_claim"})
            return result
        conn.execute(
            """UPDATE apple_effects
               SET state = 'in_flight', attempt_count = attempt_count + 1,
                   lease_owner = ?, lease_expires_at = ?,
                   stale_attempt_at = CASE WHEN state = 'in_flight' THEN ? ELSE stale_attempt_at END,
                   last_error_code = NULL, updated_at = ?
               WHERE effect_key = ?
                 AND state != 'succeeded'""",
            (owner, lease_until, now_iso, now_iso, effect_key),
        )
        row = conn.execute(
            "SELECT * FROM apple_effects WHERE effect_key = ?", (effect_key,)
        ).fetchone()
        conn.commit()
        result = dict(row)
        result.update({"claimable": True, "lease_owner": owner})
        return result
    except sqlite3.IntegrityError:
        if conn:
            conn.rollback()
        return {"effect_key": effect_key, "state": "failed", "claimable": False,
                "error_code": "canonical_id_required"}
    except sqlite3.Error:
        if conn:
            conn.rollback()
        return {"effect_key": effect_key, "state": "failed", "claimable": False,
                "error_code": "database_unavailable"}
    finally:
        if conn:
            conn.close()


def reserve_apple_effect(**kwargs: Any) -> dict[str, Any]:
    """Compatibility name for the CAS claim primitive."""
    return claim_apple_effect(**kwargs)


def mark_apple_effect_succeeded(
    effect_key: str,
    provider_id: str,
    actual_target: str | None = None,
    *,
    reconciled: bool = False,
    lease_owner: str | None = None,
) -> bool:
    """Persist a provider receipt monotonically; reject conflicting IDs."""
    provider_id = str(provider_id or "").strip()
    if not provider_id:
        return False
    conn = None
    try:
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT state, provider_id, effect_type, lease_owner "
            "FROM apple_effects WHERE effect_key = ?",
            (effect_key,),
        ).fetchone()
        if row is None:
            conn.rollback()
            return False
        if row["state"] == "succeeded":
            if row["provider_id"] != provider_id:
                conn.commit()
                return False
            conn.commit()
            return True
        if not lease_owner or row["lease_owner"] != lease_owner:
            conn.commit()
            return False
        now_iso = _apple_effect_now()
        existing_provider = conn.execute(
            """SELECT effect_key FROM apple_effects
               WHERE effect_type = ? AND provider_id = ?
                 AND effect_key != ? AND state = 'succeeded'
               LIMIT 1""",
            (row["effect_type"], provider_id, effect_key),
        ).fetchone()
        if existing_provider is not None:
            conn.execute(
                """UPDATE apple_effects SET state='quarantined',
                    last_error_code='provider_conflict', lease_owner=NULL,
                    lease_expires_at=NULL, updated_at=?
                    WHERE effect_key=? AND state != 'succeeded'
                      AND lease_owner=?""",
                (now_iso, effect_key, lease_owner),
            )
            conn.commit()
            return False
        params: list[Any] = [provider_id, actual_target, 1 if reconciled else 0,
                             now_iso, now_iso, effect_key, lease_owner]
        cursor = conn.execute(
            """UPDATE apple_effects
               SET state='succeeded', provider_id=?, actual_target=?,
                   reconciled=?, lease_owner=NULL, lease_expires_at=NULL,
                   last_error_code=NULL, succeeded_at=?, updated_at=?
               WHERE effect_key=? AND lease_owner=?
                 AND state NOT IN ('succeeded', 'quarantined')""",
            tuple(params),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return False
        conn.commit()
        return True
    except sqlite3.Error:
        if conn:
            conn.rollback()
        log.error("Failed to persist Apple effect receipt")
        return False
    finally:
        if conn:
            conn.close()


def mark_apple_effect_uncertain(
    effect_key: str,
    error_code: str = "timeout_uncertain",
    *,
    lease_owner: str | None = None,
) -> bool:
    code = _apple_effect_safe_code(error_code)
    conn = None
    try:
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        if not lease_owner:
            conn.rollback()
            return False
        now_iso = _apple_effect_now()
        params: list[Any] = [code, now_iso, effect_key, lease_owner]
        cursor = conn.execute(
            f"""UPDATE apple_effects SET state='uncertain', last_error_code=?,
                lease_owner=NULL, lease_expires_at=NULL, updated_at=?
                WHERE effect_key=? AND lease_owner=?
                  AND state NOT IN ('succeeded', 'quarantined')""",
            tuple(params),
        )
        conn.commit()
        return cursor.rowcount == 1
    except sqlite3.Error:
        if conn:
            conn.rollback()
        log.error("Failed to mark Apple effect uncertain")
        return False
    finally:
        if conn:
            conn.close()


def mark_apple_effect_failed(
    effect_key: str,
    error_code: str = "provider_error",
    *,
    quarantine: bool = False,
    lease_owner: str | None = None,
) -> bool:
    code = _apple_effect_safe_code(error_code)
    state = "quarantined" if quarantine else "failed"
    conn = None
    try:
        conn = _get_conn()
        conn.execute("BEGIN IMMEDIATE")
        if not lease_owner:
            conn.rollback()
            return False
        now_iso = _apple_effect_now()
        cursor = conn.execute(
            f"""UPDATE apple_effects SET state=?, last_error_code=?,
                lease_owner=NULL, lease_expires_at=NULL, updated_at=?
                WHERE effect_key=? AND lease_owner=?
                  AND state NOT IN ('succeeded', 'quarantined')""",
            (state, code, now_iso, effect_key, lease_owner),
        )
        conn.commit()
        return cursor.rowcount == 1
    except sqlite3.Error:
        if conn:
            conn.rollback()
        log.error("Failed to mark Apple effect failure")
        return False
    finally:
        if conn:
            conn.close()


def get_apple_effect_health() -> dict[str, Any]:
    """Aggregate Apple-effect state without returning content or provider data."""
    health: dict[str, Any] = {
        "query_ok": 1, "health_error": 0, "total_count": 0,
        "reserved_count": 0, "in_flight_count": 0, "uncertain_count": 0,
        "succeeded_count": 0, "failed_count": 0, "quarantined_count": 0,
        "stale_in_flight_count": 0, "migration_quarantine_count": 0,
    }
    conn = None
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT state, COUNT(*) AS count FROM apple_effects GROUP BY state"
        ).fetchall()
        for row in rows:
            health[f"{row['state']}_count"] = int(row["count"])
        health["total_count"] = sum(
            int(row["count"]) for row in rows
        )
        health["migration_quarantine_count"] = int(
            conn.execute("SELECT COUNT(*) FROM apple_effect_quarantine").fetchone()[0]
        )
        now = datetime.now(timezone.utc)
        stale = 0
        for row in conn.execute(
            "SELECT lease_expires_at FROM apple_effects "
            "WHERE state='in_flight' AND lease_expires_at IS NOT NULL"
        ).fetchall():
            try:
                expiry = datetime.fromisoformat(
                    str(row[0]).replace("Z", "+00:00")
                )
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry <= now:
                    stale += 1
            except ValueError:
                stale += 1
        health["stale_in_flight_count"] = stale
        return health
    except sqlite3.Error:
        health["query_ok"] = 0
        health["health_error"] = 1
        return health
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
    recorded_at: str | None = None,
) -> bool:
    conn = None
    try:
        conn = _get_conn()
        conn.execute(
            """INSERT INTO voice_memo_ingest (
                   recording_pk, label, raw_path, duration_seconds, recorded_at,
                   status, discovered_at, last_seen_at, updated_at
               )
               VALUES (?, ?, ?, ?, ?, 'discovered', datetime('now'), datetime('now'), datetime('now'))
               ON CONFLICT(recording_pk) DO UPDATE SET
                   label = excluded.label,
                   raw_path = excluded.raw_path,
                   duration_seconds = excluded.duration_seconds,
                   recorded_at = COALESCE(excluded.recorded_at, voice_memo_ingest.recorded_at),
                   last_seen_at = datetime('now'),
                   updated_at = datetime('now')""",
            (
                recording_pk,
                label,
                raw_path,
                duration_seconds,
                _as_iso8601_utc(recorded_at) if recorded_at is not None else None,
            ),
        )
        conn.commit()
        return True
    except Exception as e:
        log.error("Failed to upsert voice memo state pk=%s: %s", recording_pk, e)
        return False
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
                   error_message = 'file_not_downloaded',
                   file_missing_count = file_missing_count + 1,
                   updated_at = datetime('now')
               WHERE recording_pk = ?""",
            (recording_pk,),
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
) -> bool:
    conn = None
    try:
        conn = _get_conn()
        status = "routed" if routed else "transcribed"
        routed_sql = ", routed_at = datetime('now')" if routed else ""
        cursor = conn.execute(
            f"""UPDATE voice_memo_ingest
                SET transcript_row_id = ?,
                    content_hash = ?,
                    audio_path = ?,
                    status = ?,
                    transcribed_at = datetime('now'),
                    error_message = NULL,
                    retryable = 0,
                    next_attempt_at = NULL,
                    updated_at = datetime('now')
                    {routed_sql}
                WHERE recording_pk = ?""",
            (transcript_row_id, content_hash, audio_path, status, recording_pk),
        )
        conn.commit()
        return cursor.rowcount == 1
    except Exception as e:
        log.error("Failed to link voice memo transcript pk=%s: %s", recording_pk, e)
        return False
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
                   retryable = 0, next_attempt_at = NULL, terminal_at = datetime('now'),
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
                   retryable = 0, next_attempt_at = NULL, terminal_at = datetime('now'),
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


def _voice_memo_error_code(error_code: str) -> str:
    return error_code if error_code in VOICE_MEMO_RETRY_ERROR_CODES else "processing_error"


def _voice_memo_now(now: str | None) -> datetime:
    value = datetime.now(timezone.utc) if now is None else datetime.fromisoformat(now.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _voice_memo_iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def mark_voice_memo_retryable(
    recording_pk: int, error_code: str, *, now: str | None = None
) -> None:
    """Schedule an unlinked source record for a bounded retry."""
    conn = None
    try:
        conn = _get_conn()
        row = conn.execute(
            """SELECT attempt_count, transcript_row_id FROM voice_memo_ingest
               WHERE recording_pk = ?""",
            (recording_pk,),
        ).fetchone()
        if row is None or row["transcript_row_id"] is not None:
            return
        attempt_count = int(row["attempt_count"] or 0) + 1
        attempted_at = _voice_memo_now(now)
        terminal = attempt_count >= VOICE_MEMO_MAX_ATTEMPTS
        next_attempt_at = None
        if not terminal:
            backoff_seconds = min(30 * 2 ** (attempt_count - 1), 1800)
            next_attempt_at = _voice_memo_iso(
                attempted_at + timedelta(seconds=backoff_seconds)
            )
        conn.execute(
            """UPDATE voice_memo_ingest
               SET status = CASE WHEN ? THEN 'failed_terminal' ELSE 'failed' END,
                   error_message = ?,
                   attempt_count = ?,
                   last_attempt_at = ?,
                   next_attempt_at = ?,
                   retryable = ?,
                   terminal_at = CASE WHEN ? THEN ? ELSE NULL END,
                   updated_at = datetime('now')
               WHERE recording_pk = ?""",
            (
                terminal,
                _voice_memo_error_code(error_code),
                attempt_count,
                _voice_memo_iso(attempted_at),
                next_attempt_at,
                int(not terminal),
                terminal,
                _voice_memo_iso(attempted_at) if terminal else None,
                recording_pk,
            ),
        )
        conn.commit()
    except Exception as e:
        log.error("Failed to schedule voice memo retry pk=%s: %s", recording_pk, e)
    finally:
        if conn:
            conn.close()


def mark_voice_memo_terminal(recording_pk: int, error_code: str) -> bool:
    """Record a linked non-retryable source outcome without retaining unsafe detail."""
    conn = None
    try:
        conn = _get_conn()
        status = (
            error_code
            if error_code in {"routed", "needs_review", "skipped_too_large"}
            else "failed_terminal"
        )
        cursor = conn.execute(
            """UPDATE voice_memo_ingest
               SET status = ?, error_message = ?, retryable = 0,
                   next_attempt_at = NULL, terminal_at = datetime('now'),
                   updated_at = datetime('now')
               WHERE recording_pk = ?""",
            (status, _voice_memo_error_code(error_code), recording_pk),
        )
        conn.commit()
        return cursor.rowcount == 1
    except Exception as e:
        log.error("Failed to mark voice memo terminal pk=%s: %s", recording_pk, e)
        return False
    finally:
        if conn:
            conn.close()


def mark_voice_memo_failed(recording_pk: int, error_message: str) -> None:
    """Compatibility alias for legacy callers; errors are reduced to safe codes."""
    mark_voice_memo_retryable(recording_pk, error_message)


def get_voice_memo_recordings_for_retry(
    *, now: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    conn = None
    try:
        conn = _get_conn()
        due_at = _voice_memo_iso(_voice_memo_now(now))
        rows = conn.execute(
            """SELECT * FROM voice_memo_ingest
               WHERE retryable = 1
                 AND transcript_row_id IS NULL
                 AND attempt_count < ?
                 AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
               ORDER BY next_attempt_at IS NOT NULL, next_attempt_at ASC, recording_pk ASC
               LIMIT ?""",
            (VOICE_MEMO_MAX_ATTEMPTS, due_at, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        log.error("Failed to fetch retryable voice memos: %s", e)
        return []
    finally:
        if conn:
            conn.close()


def get_source_watermark(source: str) -> int:
    conn = None
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT last_discovered_id FROM source_watermarks WHERE source = ?",
            (source,),
        ).fetchone()
        return int(row[0]) if row else 0
    except Exception as e:
        log.error("Failed to get source watermark source=%s: %s", source, e)
        return 0
    finally:
        if conn:
            conn.close()


def advance_source_watermark(source: str, discovered_id: int) -> bool:
    conn = None
    try:
        conn = _get_conn()
        cursor = conn.execute(
            """INSERT INTO source_watermarks(source, last_discovered_id, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(source) DO UPDATE SET
                   last_discovered_id = excluded.last_discovered_id,
                   updated_at = datetime('now')
               WHERE excluded.last_discovered_id > source_watermarks.last_discovered_id""",
            (source, discovered_id),
        )
        conn.commit()
        return cursor.rowcount == 1
    except Exception as e:
        log.error("Failed to advance source watermark source=%s: %s", source, e)
        return False
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
        "query_ok": 1,
        "health_error": 0,
        "latest_recording_pk": 0,
        "awaiting_file_count": 0,
        "failed_count": 0,
        "oldest_waiting_discovered_at": None,
        "retry_due_count": 0,
        "terminal_count": 0,
        "terminal_failure_count": 0,
        "max_attempt_count": 0,
        "source_watermark": 0,
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
            "SELECT COUNT(*) FROM voice_memo_ingest WHERE status IN ('failed', 'failed_terminal')"
        ).fetchone()
        health["failed_count"] = int(failed[0] or 0)

        retry_due_at = _voice_memo_iso(_voice_memo_now(None))
        retry_due = conn.execute(
            """SELECT COUNT(*) FROM voice_memo_ingest
               WHERE retryable = 1
                 AND transcript_row_id IS NULL
                 AND attempt_count < ?
                 AND (next_attempt_at IS NULL OR next_attempt_at <= ?)""",
            (VOICE_MEMO_MAX_ATTEMPTS, retry_due_at),
        ).fetchone()
        health["retry_due_count"] = int(retry_due[0] or 0)

        terminal = conn.execute(
            "SELECT COUNT(*) FROM voice_memo_ingest WHERE terminal_at IS NOT NULL"
        ).fetchone()
        health["terminal_count"] = int(terminal[0] or 0)
        terminal_failures = conn.execute(
            "SELECT COUNT(*) FROM voice_memo_ingest WHERE status = 'failed_terminal'"
        ).fetchone()
        health["terminal_failure_count"] = int(terminal_failures[0] or 0)
        max_attempts = conn.execute(
            "SELECT COUNT(*) FROM voice_memo_ingest WHERE attempt_count >= ?",
            (VOICE_MEMO_MAX_ATTEMPTS,),
        ).fetchone()
        health["max_attempt_count"] = int(max_attempts[0] or 0)
        watermark = conn.execute(
            "SELECT last_discovered_id FROM source_watermarks WHERE source = 'voice_memos'"
        ).fetchone()
        health["source_watermark"] = int(watermark[0] or 0) if watermark else 0
        return health
    except Exception as e:
        log.error(
            "Failed to fetch voice memo health: %s",
            _safe_exception_class(e),
        )
        health["query_ok"] = 0
        health["health_error"] = 1
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
                        content_hash, source, transcript, status, quality_status,
                        quality_detail, transcript_sha256,
                        maya_delivery_status, maya_delivery_eligible
                    ) VALUES (
                        ?, ?, ?, 'routed', 'pending', 'migrated_placeholder',
                        ?, 'ineligible', 0
                    )
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
