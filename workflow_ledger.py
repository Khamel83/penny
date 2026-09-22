"""Durable, metadata-only state for multi-step agent plans.

This ledger is deliberately separate from Penny's capture/transcript database.
It stores plan identity, bounded stage/step state, review findings, and
verification metadata. It never accepts arbitrary bodies or provider payloads.
"""

from __future__ import annotations

import json
import re
import shlex
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

DEFAULT_WORKFLOW_LEDGER_PATH = Path("~/.penny/workflow_ledger.db").expanduser()
MAX_REVIEW_FIX_ROUNDS = 5
_MAX_IDENTIFIER_LENGTH = 128
_MAX_BASELINE_LENGTH = 256
_MAX_COMMAND_LENGTH = 512
_MAX_COMMAND_ARGUMENTS = 32
_MAX_ARGUMENT_LENGTH = 128
_VALID_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_VALID_PATH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:-]{0,255}\Z")
_FORBIDDEN_METADATA = re.compile(
    r"(?:api[_ -]?key|bearer|credential|password|secret|token|"
    r"provider[_ -]?response|raw[_ -]?audio|transcript[_ -]?text|"
    r"personal[_ -]?routing)(?:\b|[_=-])",
    re.IGNORECASE,
)


def _bound_baseline(plan_baseline: str, override: str | None) -> str:
    """Return an explicit override without allowing falsy bypasses."""
    return plan_baseline if override is None else override


class WorkflowLedgerError(Exception):
    """Base class for workflow ledger failures."""


class PlanAlreadyExists(WorkflowLedgerError):
    """The plan identifier is already bound to immutable state."""


class PlanNotFound(WorkflowLedgerError):
    """The requested plan does not exist."""


class BaselineMismatchError(WorkflowLedgerError):
    """The requested plan was created from a different repository baseline."""


class InvalidStageTransition(WorkflowLedgerError):
    """A stage transition would regress or otherwise violate the state machine."""


class RetryLimitExceeded(WorkflowLedgerError):
    """The plan must be replaced after five review/fix rounds."""


class InvalidMetadata(WorkflowLedgerError):
    """Input is not bounded workflow metadata."""


_ALLOWED_STAGE_STATUSES = frozenset(
    {"pending", "in_progress", "blocked", "failed", "completed"}
)
_ALLOWED_TRANSITIONS = {
    "pending": frozenset({"in_progress", "blocked", "failed", "completed"}),
    "in_progress": frozenset({"blocked", "failed", "completed"}),
    "blocked": frozenset({"in_progress", "failed"}),
    "failed": frozenset({"in_progress", "blocked"}),
    "completed": frozenset(),
}
_ALLOWED_FINDING_SEVERITIES = frozenset({"critical", "important", "minor", "info"})
_ALLOWED_FINDING_STATUSES = frozenset({"open", "resolved"})


@dataclass(frozen=True)
class WorkflowPlan:
    """A plan handle bound to one immutable repository baseline."""

    plan_id: str
    repository_baseline: str
    _ledger: WorkflowLedger = field(repr=False, compare=False)

    def transition_stage(
        self,
        stage: str,
        status: str,
        *,
        repository_baseline: str | None = None,
    ) -> bool:
        return self._ledger.transition_stage(
            self.plan_id,
            stage,
            status,
            repository_baseline=_bound_baseline(
                self.repository_baseline, repository_baseline
            ),
        )

    def complete_step(
        self,
        step_id: str,
        *,
        repository_baseline: str | None = None,
    ) -> bool:
        return self._ledger.complete_step(
            self.plan_id,
            step_id,
            repository_baseline=_bound_baseline(
                self.repository_baseline, repository_baseline
            ),
        )

    def start_review_round(self, *, repository_baseline: str | None = None) -> int:
        return self._ledger.start_review_round(
            self.plan_id,
            repository_baseline=_bound_baseline(
                self.repository_baseline, repository_baseline
            ),
        )

    def finish_review_round(
        self,
        round_number: int,
        status: str,
        *,
        repository_baseline: str | None = None,
    ) -> bool:
        return self._ledger.finish_review_round(
            self.plan_id,
            round_number,
            status,
            repository_baseline=_bound_baseline(
                self.repository_baseline, repository_baseline
            ),
        )

    def record_review_finding(
        self,
        round_number: int,
        *,
        finding_id: str,
        severity: str,
        code: str,
        path: str,
        line: int | None = None,
        status: str = "open",
        repository_baseline: str | None = None,
    ) -> bool:
        return self._ledger.record_review_finding(
            self.plan_id,
            round_number,
            finding_id=finding_id,
            severity=severity,
            code=code,
            path=path,
            line=line,
            status=status,
            repository_baseline=_bound_baseline(
                self.repository_baseline, repository_baseline
            ),
        )

    def record_verification(
        self,
        command: str | Sequence[str],
        *,
        exit_code: int,
        status: str | None = None,
        repository_baseline: str | None = None,
    ) -> int:
        return self._ledger.record_verification(
            self.plan_id,
            command,
            exit_code=exit_code,
            status=status,
            repository_baseline=_bound_baseline(
                self.repository_baseline, repository_baseline
            ),
        )

    def snapshot(self, *, repository_baseline: str | None = None) -> dict[str, object]:
        return self._ledger.snapshot(
            self.plan_id,
            repository_baseline=_bound_baseline(
                self.repository_baseline, repository_baseline
            ),
        )


class WorkflowLedger:
    """SQLite-backed plan ledger with per-operation transactions."""

    def __init__(self, db_path: str | Path = DEFAULT_WORKFLOW_LEDGER_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def close(self) -> None:
        """Compatibility no-op; connections are intentionally short-lived."""

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT PRIMARY KEY,
                    repository_baseline TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    review_rounds INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS stages (
                    plan_id TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    PRIMARY KEY (plan_id, stage)
                );
                CREATE TABLE IF NOT EXISTS completed_steps (
                    plan_id TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
                    step_id TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    PRIMARY KEY (plan_id, step_id)
                );
                CREATE TABLE IF NOT EXISTS review_rounds (
                    plan_id TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
                    round_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    PRIMARY KEY (plan_id, round_number)
                );
                CREATE TABLE IF NOT EXISTS review_findings (
                    plan_id TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    finding_id TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    code TEXT NOT NULL,
                    path TEXT NOT NULL,
                    line INTEGER,
                    status TEXT NOT NULL,
                    PRIMARY KEY (plan_id, round_number, finding_id),
                    FOREIGN KEY (plan_id, round_number)
                        REFERENCES review_rounds(plan_id, round_number)
                        ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS verifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
                    command_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    exit_code INTEGER NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_review_findings_plan
                    ON review_findings(plan_id, round_number);
                CREATE INDEX IF NOT EXISTS idx_verifications_plan
                    ON verifications(plan_id, id);
                """
            )
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )

    @staticmethod
    def _identifier(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value or len(value) > _MAX_IDENTIFIER_LENGTH:
            raise InvalidMetadata(f"{field_name} must be a bounded identifier")
        if not _VALID_IDENTIFIER.fullmatch(value):
            raise InvalidMetadata(f"{field_name} contains unsafe metadata")
        if _FORBIDDEN_METADATA.search(value):
            raise InvalidMetadata(f"{field_name} contains forbidden metadata")
        return value

    @staticmethod
    def _baseline(value: str) -> str:
        if not isinstance(value, str) or not value or len(value) > _MAX_BASELINE_LENGTH:
            raise InvalidMetadata("repository_baseline must be bounded")
        if any(character.isspace() for character in value) or any(
            ord(character) < 32 for character in value
        ):
            raise InvalidMetadata("repository_baseline must be a stable identity")
        if _FORBIDDEN_METADATA.search(value):
            raise InvalidMetadata("repository_baseline contains forbidden metadata")
        return value

    @staticmethod
    def _path(value: str) -> str:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 256
            or value.startswith("/")
            or ".." in value.split("/")
            or not _VALID_PATH.fullmatch(value)
        ):
            raise InvalidMetadata("path must be a repository-relative metadata path")
        if _FORBIDDEN_METADATA.search(value):
            raise InvalidMetadata("path contains forbidden metadata")
        return value

    @classmethod
    def _command(cls, command: str | Sequence[str]) -> list[str]:
        if isinstance(command, str):
            if len(command) > _MAX_COMMAND_LENGTH:
                raise InvalidMetadata("verification command is too long")
            try:
                parts = shlex.split(command)
            except ValueError as error:
                raise InvalidMetadata("verification command is not parseable") from error
        elif isinstance(command, Sequence) and not isinstance(command, (bytes, bytearray)):
            parts = list(command)
        else:
            raise InvalidMetadata("verification command must be argv metadata")
        if not parts or len(parts) > _MAX_COMMAND_ARGUMENTS:
            raise InvalidMetadata("verification command has invalid argument count")
        normalized: list[str] = []
        for part in parts:
            if not isinstance(part, str) or not part or len(part) > _MAX_ARGUMENT_LENGTH:
                raise InvalidMetadata("verification command argument is not bounded")
            if any(ord(character) < 32 for character in part):
                raise InvalidMetadata("verification command contains control data")
            if _FORBIDDEN_METADATA.search(part):
                raise InvalidMetadata("verification command contains forbidden metadata")
            normalized.append(part)
        return normalized

    def _require_plan(
        self,
        connection: sqlite3.Connection,
        plan_id: str,
        repository_baseline: str,
    ) -> sqlite3.Row:
        self._identifier(plan_id, "plan_id")
        baseline = self._baseline(repository_baseline)
        row = connection.execute(
            "SELECT * FROM plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        if row is None:
            raise PlanNotFound(plan_id)
        if row["repository_baseline"] != baseline:
            raise BaselineMismatchError(
                f"plan {plan_id!r} is bound to a different repository baseline"
            )
        return row

    def create_plan(
        self,
        *,
        repository_baseline: str,
        plan_id: str | None = None,
        stages: Iterable[str] = (),
    ) -> WorkflowPlan:
        baseline = self._baseline(repository_baseline)
        identifier = (
            uuid.uuid4().hex
            if plan_id is None
            else self._identifier(plan_id, "plan_id")
        )
        stage_names = [self._identifier(stage, "stage") for stage in stages]
        if len(stage_names) != len(set(stage_names)):
            raise InvalidMetadata("stages must be unique")
        now = self._now()
        connection = self._connect()
        try:
            with connection:
                try:
                    connection.execute(
                        "INSERT INTO plans(plan_id, repository_baseline, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?)",
                        (identifier, baseline, now, now),
                    )
                except sqlite3.IntegrityError as error:
                    raise PlanAlreadyExists(identifier) from error
                connection.executemany(
                    "INSERT INTO stages(plan_id, stage, status, updated_at) VALUES (?, ?, 'pending', ?)",
                    [(identifier, stage, now) for stage in stage_names],
                )
        finally:
            connection.close()
        return WorkflowPlan(identifier, baseline, self)

    def resume_plan(self, plan_id: str, repository_baseline: str) -> WorkflowPlan:
        connection = self._connect()
        try:
            row = self._require_plan(connection, plan_id, repository_baseline)
        finally:
            connection.close()
        return WorkflowPlan(row["plan_id"], row["repository_baseline"], self)

    def transition_stage(
        self,
        plan_id: str,
        stage: str,
        status: str,
        *,
        repository_baseline: str,
    ) -> bool:
        stage = self._identifier(stage, "stage")
        if not isinstance(status, str) or status not in _ALLOWED_STAGE_STATUSES:
            raise InvalidMetadata("unknown stage status")
        now = self._now()
        connection = self._connect()
        try:
            with connection:
                self._require_plan(connection, plan_id, repository_baseline)
                current = connection.execute(
                    "SELECT status FROM stages WHERE plan_id = ? AND stage = ?",
                    (plan_id, stage),
                ).fetchone()
                if current is None:
                    connection.execute(
                        "INSERT INTO stages(plan_id, stage, status, updated_at, completed_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (plan_id, stage, status, now, now if status == "completed" else None),
                    )
                    connection.execute(
                        "UPDATE plans SET updated_at = ? WHERE plan_id = ?",
                        (now, plan_id),
                    )
                    return True
                current_status = current["status"]
                if current_status == status:
                    return False
                if status not in _ALLOWED_TRANSITIONS[current_status]:
                    raise InvalidStageTransition(
                        f"cannot move stage {stage!r} from {current_status!r} to {status!r}"
                    )
                connection.execute(
                    "UPDATE stages SET status = ?, updated_at = ?, completed_at = ? "
                    "WHERE plan_id = ? AND stage = ?",
                    (
                        status,
                        now,
                        now if status == "completed" else None,
                        plan_id,
                        stage,
                    ),
                )
                connection.execute(
                    "UPDATE plans SET updated_at = ? WHERE plan_id = ?",
                    (now, plan_id),
                )
                return True
        finally:
            connection.close()

    def complete_step(
        self,
        plan_id: str,
        step_id: str,
        *,
        repository_baseline: str,
    ) -> bool:
        step_id = self._identifier(step_id, "step_id")
        connection = self._connect()
        try:
            with connection:
                self._require_plan(connection, plan_id, repository_baseline)
                result = connection.execute(
                    "INSERT OR IGNORE INTO completed_steps(plan_id, step_id, completed_at) "
                    "VALUES (?, ?, ?)",
                    (plan_id, step_id, self._now()),
                )
                if result.rowcount == 1:
                    connection.execute(
                        "UPDATE plans SET updated_at = ? WHERE plan_id = ?",
                        (self._now(), plan_id),
                    )
                    return True
                return False
        finally:
            connection.close()

    def start_review_round(
        self, plan_id: str, *, repository_baseline: str
    ) -> int:
        now = self._now()
        connection = self._connect()
        try:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                self._require_plan(connection, plan_id, repository_baseline)
                latest = connection.execute(
                    "SELECT round_number, status FROM review_rounds "
                    "WHERE plan_id = ? ORDER BY round_number DESC LIMIT 1",
                    (plan_id,),
                ).fetchone()
                if latest is not None and latest["status"] == "in_progress":
                    return int(latest["round_number"])
                if latest is not None and int(latest["round_number"]) >= MAX_REVIEW_FIX_ROUNDS:
                    raise RetryLimitExceeded(
                        "review/fix retry limit exceeded; create a fresh plan"
                    )
                round_number = int(latest["round_number"]) + 1 if latest else 1
                connection.execute(
                    "INSERT INTO review_rounds(plan_id, round_number, status, started_at) "
                    "VALUES (?, ?, 'in_progress', ?)",
                    (plan_id, round_number, now),
                )
                connection.execute(
                    "UPDATE plans SET review_rounds = ?, updated_at = ? WHERE plan_id = ?",
                    (round_number, now, plan_id),
                )
                return round_number
        finally:
            connection.close()

    def finish_review_round(
        self,
        plan_id: str,
        round_number: int,
        status: str,
        *,
        repository_baseline: str,
    ) -> bool:
        if not isinstance(status, str) or status not in {"fix_required", "passed"}:
            raise InvalidMetadata("review round must finish as fix_required or passed")
        if (
            not isinstance(round_number, int)
            or isinstance(round_number, bool)
            or round_number < 1
        ):
            raise InvalidMetadata("round_number must be positive")
        now = self._now()
        connection = self._connect()
        try:
            with connection:
                self._require_plan(connection, plan_id, repository_baseline)
                current = connection.execute(
                    "SELECT status FROM review_rounds WHERE plan_id = ? AND round_number = ?",
                    (plan_id, round_number),
                ).fetchone()
                if current is None:
                    raise WorkflowLedgerError("review round does not exist")
                if current["status"] == status:
                    return False
                if current["status"] != "in_progress":
                    raise WorkflowLedgerError("review round is already finished")
                connection.execute(
                    "UPDATE review_rounds SET status = ?, completed_at = ? "
                    "WHERE plan_id = ? AND round_number = ?",
                    (status, now, plan_id, round_number),
                )
                connection.execute(
                    "UPDATE plans SET updated_at = ? WHERE plan_id = ?", (now, plan_id)
                )
                return True
        finally:
            connection.close()

    def record_review_finding(
        self,
        plan_id: str,
        round_number: int,
        *,
        finding_id: str,
        severity: str,
        code: str,
        path: str,
        line: int | None = None,
        status: str = "open",
        repository_baseline: str,
    ) -> bool:
        finding_id = self._identifier(finding_id, "finding_id")
        code = self._identifier(code, "finding_code")
        path = self._path(path)
        if not isinstance(severity, str) or severity not in _ALLOWED_FINDING_SEVERITIES:
            raise InvalidMetadata("unknown finding severity")
        if not isinstance(status, str) or status not in _ALLOWED_FINDING_STATUSES:
            raise InvalidMetadata("unknown finding status")
        if (
            not isinstance(round_number, int)
            or isinstance(round_number, bool)
            or round_number < 1
        ):
            raise InvalidMetadata("round_number must be positive")
        if line is not None and (
            not isinstance(line, int)
            or isinstance(line, bool)
            or line < 1
            or line > 10_000_000
        ):
            raise InvalidMetadata("finding line is out of bounds")
        connection = self._connect()
        try:
            with connection:
                self._require_plan(connection, plan_id, repository_baseline)
                if connection.execute(
                    "SELECT 1 FROM review_rounds WHERE plan_id = ? AND round_number = ?",
                    (plan_id, round_number),
                ).fetchone() is None:
                    raise WorkflowLedgerError("review round does not exist")
                result = connection.execute(
                    "INSERT OR IGNORE INTO review_findings "
                    "(plan_id, round_number, finding_id, severity, code, path, line, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (plan_id, round_number, finding_id, severity, code, path, line, status),
                )
                if result.rowcount == 1:
                    connection.execute(
                        "UPDATE plans SET updated_at = ? WHERE plan_id = ?",
                        (self._now(), plan_id),
                    )
                    return True
                return False
        finally:
            connection.close()

    def record_verification(
        self,
        plan_id: str,
        command: str | Sequence[str],
        *,
        exit_code: int,
        status: str | None = None,
        repository_baseline: str,
    ) -> int:
        argv = self._command(command)
        if (
            not isinstance(exit_code, int)
            or isinstance(exit_code, bool)
            or exit_code < 0
            or exit_code > 255
        ):
            raise InvalidMetadata("exit_code must be between 0 and 255")
        verification_status = (
            ("passed" if exit_code == 0 else "failed")
            if status is None
            else status
        )
        if (
            not isinstance(verification_status, str)
            or verification_status not in {"passed", "failed"}
        ):
            raise InvalidMetadata("verification status must be passed or failed")
        connection = self._connect()
        try:
            with connection:
                self._require_plan(connection, plan_id, repository_baseline)
                result = connection.execute(
                    "INSERT INTO verifications "
                    "(plan_id, command_json, status, exit_code, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        plan_id,
                        json.dumps(argv, separators=(",", ":")),
                        verification_status,
                        exit_code,
                        self._now(),
                    ),
                )
                connection.execute(
                    "UPDATE plans SET updated_at = ? WHERE plan_id = ?",
                    (self._now(), plan_id),
                )
                return int(result.lastrowid)
        finally:
            connection.close()

    def snapshot(
        self, plan_id: str, *, repository_baseline: str
    ) -> dict[str, object]:
        connection = self._connect()
        try:
            plan = self._require_plan(connection, plan_id, repository_baseline)
            stages = {
                row["stage"]: row["status"]
                for row in connection.execute(
                    "SELECT stage, status FROM stages WHERE plan_id = ? ORDER BY stage",
                    (plan_id,),
                )
            }
            completed_steps = [
                row["step_id"]
                for row in connection.execute(
                    "SELECT step_id FROM completed_steps WHERE plan_id = ? ORDER BY completed_at, step_id",
                    (plan_id,),
                )
            ]
            rounds = [
                {
                    "round": row["round_number"],
                    "status": row["status"],
                    "started_at": row["started_at"],
                    "completed_at": row["completed_at"],
                }
                for row in connection.execute(
                    "SELECT round_number, status, started_at, completed_at "
                    "FROM review_rounds WHERE plan_id = ? ORDER BY round_number",
                    (plan_id,),
                )
            ]
            findings = [
                {
                    "round": row["round_number"],
                    "finding_id": row["finding_id"],
                    "severity": row["severity"],
                    "code": row["code"],
                    "path": row["path"],
                    "line": row["line"],
                    "status": row["status"],
                }
                for row in connection.execute(
                    "SELECT round_number, finding_id, severity, code, path, line, status "
                    "FROM review_findings WHERE plan_id = ? ORDER BY round_number, finding_id",
                    (plan_id,),
                )
            ]
            verifications = [
                {
                    "id": row["id"],
                    "command": json.loads(row["command_json"]),
                    "status": row["status"],
                    "exit_code": row["exit_code"],
                    "recorded_at": row["recorded_at"],
                }
                for row in connection.execute(
                    "SELECT id, command_json, status, exit_code, recorded_at "
                    "FROM verifications WHERE plan_id = ? ORDER BY id",
                    (plan_id,),
                )
            ]
            return {
                "plan_id": plan["plan_id"],
                "repository_baseline": plan["repository_baseline"],
                "created_at": plan["created_at"],
                "updated_at": plan["updated_at"],
                "stages": stages,
                "completed_steps": completed_steps,
                "review_rounds": rounds,
                "review_findings": findings,
                "verifications": verifications,
            }
        finally:
            connection.close()
