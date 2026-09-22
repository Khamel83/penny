#!/usr/bin/env python3
"""Index and transcribe historical Voice Memos without downstream delivery."""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import transcript_log  # noqa: E402
import watcher  # noqa: E402

DEFAULT_LIMIT = 50


def compact_ranges(values: Iterable[int]) -> list[str]:
    """Render sorted integer IDs as compact, metadata-only ranges."""
    ordered = sorted({int(value) for value in values})
    if not ordered:
        return []

    ranges: list[str] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = value
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ranges


def _state_counts() -> dict[str, int]:
    conn = None
    try:
        conn = transcript_log._get_conn()
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM voice_memo_ingest
            GROUP BY status
            ORDER BY status
            """
        ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}
    finally:
        if conn:
            conn.close()


def _downstream_effect_count() -> int:
    """Count existing downstream rows without reading bodies or payloads."""
    conn = None
    count = 0
    try:
        conn = transcript_log._get_conn()
        for table in (
            "slack_deliveries",
            "quality_failure_slack_deliveries",
            "apple_effects",
            "github_deliveries",
        ):
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            if exists is not None:
                count += int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return count
    finally:
        if conn:
            conn.close()


def _retryable_source_pks(source_pks: set[int]) -> set[int]:
    retryable = transcript_log.get_voice_memo_recordings_for_retry(
        limit=max(1, len(source_pks) + 1)
    )
    return {
        int(row["recording_pk"])
        for row in retryable
        if int(row["recording_pk"]) in source_pks
    }


def _metadata_upsert(recording: dict[str, Any]) -> bool:
    recorded_at, timestamp_invalid = watcher._recording_timestamp_or_invalid(recording)
    duration_seconds, duration_invalid = watcher._recording_duration_or_invalid(recording)
    if timestamp_invalid or duration_invalid:
        return watcher._upsert_recording_metadata(
            recording,
            recorded_at=None if timestamp_invalid else recorded_at,
            duration_seconds=None if duration_invalid else duration_seconds,
        )
    return watcher._upsert_recording_metadata(
        recording,
        recorded_at=recorded_at,
        duration_seconds=duration_seconds,
    )


def _placeholder_source_pks() -> set[int]:
    with closing(transcript_log._get_conn()) as conn:
        return {int(row[0]) for row in conn.execute(
            """SELECT v.recording_pk FROM voice_memo_ingest v
               JOIN transcripts t ON t.id = v.transcript_row_id
               WHERE t.transcript = ?""",
            ('(migrated — original transcript not preserved)',),
        )}


def run_backfill(
    limit: int | None = DEFAULT_LIMIT,
    dry_run: bool = False,
    progress: bool = False,
) -> dict[str, Any]:
    """Run one bounded local-only historical pass and return metadata counts."""
    if limit is not None and limit < 0:
        raise ValueError("limit_must_be_nonnegative")

    if not dry_run:
        transcript_log.init_db()

    source_rows = watcher.get_all_recordings()
    source_pks = {int(row["Z_PK"]) for row in source_rows}
    ledger_pks = transcript_log.get_voice_memo_recording_pks()
    initial_unindexed = source_pks - ledger_pks
    retryable_pks = _retryable_source_pks(source_pks)
    placeholder_pks = _placeholder_source_pks()
    candidates = [
        row
        for row in source_rows
        if int(row["Z_PK"]) in initial_unindexed
        or int(row["Z_PK"]) in retryable_pks
        or int(row["Z_PK"]) in placeholder_pks
    ]
    if limit is not None:
        candidates = candidates[:limit]

    attempted_count = 0
    processed_count = 0
    failed_count = 0
    if not dry_run:
        for recording in candidates:
            attempted_count += 1
            if not _metadata_upsert(recording):
                failed_count += 1
                continue
            if watcher.process_recording(
                recording,
                already_upserted=True,
                local_only=True,
            ):
                processed_count += 1
            else:
                failed_count += 1
            if progress:
                print(json.dumps({'recording_pk': int(recording['Z_PK']),
                                  'attempted_count': attempted_count,
                                  'processed_count': processed_count,
                                  'failed_count': failed_count}), flush=True)

    coverage = transcript_log.get_voice_memo_coverage()
    final_ledger_pks = transcript_log.get_voice_memo_recording_pks()
    archive_counts = transcript_log.get_archive_delivery_health()
    report: dict[str, Any] = {
        "source_records": len(source_rows),
        "ledger_records": coverage["ledger_count"],
        "linked_count": coverage["linked_count"],
        "unlinked_count": coverage["unlinked_count"],
        "retryable_count": coverage["retryable_count"],
        "terminal_count": coverage["terminal_count"],
        "local_only_count": coverage["local_only_count"],
        "initial_unindexed_ranges": compact_ranges(initial_unindexed),
        "unindexed_ranges": compact_ranges(source_pks - final_ledger_pks),
        "selected_count": len(candidates),
        "attempted_count": attempted_count,
        "processed_count": processed_count,
        "failed_count": failed_count,
        "status_counts": _state_counts(),
        "archive_counts": archive_counts,
        "downstream_effect_count": _downstream_effect_count(),
        "dry_run": dry_run,
        "placeholder_source_count": len(_placeholder_source_pks() & source_pks),
    }
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="maximum records to attempt; 0 processes all candidates",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report source/ledger coverage without changing the ledger",
    )
    parser.add_argument('--progress', action='store_true', help='emit metadata after each record')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.limit < 0:
        print(json.dumps({"error_code": "limit_must_be_nonnegative"}, sort_keys=True))
        return 2

    limit = None if args.limit == 0 else args.limit
    logging.disable(logging.CRITICAL)
    try:
        report = run_backfill(limit=limit, dry_run=args.dry_run, progress=args.progress)
    except (OSError, sqlite3.Error, RuntimeError, ValueError):
        print(json.dumps({"error_code": "backfill_failed"}, sort_keys=True))
        return 1
    finally:
        logging.disable(logging.NOTSET)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
