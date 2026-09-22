#!/usr/bin/env python3
"""Validate Penny's plan-scoped development workflow state.

This command is deliberately metadata-only. It reads workflow artifacts under
.penny/workflow/plans and reports identifiers, statuses, and reason codes; it
never reads or prints Penny capture, transcript, provider, or credential data.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PLAN_ID_RE = re.compile(r"^penny-[a-z0-9][a-z0-9-]*$")
PLACEHOLDER_RE = re.compile(r"<[^>]+>|\[\[[^]]+\]\]")
GENERIC_EVIDENCE_RE = re.compile(
    r"^(?:files changed|changed files|diff exists|updated files?)$", re.IGNORECASE
)

STAGES = {
    "requirements": ("requirements.md", "approved"),
    "design": ("design-review.md", "approved"),
    "plan": ("implementation-plan.md", "executable"),
}


def _fields(text: str, label: str) -> list[str]:
    values: list[str] = []
    for line in text.splitlines()[:120]:
        normalized = line.lstrip("- *").strip()
        key, separator, value = normalized.partition(":")
        if separator and key.strip() == label:
            values.append(value.strip())
    return values


def _field(text: str, label: str) -> str:
    values = _fields(text, label)
    return values[0] if values else ""


def _concrete(value: str) -> bool:
    return bool(value) and not PLACEHOLDER_RE.search(value) and not GENERIC_EVIDENCE_RE.fullmatch(
        value
    )


def _metadata(path: Path, plan_id: str) -> tuple[dict[str, str], list[str]]:
    """Read only bounded metadata headers and required evidence markers."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}, [f"unreadable:{path.name}"]
    keys = {
        "Plan ID",
        "Status",
        "Requirements",
        "Design",
        "Approved design",
        "Implementation plan",
        "Executable plan",
        "Approved review",
        "Head revision",
        "Evidence command",
        "Evidence result",
        "Base revision",
        "Changed paths",
        "Review evidence",
        "Spec-compliance command",
        "Spec-compliance result",
        "Behavioral evidence",
        "Privacy/scope inspection",
        "Runtime behavior unchanged outside plan",
        "Decision",
        "Unresolved risk",
        "Handoff",
    }
    metadata = {key: _field(text, key) for key in keys}
    reasons: list[str] = []
    if metadata.get("Plan ID") != plan_id:
        reasons.append(f"plan_id_mismatch:{path.name}")
    if PLACEHOLDER_RE.search(metadata.get("Plan ID", "")):
        reasons.append(f"placeholder_plan_id:{path.name}")
    return metadata, reasons


def _plan_dir(value: str) -> tuple[Path | None, str | None]:
    root = Path.cwd() / ".penny" / "workflow" / "plans"
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return None, "plan_dir_outside_workflow_root"
    if not PLAN_ID_RE.fullmatch(resolved.name):
        return None, "invalid_plan_id"
    return resolved, None


def _stage_check(plan_dir: Path, filename: str, expected_status: str) -> list[str]:
    path = plan_dir / filename
    if not path.is_file():
        return [f"missing:{filename}"]
    metadata, reasons = _metadata(path, plan_dir.name)
    if metadata.get("Status") != expected_status:
        reasons.append(f"status_not_{expected_status}:{filename}")
    return reasons


def gate(plan_dir: Path, risk: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if risk in {"high", "critical"}:
        for filename, expected_status in STAGES.values():
            reasons.extend(_stage_check(plan_dir, filename, expected_status))
        if not reasons:
            reasons.extend(_validate_plan(plan_dir))
    else:
        requirements = plan_dir / "requirements.md"
        if requirements.is_file():
            reasons.extend(_metadata(requirements, plan_dir.name)[1])
    return not reasons, reasons


def _validate_plan(plan_dir: Path) -> list[str]:
    path = plan_dir / "implementation-plan.md"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return [f"unreadable:{path.name}"]

    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.lower().startswith("| task id"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells and not any(set(cell) - {"-"} for cell in cells):
            continue
        rows.append(cells)
    if not rows:
        return ["missing_executable_tasks:implementation-plan.md"]
    if any(len(row) != 5 or any(not _concrete(cell) for cell in row) for row in rows):
        return ["placeholder_or_incomplete_task_row:implementation-plan.md"]
    return []


def _validate_tdd(plan_dir: Path) -> list[str]:
    path = plan_dir / "tdd.md"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return [f"unreadable:{path.name}"]

    exception = _field(text, "Exception approved")
    if exception == "yes":
        required = ("Reason", "Scenario", "Observed result", "Smoke evidence", "Approver")
        return [
            "incomplete_smoke_test_exception"
            for label in required
            if not _concrete(_field(text, label))
        ]
    if exception not in {"", "no"}:
        return ["invalid_smoke_test_exception"]

    required = (
        "Expected observable behavior",
        "Observed failure",
        "RED evidence",
        "Observed pass",
        "GREEN evidence",
    )
    reasons = [
        f"missing_red_green_{label.lower().replace(' ', '_')}"
        for label in required
        if not _concrete(_field(text, label))
    ]
    checks = _fields(text, "Check")
    if len(checks) < 2 or not all(_concrete(value) for value in checks[:2]):
        reasons.append("missing_red_green_check")
    elif checks[0] != checks[1]:
        reasons.append("red_green_check_mismatch")
    red = _field(text, "RED evidence")
    green = _field(text, "GREEN evidence")
    if _concrete(red) and red == green:
        reasons.append("red_green_evidence_not_distinct")
    return reasons
def _validate_review(plan_dir: Path) -> list[str]:
    path = plan_dir / "code-review.md"
    if not path.is_file():
        return []
    metadata, reasons = _metadata(path, plan_dir.name)
    required = (
        "Requirements",
        "Design",
        "Implementation plan",
        "Base revision",
        "Head revision",
        "Changed paths",
        "Review evidence",
        "Spec-compliance command",
        "Spec-compliance result",
        "Behavioral evidence",
        "Privacy/scope inspection",
        "Runtime behavior unchanged outside plan",
    )
    for key in required:
        if not _concrete(metadata.get(key, "")):
            reasons.append(f"missing_observed_review_{key.lower().replace(' ', '_').replace('/', '_')}")
    if metadata.get("Base revision") == metadata.get("Head revision") and _concrete(
        metadata.get("Base revision", "")
    ):
        reasons.append("review_base_and_head_revisions_identical")
    return reasons


def _evidence_matrix_reasons(text: str) -> list[str]:
    boundaries = (
        "Requirements",
        "Behavioral",
        "Repository",
        "Local receipt/archive",
        "Runtime state",
        "Provider state",
        "Downstream delivery",
    )
    reasons: list[str] = []
    for boundary in boundaries:
        rows = [
            line.strip()
            for line in text.splitlines()
            if line.strip().startswith(f"| {boundary} |")
        ]
        if not rows:
            reasons.append(f"missing_evidence_boundary:{boundary}")
            continue
        cells = [cell.strip() for cell in rows[0].strip("|").split("|")]
        if len(cells) != 4 or any(not _concrete(cell) for cell in cells[1:]):
            reasons.append(f"incomplete_evidence_boundary:{boundary}")
    return reasons


def _validate_verification(plan_dir: Path) -> list[str]:
    path = plan_dir / "verification.md"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return [f"unreadable:{path.name}"]
    metadata, reasons = _metadata(path, plan_dir.name)
    for key in (
        "Requirements",
        "Approved design",
        "Executable plan",
        "Approved review",
        "Head revision",
        "Evidence command",
        "Evidence result",
        "Decision",
        "Unresolved risk",
        "Handoff",
    ):
        if not _concrete(metadata.get(key, "")):
            reasons.append(f"missing_observed_{key.lower().replace(' ', '_')}")
    if metadata.get("Decision") != "verified":
        reasons.append("decision_not_verified")
    reasons.extend(_evidence_matrix_reasons(text))
    review = plan_dir / "code-review.md"
    if review.is_file():
        review_metadata, _ = _metadata(review, plan_dir.name)
        if (
            _concrete(metadata.get("Head revision", ""))
            and _concrete(review_metadata.get("Head revision", ""))
            and metadata["Head revision"] != review_metadata["Head revision"]
        ):
            reasons.append("verification_head_revision_mismatch")
    return reasons


def _validate_debugging(plan_dir: Path) -> list[str]:
    path = plan_dir / "debugging.md"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return [f"unreadable:{path.name}"]
    metadata, reasons = _metadata(path, plan_dir.name)
    if metadata.get("Status") != "complete":
        reasons.append("status_not_complete:debugging.md")
    for label in (
        "Symptom or failing check",
        "Affected task",
        "Reproduction command/scenario",
        "Reproduction count/result",
        "Complete error class/code",
        "Single hypothesis",
        "Minimal experiment",
        "Result",
        "Root-cause fix boundary",
        "RED evidence",
        "GREEN evidence",
        "Remaining uncertainty",
    ):
        if not _concrete(_field(text, label)):
            reasons.append(f"missing_debugging_{label.lower().replace(' ', '_').replace('/', '_')}")
    return reasons


def _validate_task(plan_dir: Path, task_path: Path) -> list[str]:
    try:
        text = task_path.read_text(encoding="utf-8")
    except OSError:
        return [f"unreadable:{task_path.name}"]

    reasons = _metadata(task_path, plan_dir.name)[1]
    if _field(text, "Status") != "complete":
        reasons.append(f"status_not_complete:{task_path.name}")
    for label in (
        "Task ID",
        "Allowed files",
        "Allowed symbols/behavior",
        "Required behavioral check",
        "Out of scope",
        "No subdelegation",
        "Changed paths",
        "Behavioral evidence",
        "Remaining risks",
        "Next artifact/stage",
    ):
        if not _concrete(_field(text, label)):
            reasons.append(f"missing_task_{label.lower().replace(' ', '_').replace('/', '_')}:{task_path.name}")
    if _field(text, "No subdelegation").lower() != "yes":
        reasons.append(f"subdelegation_not_disabled:{task_path.name}")
    lowered = text.lower()
    for phrase in (
        "raw audio",
        "transcript text",
        "credentials",
        "tokens",
        "must not access",
        "has no permission",
    ):
        if phrase not in lowered:
            reasons.append(f"missing_task_privacy_rule:{phrase}:{task_path.name}")
    return reasons

def _validate_tasks(plan_dir: Path) -> list[str]:
    tasks_dir = plan_dir / "tasks"
    if not tasks_dir.is_dir():
        return []
    reasons: list[str] = []
    for path in sorted(tasks_dir.glob("*.md")):
        reasons.extend(_validate_task(plan_dir, path))
    return reasons


def verify(plan_dir: Path) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for filename, expected_status in (
        ("requirements.md", "approved"),
        ("design-review.md", "approved"),
        ("implementation-plan.md", "executable"),
        ("tdd.md", "complete"),
        ("code-review.md", "approved"),
        ("verification.md", "verified"),
    ):
        reasons.extend(_stage_check(plan_dir, filename, expected_status))
    reasons.extend(_validate_plan(plan_dir))
    reasons.extend(_validate_tdd(plan_dir))
    reasons.extend(_validate_review(plan_dir))
    reasons.extend(_validate_verification(plan_dir))
    reasons.extend(_validate_debugging(plan_dir))
    reasons.extend(_validate_tasks(plan_dir))
    return not reasons, reasons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("gate", "verify"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--plan-dir", required=True)
        if name == "gate":
            subparser.add_argument(
                "--risk", choices=("low", "medium", "high", "critical"), required=True
            )
    args = parser.parse_args(argv)
    plan_dir, error = _plan_dir(args.plan_dir)
    if error or plan_dir is None:
        print(json.dumps({"ok": False, "reasons": [error]}))
        return 2

    if args.command == "gate":
        ok, reasons = gate(plan_dir, args.risk)
        result = {"ok": ok, "command": "gate", "plan_id": plan_dir.name, "risk": args.risk}
    else:
        ok, reasons = verify(plan_dir)
        result = {"ok": ok, "command": "verify", "plan_id": plan_dir.name}
    result["reasons"] = reasons
    print(json.dumps(result, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
