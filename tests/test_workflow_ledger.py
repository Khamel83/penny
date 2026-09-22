from __future__ import annotations

import sqlite3

import pytest

from workflow_ledger import (
    MAX_REVIEW_FIX_ROUNDS,
    BaselineMismatchError,
    InvalidMetadata,
    PlanAlreadyExists,
    InvalidStageTransition,
    RetryLimitExceeded,
    WorkflowLedger,
)


@pytest.fixture
def ledger_path(tmp_path):
    return tmp_path / "workflow.db"


def test_state_survives_reopen_and_resume_without_duplicate_steps(ledger_path):
    ledger = WorkflowLedger(ledger_path)
    plan = ledger.create_plan(
        plan_id="plan-resume",
        repository_baseline="penny@abc123",
        stages=("design", "implementation"),
    )
    assert plan.transition_stage("design", "completed") is True
    assert plan.complete_step("schema") is True
    assert plan.complete_step("schema") is False
    ledger.close()

    resumed = WorkflowLedger(ledger_path).resume_plan(
        "plan-resume", "penny@abc123"
    )
    assert resumed.snapshot()["stages"]["design"] == "completed"
    assert resumed.snapshot()["completed_steps"] == ["schema"]
    assert resumed.complete_step("tests") is True
    assert resumed.snapshot()["completed_steps"] == ["schema", "tests"]

    with pytest.raises(InvalidStageTransition):
        resumed.transition_stage("design", "in_progress")


def test_plan_ids_are_explicitly_unique_and_empty_ids_are_rejected(ledger_path):
    ledger = WorkflowLedger(ledger_path)
    with pytest.raises(InvalidMetadata):
        ledger.create_plan(plan_id="", repository_baseline="penny@empty")

    ledger.create_plan(plan_id="plan-unique", repository_baseline="penny@unique")
    with pytest.raises(PlanAlreadyExists):
        ledger.create_plan(
            plan_id="plan-unique", repository_baseline="penny@unique"
        )

def test_stale_or_cross_plan_state_is_rejected(ledger_path):
    ledger = WorkflowLedger(ledger_path)
    first = ledger.create_plan(
        plan_id="plan-one", repository_baseline="penny@one"
    )
    ledger.create_plan(plan_id="plan-two", repository_baseline="penny@two")

    with pytest.raises(BaselineMismatchError):
        ledger.resume_plan(first.plan_id, "penny@two")
    with pytest.raises(BaselineMismatchError):
        first.complete_step("wrong-baseline", repository_baseline="penny@two")
    with pytest.raises(BaselineMismatchError):
        ledger.resume_plan("plan-two", "penny@one")


def test_review_fix_rounds_are_durable_and_bounded(ledger_path):
    ledger = WorkflowLedger(ledger_path)
    plan = ledger.create_plan(
        plan_id="plan-retries", repository_baseline="penny@retries"
    )

    for expected_round in range(1, MAX_REVIEW_FIX_ROUNDS + 1):
        round_number = plan.start_review_round()
        assert round_number == expected_round
        plan.record_review_finding(
            round_number,
            finding_id=f"finding-{expected_round}",
            severity="important",
            code="missing-check",
            path="workflow_ledger.py",
            line=expected_round,
        )
        plan.finish_review_round(round_number, "fix_required")

    with pytest.raises(RetryLimitExceeded, match="fresh plan"):
        plan.start_review_round()

    ledger.close()
    resumed = WorkflowLedger(ledger_path).resume_plan(
        "plan-retries", "penny@retries"
    )
    snapshot = resumed.snapshot()
    assert [item["round"] for item in snapshot["review_rounds"]] == list(
        range(1, MAX_REVIEW_FIX_ROUNDS + 1)
    )
    assert snapshot["review_rounds"][-1]["status"] == "fix_required"


def test_interrupted_review_round_resumes_without_creating_another_round(ledger_path):
    ledger = WorkflowLedger(ledger_path)
    plan = ledger.create_plan(
        plan_id="plan-review-resume", repository_baseline="penny@review-resume"
    )
    assert plan.start_review_round() == 1
    ledger.close()

    resumed = WorkflowLedger(ledger_path).resume_plan(
        "plan-review-resume", "penny@review-resume"
    )
    assert resumed.start_review_round() == 1
    assert resumed.finish_review_round(1, "passed") is True
    assert [item["round"] for item in resumed.snapshot()["review_rounds"]] == [1]


def test_explicit_falsy_baseline_override_cannot_bypass_binding(ledger_path):
    ledger = WorkflowLedger(ledger_path)
    plan = ledger.create_plan(
        plan_id="plan-bound", repository_baseline="penny@bound"
    )

    with pytest.raises(InvalidMetadata):
        plan.snapshot(repository_baseline="")


def test_sensitive_metadata_is_rejected_but_safe_paths_remain_recordable(ledger_path):
    ledger = WorkflowLedger(ledger_path)
    plan = ledger.create_plan(
        plan_id="plan-safe-metadata", repository_baseline="penny@safe-metadata"
    )

    with pytest.raises(InvalidMetadata):
        plan.complete_step("captured-transcript-text")
    with pytest.raises(InvalidMetadata):
        plan.record_verification(["pytest", "--token=secret"], exit_code=0)
    with pytest.raises(InvalidMetadata):
        plan.record_review_finding(
            1,
            finding_id="finding-sensitive",
            severity="important",
            code="unsafe-boundary",
            path="provider-response.json",
        )

    plan.record_verification(
        ["python3", "-m", "pytest", "tests/test_transcript_log.py"], exit_code=0
    )
    assert plan.snapshot()["verifications"][0]["command"][-1] == (
        "tests/test_transcript_log.py"
    )


def test_ledger_persists_only_bounded_metadata(ledger_path):
    ledger = WorkflowLedger(ledger_path)
    plan = ledger.create_plan(
        plan_id="plan-metadata", repository_baseline="penny@metadata"
    )
    round_number = plan.start_review_round()
    plan.record_review_finding(
        round_number,
        finding_id="finding-safe",
        severity="critical",
        code="unsafe-boundary",
        path="workflow_ledger.py",
        line=10,
    )
    plan.record_verification(["python", "-m", "pytest", "-q"], exit_code=0)

    connection = sqlite3.connect(ledger_path)
    try:
        stored = " ".join(
            str(value)
            for row in connection.execute(
                "SELECT * FROM plans UNION ALL SELECT * FROM stages"
            ).fetchall()
            for value in row
        )
    finally:
        connection.close()

    assert "audio" not in stored.lower()
    assert "transcript" not in stored.lower()
    assert "provider response" not in stored.lower()
    assert "credential" not in stored.lower()
    assert "token" not in stored.lower()
    assert "routing" not in stored.lower()
    assert plan.snapshot()["verifications"][0]["command"] == [
        "python",
        "-m",
        "pytest",
        "-q",
    ]
