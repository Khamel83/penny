from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

import transcript_log


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transcript_log, "TRANSCRIPT_DB_PATH", tmp_path / "penny.db")
    monkeypatch.setattr(
        transcript_log,
        "LEGACY_VOICE_MEMO_CURSOR_PATH",
        tmp_path / "last_pk.txt",
    )
    monkeypatch.setattr(transcript_log, "_MIGRATION_SOURCES", [])
    transcript_log.init_db()


def _review_row(*, linked: bool = True) -> tuple[int, int | None]:
    if linked:
        assert transcript_log.upsert_voice_memo_recording(
            408,
            label="recheck",
            raw_path="408.m4a",
            duration_seconds=8.0,
            recorded_at="2026-08-11T06:00:00Z",
        )
    row_id = transcript_log.insert_transcript(
        content_hash="review-quality-hash",
        source="iCloud",
        transcript="No no no, put this in the other folder.",
        audio_path="/tmp/staged-408.m4a",
        duration_seconds=8.0,
        ingest_state="needs_review",
        quality_status="needs_review",
        quality_detail="attempt_1=consecutive_token_repetition",
        recorded_at="2026-08-11T06:00:00Z",
        enqueue_slack=False,
    )
    assert row_id is not None
    if linked:
        assert transcript_log.link_voice_memo_transcript(
            408,
            transcript_row_id=int(row_id),
            content_hash="review-quality-hash",
            audio_path="/tmp/staged-408.m4a",
            terminal_state="needs_review",
        )
    return int(row_id), 408 if linked else None


def test_quality_recheck_promotes_atomically_and_preserves_receipt(isolated_db) -> None:
    row_id, recording_pk = _review_row()

    result = transcript_log.re_evaluate_quality_review(row_id)

    assert result.status == "promoted"
    assert result.reason is None
    assert result.slack_queued is True
    assert result.maya_queued is True
    row = transcript_log.get_transcript(row_id)
    assert row["status"] == "pending"
    assert row["ingest_state"] == "transcribed"
    assert row["quality_status"] == "passed"
    assert row["quality_detail"] == "attempt_1=consecutive_token_repetition"
    assert row["maya_delivery_eligible"] == 1
    assert row["maya_delivery_status"] == "pending"
    assert len(transcript_log.get_pending_slack_deliveries(transcript_id=row_id)) == 1

    conn = transcript_log._get_conn()
    try:
        source = conn.execute(
            "SELECT status, error_message, terminal_at, retryable, content_hash "
            "FROM voice_memo_ingest WHERE recording_pk = ?",
            (recording_pk,),
        ).fetchone()
        receipt = conn.execute(
            "SELECT status, message_text FROM quality_failure_slack_deliveries "
            "WHERE transcript_row_id = ?",
            (row_id,),
        ).fetchone()
    finally:
        conn.close()
    assert source["status"] == "transcribed"
    assert source["error_message"] is None
    assert source["terminal_at"] is None
    assert source["retryable"] == 0
    assert source["content_hash"] == "review-quality-hash"
    assert receipt["status"] == "resolved"
    assert "No no no" not in receipt["message_text"]


def test_quality_recheck_is_idempotent_and_does_not_duplicate_outboxes(isolated_db) -> None:
    row_id, _ = _review_row()

    first = transcript_log.re_evaluate_quality_review(row_id)
    second = transcript_log.re_evaluate_quality_review(row_id)

    assert first.status == "promoted"
    assert second.status == "already_promoted"
    assert second.slack_queued is False
    assert second.maya_queued is False
    assert len(transcript_log.get_pending_slack_deliveries(transcript_id=row_id)) == 1
    conn = transcript_log._get_conn()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM quality_failure_slack_deliveries "
            "WHERE transcript_row_id = ?",
            (row_id,),
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_quality_recheck_rejects_under_current_policy_without_mutation(isolated_db) -> None:
    row_id, _ = _review_row(linked=False)
    conn = transcript_log._get_conn()
    try:
        conn.execute(
            "UPDATE transcripts SET transcript = ?, transcript_sha256 = ? WHERE id = ?",
            (
                "No no no no, put this in the other folder.",
                "bad-hash-is-intentionally-repaired-by-fixture",
                row_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    result = transcript_log.re_evaluate_quality_review(row_id)

    assert result.status == "rejected"
    assert result.reason == "consecutive_token_repetition"
    row = transcript_log.get_transcript(row_id)
    assert row["quality_status"] == "needs_review"
    assert row["ingest_state"] == "needs_review"
    assert transcript_log.get_pending_slack_deliveries(transcript_id=row_id) == []


def test_quality_recheck_conflict_does_not_overwrite_routed_source(isolated_db) -> None:
    row_id, recording_pk = _review_row()
    conn = transcript_log._get_conn()
    try:
        conn.execute(
            "UPDATE voice_memo_ingest SET status = 'routed', routed_at = datetime('now') "
            "WHERE recording_pk = ?",
            (recording_pk,),
        )
        conn.commit()
    finally:
        conn.close()

    result = transcript_log.re_evaluate_quality_review(row_id)

    assert result.status == "conflict"
    assert transcript_log.get_transcript(row_id)["quality_status"] == "needs_review"
    assert transcript_log.get_pending_slack_deliveries(transcript_id=row_id) == []


def test_quality_recheck_rolls_back_every_write_on_outbox_failure(isolated_db) -> None:
    row_id, recording_pk = _review_row()

    with patch.object(
        transcript_log,
        "_queue_slack_delivery",
        side_effect=sqlite3.OperationalError("test write failure"),
    ):
        result = transcript_log.re_evaluate_quality_review(row_id)

    assert result.status == "failed"
    assert transcript_log.get_transcript(row_id)["quality_status"] == "needs_review"
    assert transcript_log.get_transcript(row_id)["ingest_state"] == "needs_review"
    assert transcript_log.get_pending_slack_deliveries(transcript_id=row_id) == []
    conn = transcript_log._get_conn()
    try:
        source = conn.execute(
            "SELECT status, error_message, terminal_at FROM voice_memo_ingest "
            "WHERE recording_pk = ?",
            (recording_pk,),
        ).fetchone()
        receipt = conn.execute(
            "SELECT status FROM quality_failure_slack_deliveries "
            "WHERE transcript_row_id = ?",
            (row_id,),
        ).fetchone()
    finally:
        conn.close()
    assert source["status"] == "needs_review"
    assert source["error_message"] == "needs_review"
    assert source["terminal_at"] is not None
    assert receipt["status"] == "pending"
