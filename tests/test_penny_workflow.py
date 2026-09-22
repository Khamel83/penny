from __future__ import annotations

import json
from pathlib import Path

from scripts import penny_workflow


PLAN_ID = "penny-20260919-example"


def _write_plan(
    tmp_path: Path,
    *,
    statuses: dict[str, str],
    executable_tasks: bool = True,
    include_task: bool = False,
) -> Path:
    plan_dir = tmp_path / ".penny" / "workflow" / "plans" / PLAN_ID
    plan_dir.mkdir(parents=True)
    artifacts = {
        "requirements.md": f"Plan ID: {PLAN_ID}\nStatus: {statuses.get('requirements.md', 'approved')}\n",
        "design-review.md": f"Plan ID: {PLAN_ID}\nStatus: {statuses.get('design-review.md', 'approved')}\n",
        "implementation-plan.md": (
            f"Plan ID: {PLAN_ID}\nStatus: {statuses.get('implementation-plan.md', 'executable')}\n"
            "| Task ID | Files allowed | Behavior to change | Check | Handoff |\n"
            "| --- | --- | --- | --- | --- |\n"
            + (
                "| task-1 | scripts/example.py | observable result | pytest -q | tdd.md |\n"
                if executable_tasks
                else "| <TASK_ID> | <PATH_1> | <OBSERVABLE_BEHAVIOR> | <TEST> | <HANDOFF> |\n"
            )
        ),
        "tdd.md": (
            f"Plan ID: {PLAN_ID}\nStatus: {statuses.get('tdd.md', 'complete')}\n"
            "Check: pytest -q tests/test_example.py\n"
            "Expected observable behavior: receipt is persisted\n"
            "Observed failure: assertion failed before fix\n"
            "RED evidence: red-ref\n"
            "Check: pytest -q tests/test_example.py\n"
            "Observed pass: 1 passed\n"
            "GREEN evidence: green-ref\n"
            "Exception approved: no\n"
        ),
        "code-review.md": (
            f"Plan ID: {PLAN_ID}\nStatus: {statuses.get('code-review.md', 'approved')}\n"
            "Requirements: requirements.md\nDesign: design-review.md\n"
            "Implementation plan: implementation-plan.md\n"
            "Base revision: abc123\nHead revision: def456\n"
            "Changed paths: scripts/example.py\n"
            "Review evidence: review-ref\n"
            "Spec-compliance command: pytest -q\nSpec-compliance result: 2 passed\n"
            "Behavioral evidence: green-ref\nPrivacy/scope inspection: metadata-only\n"
            "Runtime behavior unchanged outside plan: confirmed\n"
        ),
        "verification.md": (
            f"Plan ID: {PLAN_ID}\nStatus: {statuses.get('verification.md', 'verified')}\n"
            "Requirements: requirements.md\nApproved design: design-review.md\n"
            "Executable plan: implementation-plan.md\nApproved review: code-review.md\n"
            "Head revision: def456\nEvidence command: pytest -q\nEvidence result: 8 passed\n"
            "Decision: verified\nUnresolved risk: none\nHandoff: parent issue\n"
            "| Boundary | Check | Observable result | Evidence reference |\n"
            "| --- | --- | --- | --- |\n"
            "| Requirements | review | approved | req-ref |\n"
            "| Behavioral | pytest -q | 2 passed | behavior-ref |\n"
            "| Repository | trust check | passed | repo-ref |\n"
            "| Local receipt/archive | metadata check | not_applicable | local-ref |\n"
            "| Runtime state | read-only check | unproven | runtime-ref |\n"
            "| Provider state | read-only check | unproven | provider-ref |\n"
            "| Downstream delivery | read-only check | unproven | downstream-ref |\n"
        ),
    }
    for filename, content in artifacts.items():
        if filename in statuses or filename in {
            "requirements.md",
            "design-review.md",
            "implementation-plan.md",
            "tdd.md",
            "code-review.md",
            "verification.md",
        }:
            plan_dir.joinpath(filename).write_text(content, encoding="utf-8")
    if include_task:
        task_dir = plan_dir / "tasks"
        task_dir.mkdir()
        task_dir.joinpath("task-1.md").write_text(
            f"Plan ID: {PLAN_ID}\nStatus: complete\nTask ID: task-1\n"
            "Allowed files: scripts/example.py\n"
            "Allowed symbols/behavior: receipt status\n"
            "Required behavioral check: pytest -q\n"
            "Out of scope: provider delivery\nNo subdelegation: yes\n"
            "Changed paths: scripts/example.py\nBehavioral evidence: green-ref\n"
            "Remaining risks: none\nNext artifact/stage: code-review.md\n"
            "The worker must not access raw audio, transcript text, credentials, or tokens. It has no permission to send external effects.\n",
            encoding="utf-8",
        )
    return plan_dir


def test_high_risk_gate_requires_approved_requirements_design_and_executable_plan(tmp_path, monkeypatch):
    plan_dir = _write_plan(tmp_path, statuses={"design-review.md": "draft"})
    monkeypatch.chdir(tmp_path)

    ok, reasons = penny_workflow.gate(plan_dir, "high")

    assert not ok
    assert reasons == ["status_not_approved:design-review.md"]


def test_high_risk_gate_rejects_placeholder_executable_tasks(tmp_path, monkeypatch):
    plan_dir = _write_plan(tmp_path, statuses={}, executable_tasks=False)
    monkeypatch.chdir(tmp_path)

    ok, reasons = penny_workflow.gate(plan_dir, "high")

    assert not ok
    assert reasons == ["placeholder_or_incomplete_task_row:implementation-plan.md"]


def test_verify_accepts_complete_plan_scoped_evidence(tmp_path, monkeypatch, capsys):
    plan_dir = _write_plan(tmp_path, statuses={}, include_task=True)
    monkeypatch.chdir(tmp_path)

    assert penny_workflow.main(["verify", "--plan-dir", str(plan_dir)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["plan_id"] == PLAN_ID


def test_verify_requires_matching_red_green_behavioral_check(tmp_path, monkeypatch):
    plan_dir = _write_plan(tmp_path, statuses={})
    tdd = plan_dir / "tdd.md"
    tdd.write_text(tdd.read_text(encoding="utf-8").replace(
        "Check: pytest -q tests/test_example.py\nObserved pass",
        "Check: pytest -q tests/test_other.py\nObserved pass",
    ), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    ok, reasons = penny_workflow.verify(plan_dir)

    assert not ok
    assert "red_green_check_mismatch" in reasons


def test_verify_requires_approved_smoke_exception(tmp_path, monkeypatch):
    plan_dir = _write_plan(tmp_path, statuses={})
    tdd = plan_dir / "tdd.md"
    tdd.write_text(
        f"Plan ID: {PLAN_ID}\nStatus: complete\nException approved: yes\n"
        "Reason: operator boundary\nScenario: run bounded smoke\n"
        "Observed result: ready\nSmoke evidence: smoke-ref\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    ok, reasons = penny_workflow.verify(plan_dir)

    assert not ok
    assert "incomplete_smoke_test_exception" in reasons


def test_verify_requires_complete_bounded_subagent_task(tmp_path, monkeypatch):
    plan_dir = _write_plan(tmp_path, statuses={}, include_task=True)
    task = plan_dir / "tasks" / "task-1.md"
    task.write_text(f"Plan ID: {PLAN_ID}\nStatus: complete\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    ok, reasons = penny_workflow.verify(plan_dir)

    assert not ok
    assert "missing_task_allowed_files:task-1.md" in reasons


def test_verify_requires_each_evidence_boundary(tmp_path, monkeypatch):
    plan_dir = _write_plan(tmp_path, statuses={})
    verification = plan_dir / "verification.md"
    text = verification.read_text(encoding="utf-8")
    verification.write_text(
        text.replace("| Provider state | read-only check | unproven | provider-ref |\n", ""),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    ok, reasons = penny_workflow.verify(plan_dir)

    assert not ok
    assert "missing_evidence_boundary:Provider state" in reasons
