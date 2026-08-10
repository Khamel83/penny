#!/usr/bin/env python3
"""Read-only Penny readiness probes.

The Doctor is deliberately a metadata boundary.  It may inspect SQLite
schema/integrity, outbox counters, receipt metadata, model manifests and
health-file timestamps, but it never reads transcript/audio bodies, opens a
macOS TCC database, contacts a provider, or repairs state.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote

import transcript_log

try:  # Config import is intentionally lazy in run_doctor for testability.
    from config import get_config
except Exception:  # pragma: no cover - a broken config is a Doctor result.
    get_config = None  # type: ignore[assignment]

try:
    from transcript_quality import ModelUnavailableError, resolve_whisper_model
except Exception:  # pragma: no cover - dependency failure is reported safely.
    ModelUnavailableError = RuntimeError  # type: ignore[assignment,misc]
    resolve_whisper_model = None  # type: ignore[assignment]


UTC = timezone.utc
_STATE_VALUES = frozenset({"ready", "degraded", "unready", "unknown"})
_SAFE_REASON_VALUES = frozenset(
    {
        "ok",
        "backlog",
        "callback_secret_missing",
        "backup_stale",
        "backup_unverified",
        "bind_policy",
        "configuration_missing",
        "database_unavailable",
        "dead_letter",
        "disabled",
        "foreign_key_failure",
        "health_stale",
        "integrity_failure",
        "launchd_unavailable",
        "missing",
        "model_offline_required",
        "model_unavailable",
        "non_loopback_bind",
        "permission_denied",
        "probe_error",
        "provider_failure",
        "quarantine",
        "retryable_failure",
        "schema_failure",
        "secret_missing",
        "source_stale",
        "source_unavailable",
        "terminal_failure",
        "timestamp_invalid",
        "uncertain_effect",
        "unknown",
    }
)
_SAFE_DETAIL_KEYS = frozenset(
    {
        "age_seconds",
        "archive_backfill_failed_count",
        "archive_invalid_count",
        "archive_pending_count",
        "archive_rebuild_needed_count",
        "archive_failed_count",
        "invalid_count",
        "rebuild_needed_count",
        "awaiting_file_count",
        "backup_catalog_present",
        "backup_set_present",
        "callback_secret_configured",
        "callback_secret_missing",
        "dead_letter_count",
        "failed_count",
        "foreign_keys_ok",
        "health_error",
        "integrity_ok",
        "launchd_ok",
        "local_mirror_published_count",
        "loopback_bind",
        "max_attempt_count",
        "pending_count",
        "query_ok",
        "quarantined_count",
        "retry_due_count",
        "schema_ok",
        "secret_configured",
        "slack_failed_count",
        "source_watermark",
        "source_health_age_seconds",
        "stale_in_flight_count",
        "terminal_failure_count",
        "uncertain_count",
        "verified",
        "watcher_ok",
        "tasks_ok",
        "voicememos_responsive",
        "voice_db_ok",
        "offline",
        "integrity_check_ok",
        "foreign_key_check_ok",
        "schema_table_count",
        "row_count",
        "max_transcript_id",
        "configured",
        "completion_pending_count",
        "configuration_partial",
        "migration_quarantine_count",
        "latest_set_matches_receipt",
        "protected_bind",
        "timestamp_valid",
        "latest_set_present",
        "database_metadata_bound",
    }
)
_FULL_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SET_ID_RE = re.compile(r"^\d{8}T\d{6}Z$")
_DEFAULT_HEALTH_MAX_AGE_SECONDS = 15 * 60
_DEFAULT_BACKUP_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


def _configured_value(value: object) -> bool:
    """Return whether a config/environment value is non-empty and concrete.

    Doctor only reports a boolean presence bit.  Common repository template
    markers are deliberately treated as absent so a loaded launchd plist or
    environment cannot appear healthy merely because a key exists.
    """

    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate:
        return False
    upper = candidate.upper()
    if (
        upper.startswith(("YOUR_", "REPLACE_", "CHANGE_ME", "CHANGEME", "TODO_"))
        or "_HERE" in upper
        or "PLACEHOLDER" in upper
        or candidate.startswith("<")
        or candidate.endswith(">")
    ):
        return False
    return True


def _capture_startup_source_revision(*, runner: Callable[..., Any] | None = None) -> str:
    """Capture the checkout revision once, before a long-lived service starts."""

    runner = runner or subprocess.run
    checkout = str(Path(__file__).resolve().parent)
    try:
        for command in (
            ["git", "-C", checkout, "diff", "--quiet", "HEAD", "--"],
            ["git", "-C", checkout, "diff", "--quiet", "--cached", "--"],
        ):
            clean = runner(
                command,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if getattr(clean, "returncode", 1) != 0:
                return "unknown"
        result = runner(
            ["git", "-C", checkout, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        value = str(getattr(result, "stdout", "") or "").strip().lower()
        if getattr(result, "returncode", 1) == 0 and _FULL_SHA_RE.fullmatch(value):
            return value
    except (OSError, subprocess.SubprocessError, TypeError):
        pass
    return "unknown"


# A launchd process must retain the revision it started from.  Reading HEAD
# on every health request could report a newly checked-out revision before the
# service has actually restarted.
_STARTUP_SOURCE_REVISION = _capture_startup_source_revision()


_REQUIRED_PROBE_KEYS: dict[str, frozenset[str]] = {
    "voice_memos": frozenset(
        {
            "query_ok",
            "voicememos_responsive",
            "voice_db_ok",
            "source_health_age_seconds",
            "timestamp_valid",
        }
    ),
    "backup": frozenset({"verified", "age_seconds", "timestamp_valid"}),
    "services": frozenset(
        {
            "watcher_ok",
            "tasks_ok",
            "launchd_ok",
            "age_seconds",
            "timestamp_valid",
            "voicememos_responsive",
            "voice_db_ok",
        }
    ),
    "ingress": frozenset(
        {"secret_configured", "callback_secret_configured", "loopback_bind", "protected_bind"}
    ),
}


@dataclass(frozen=True)
class ComponentStatus:
    """Safe status for one Doctor component."""

    component: str
    state: str
    reason: str
    details: dict[str, int | bool]
    observed_at: str

    def __post_init__(self) -> None:
        # Keep the dataclass safe even when an adapter constructs it directly
        # (rather than going through ``run_doctor``).
        object.__setattr__(self, "state", _safe_state(self.state))
        object.__setattr__(self, "reason", _safe_reason(self.reason, "unknown"))
        object.__setattr__(self, "details", _safe_details(self.details))

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "reason": self.reason,
            "details": dict(self.details),
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True)
class DoctorReport:
    """The stable operator/HTTP report contract."""

    overall: str
    components: dict[str, ComponentStatus]
    observed_at: str
    source_revision: str

    def __post_init__(self) -> None:
        overall = _safe_state(self.overall)
        object.__setattr__(self, "overall", overall)
        safe_components = {
            str(name): value
            if isinstance(value, ComponentStatus)
            else ComponentStatus(str(name), "unknown", "unknown", {}, self.observed_at)
            for name, value in self.components.items()
        }
        object.__setattr__(self, "components", safe_components)
        revision = str(self.source_revision or "").strip().lower()
        object.__setattr__(self, "source_revision", revision if _FULL_SHA_RE.fullmatch(revision) else "unknown")

    def to_dict(self) -> dict[str, object]:
        return {
            "overall": self.overall,
            "components": {
                name: status.to_dict() for name, status in self.components.items()
            },
            "observed_at": self.observed_at,
            "source_revision": self.source_revision,
        }


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC)


def _utc_text(value: datetime | None = None) -> str:
    return _now(value).isoformat().replace("+00:00", "Z")


def _parse_observed_timestamp(value: object, *, now: datetime | None = None) -> datetime | None:
    """Parse only an explicit timezone timestamp that is not in the future."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        return None
    parsed = parsed.astimezone(UTC)
    if parsed > _now(now):
        return None
    return parsed


def _age_seconds(value: object, *, now: datetime | None = None) -> tuple[int | None, bool]:
    parsed = _parse_observed_timestamp(value, now=now)
    if parsed is None:
        return None, False
    return max(0, int((_now(now) - parsed).total_seconds())), True


def _safe_details(data: Mapping[str, Any] | None) -> dict[str, int | bool]:
    """Allowlist scalar metadata; drop bodies, paths, URLs and errors."""

    result: dict[str, int | bool] = {}
    if not isinstance(data, Mapping):
        return result
    for key in _SAFE_DETAIL_KEYS:
        value = data.get(key)
        if isinstance(value, bool):
            result[key] = value
        elif isinstance(value, int) and not isinstance(value, bool):
            result[key] = max(0, min(value, 2_147_483_647))
    return dict(sorted(result.items()))


def _safe_reason(value: object, fallback: str = "probe_error") -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in _SAFE_REASON_VALUES else fallback


def _safe_state(value: object) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in _STATE_VALUES else "unknown"


def _probe_has_required_evidence(name: str, values: Mapping[str, Any]) -> bool:
    required = _REQUIRED_PROBE_KEYS.get(name)
    return not required or required.issubset(values.keys())


def _sha256_file(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except (OSError, ValueError):
        return None
    return digest.hexdigest()


def _source_revision() -> str:
    for key in ("PENNY_SOURCE_REVISION", "GITHUB_SHA"):
        value = str(os.environ.get(key, "")).strip().lower()
        if _FULL_SHA_RE.fullmatch(value):
            return value
    return _STARTUP_SOURCE_REVISION


def _sqlite_path() -> Path:
    return Path(os.environ.get("PENNY_TRANSCRIPT_DB", str(transcript_log.TRANSCRIPT_DB_PATH))).expanduser()


def _default_probe_sqlite(_config: Any = None, *, now: datetime | None = None, **_kwargs: Any) -> dict[str, Any]:
    del now
    path = _sqlite_path()
    if not path.exists() or path.is_symlink() or not path.is_file():
        return {"query_ok": 0, "reason": "missing"}
    encoded = quote(str(path.resolve()), safe="/")
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True, timeout=2.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0]).lower() == "ok"
        foreign_keys = len(connection.execute("PRAGMA foreign_key_check").fetchall()) == 0
        rows = connection.execute(
            "SELECT type, name FROM sqlite_master WHERE type IN ('table', 'index', 'trigger', 'view')"
        ).fetchall()
        names = {str(row[1]) for row in rows}
        schema_ok = {"transcripts", "source_watermarks"}.issubset(names)
        row_count = int(connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0])
        max_id = connection.execute("SELECT MAX(id) FROM transcripts").fetchone()[0]
        return {
            "query_ok": 1,
            "integrity_ok": int(integrity),
            "foreign_keys_ok": int(foreign_keys),
            "schema_ok": int(schema_ok),
            "schema_table_count": len(names),
            "row_count": row_count,
            "max_transcript_id": int(max_id or 0),
        }
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return {"query_ok": 0, "reason": "database_unavailable"}
    finally:
        if connection is not None:
            connection.close()


def _default_probe_voice_memos(_config: Any = None, *, now: datetime | None = None, **_kwargs: Any) -> dict[str, Any]:
    current = _now(now)
    health = transcript_log.get_voice_memo_health()
    watcher_path = Path(os.environ.get("PENNY_HEALTH_FILE", "~/.penny/health.txt")).expanduser()
    data = {
        key: health.get(key, 0)
        for key in (
            "query_ok",
            "health_error",
            "terminal_failure_count",
            "failed_count",
            "retry_due_count",
            "completion_pending_count",
            "awaiting_file_count",
            "source_watermark",
            "max_attempt_count",
        )
    }
    data["voicememos_responsive"] = _health_flag(
        watcher_path, "voicememos_responsive"
    )
    data["voice_db_ok"] = _health_flag(watcher_path, "voice_db_ok")
    file_age, file_valid = _health_file_age(watcher_path, now=current)
    text_age, text_valid = _health_text_age(watcher_path, now=current)
    source_age = text_age if text_valid else file_age
    data["source_health_age_seconds"] = source_age or 0
    data["timestamp_valid"] = bool(file_valid and text_valid)
    waiting = health.get("oldest_waiting_discovered_at")
    if waiting:
        age, valid = _age_seconds(waiting, now=now)
        data["age_seconds"] = age if age is not None else 0
        if not valid:
            data["timestamp_valid"] = False
            data["reason"] = "timestamp_invalid"
    return data


def _default_probe_archive(_config: Any = None, *, now: datetime | None = None, **_kwargs: Any) -> dict[str, Any]:
    del now
    health = transcript_log.get_archive_delivery_health()
    return {
        "health_error": health.get("health_error", 1),
        "pending_count": health.get("pending_count", 0),
        "failed_count": health.get("failed_count", 0),
        "invalid_count": health.get("invalid_count", 0),
        "rebuild_needed_count": health.get("rebuild_needed_count", 0),
        "archive_backfill_failed_count": health.get("backfill_failed_count", 0),
        "local_mirror_published_count": health.get("local_mirror_published_count", 0),
    }


def _default_probe_transcription(config: Any, *, now: datetime | None = None, **_kwargs: Any) -> dict[str, Any]:
    del now
    offline = os.environ.get("HF_HUB_OFFLINE") == "1"
    if not offline:
        return {"verified": 0, "offline": 0, "reason": "model_offline_required"}
    if config is None or resolve_whisper_model is None:
        return {"verified": 0, "offline": 1, "reason": "model_unavailable"}
    try:
        model_path = config.voice_memos.whisper_model_path
        resolve_whisper_model(
            model_path,
            expected_repository=config.voice_memos.whisper_model_repository,
            expected_revision=config.voice_memos.whisper_model_revision,
        )
    except (ModelUnavailableError, OSError, ValueError, TypeError):
        return {"verified": 0, "offline": 1, "reason": "model_unavailable"}
    return {"verified": 1, "offline": 1}


def _default_probe_apple_effects(_config: Any = None, *, now: datetime | None = None, **_kwargs: Any) -> dict[str, Any]:
    del now
    return transcript_log.get_apple_effect_health()


def _default_probe_maya(config: Any, *, now: datetime | None = None, **_kwargs: Any) -> dict[str, Any]:
    del now
    health = transcript_log.get_maya_delivery_health()
    launchd_keys = _launchd_environment_keys(
        "com.penny.watcher", ("MAYA_TRANSCRIPT_URL", "MAYA_INGEST_TOKEN")
    )
    url_configured = bool(
        config is not None
        and _configured_value(getattr(config.maya, "transcript_url", ""))
    ) or "MAYA_TRANSCRIPT_URL" in launchd_keys
    token_configured = bool(
        config is not None
        and _configured_value(getattr(config.maya, "ingest_token", ""))
    ) or "MAYA_INGEST_TOKEN" in launchd_keys
    configured = url_configured and token_configured
    pending_age = max(
        int(health.get("oldest_pending_age_seconds", 0) or 0),
        int(health.get("oldest_due_age_seconds", 0) or 0),
    )
    return {
        "configured": configured,
        "configuration_partial": url_configured != token_configured,
        "query_ok": health.get("query_ok", 0),
        "health_error": health.get("health_error", 1),
        "pending_count": health.get("pending_count", 0),
        "failed_count": health.get("failed_count", 0),
        "dead_letter_count": health.get("dead_letter_count", 0),
        "max_attempt_count": health.get("max_attempt_count", 0),
        "age_seconds": pending_age,
    }


def _default_probe_slack(_config: Any = None, *, now: datetime | None = None, **_kwargs: Any) -> dict[str, Any]:
    del now
    health = transcript_log.get_slack_delivery_health()
    launchd_keys = _launchd_environment_keys(
        "com.penny.watcher", ("PENNY_SLACK_BOT_TOKEN",)
    )
    return {
        "configured": _configured_value(os.environ.get("PENNY_SLACK_BOT_TOKEN", ""))
        or "PENNY_SLACK_BOT_TOKEN" in launchd_keys,
        "query_ok": health.get("query_ok", 0),
        "health_error": health.get("health_error", 1),
        "pending_count": health.get("pending_count", 0),
        "failed_count": health.get("failed_count", 0),
        "slack_failed_count": health.get("quality_failure_failed_count", 0),
    }


def _health_file_age(path: Path, *, now: datetime) -> tuple[int | None, bool]:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            return None, False
        mtime = datetime.fromtimestamp(info.st_mtime, UTC)
    except (OSError, ValueError, OverflowError):
        return None, False
    if mtime > now:
        return None, False
    return max(0, int((now - mtime).total_seconds())), True


def _read_health_text(path: Path, limit: int) -> str | None:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return None
            return handle.read(limit).decode("utf-8", errors="replace")
    except OSError:
        return None


def _health_flag(path: Path, key: str) -> bool:
    text = _read_health_text(path, 1024)
    if text is None:
        return False
    expected = f"{key}:1"
    return any(
        token.strip() == expected
        for token in text.replace("\r", "\n").replace("\n", "|").split("|")
    )


def _health_text_age(path: Path, *, now: datetime) -> tuple[int | None, bool]:
    text = _read_health_text(path, 128)
    if text is None:
        return None, False
    timestamp = text.split("|", 1)[0].strip()
    parsed = _parse_observed_timestamp(timestamp, now=now)
    if parsed is None:
        return None, False
    return max(0, int((now - parsed).total_seconds())), True


def _launchd_status(*, runner: Callable[..., Any] | None = None) -> bool:
    if os.name != "posix" or not hasattr(os, "getuid"):
        return False
    runner = runner or subprocess.run
    uid = os.getuid()
    labels = ("com.penny.watcher", "com.penny.webhook", "com.penny.tasks", "com.penny.export")
    for label in labels:
        try:
            result = runner(
                ["launchctl", "print", f"gui/{uid}/{label}"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, TypeError):
            return False
        if getattr(result, "returncode", 1) != 0:
            return False
    return True


def _launchd_environment_keys(
    label: str,
    keys: tuple[str, ...],
    *,
    runner: Callable[..., Any] | None = None,
) -> set[str]:
    """Return configured key names without retaining or rendering values."""

    if os.name != "posix" or not hasattr(os, "getuid") or not keys:
        return set()
    runner = runner or subprocess.run
    try:
        result = runner(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, TypeError):
        return set()
    if getattr(result, "returncode", 1) != 0:
        return set()
    output = str(getattr(result, "stdout", "") or "")
    configured: set[str] = set()
    for key in keys:
        match = re.search(
            rf"[\"'`]?(?P<key>{re.escape(key)})[\"'`]?\s*(?:=>|=)\s*(?P<value>[^\n,}}]+)",
            output,
        )
        if match is None:
            continue
        value = match.group("value").strip().strip("\"'").strip()
        if _configured_value(value):
            configured.add(key)
    return configured


def _launchd_environment_value(
    label: str,
    key: str,
    *,
    runner: Callable[..., Any] | None = None,
) -> str:
    """Return only a bounded classification for one launchd value."""

    if os.name != "posix" or not hasattr(os, "getuid"):
        return "missing"
    runner = runner or subprocess.run
    try:
        result = runner(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, TypeError):
        return "missing"
    if getattr(result, "returncode", 1) != 0:
        return "missing"
    output = str(getattr(result, "stdout", "") or "")
    match = re.search(
        rf"[\"'`]?(?P<key>{re.escape(key)})[\"'`]?\s*(?:=>|=)\s*(?P<value>[^\n,}}]+)",
        output,
    )
    if match is None:
        return "missing"
    value = match.group("value").strip().strip("\"'").strip()
    if not _configured_value(value):
        return "missing"
    if key == "PENNY_WEBHOOK_HOST":
        return "loopback" if value.lower() in {"127.0.0.1", "::1", "localhost"} else "non_loopback"
    if key == "PENNY_WEBHOOK_ALLOW_NONLOOPBACK":
        return "enabled" if value.lower() in {"1", "true", "yes"} else "disabled"
    return "configured"


def _default_probe_services(_config: Any = None, *, now: datetime | None = None, **_kwargs: Any) -> dict[str, Any]:
    current = _now(now)
    watcher_path = Path(os.environ.get("PENNY_HEALTH_FILE", "~/.penny/health.txt")).expanduser()
    tasks_path = Path(os.environ.get("PENNY_TASKS_HEALTH_FILE", "~/.penny/health_tasks.txt")).expanduser()
    watcher_age, watcher_valid = _health_file_age(watcher_path, now=current)
    text_age, text_valid = _health_text_age(watcher_path, now=current)
    if text_valid:
        watcher_age = text_age
    else:
        watcher_valid = False
    tasks_age, tasks_valid = _health_file_age(tasks_path, now=current)
    watcher_ok = watcher_valid and _health_flag(watcher_path, "watcher_ok")
    tasks_ok = tasks_valid and _health_flag(tasks_path, "tasks_poller_ok")
    age = max(watcher_age or 0, tasks_age or 0)
    return {
        "watcher_ok": watcher_ok,
        "tasks_ok": tasks_ok,
        "launchd_ok": _launchd_status(),
        "age_seconds": age,
        "timestamp_valid": bool(watcher_valid),
        "voicememos_responsive": _health_flag(
            watcher_path, "voicememos_responsive"
        ),
        "voice_db_ok": _health_flag(watcher_path, "voice_db_ok"),
    }


def _verification_receipt_path(root: Path) -> Path:
    configured = os.environ.get("PENNY_BACKUP_VERIFICATION_RECEIPT", "").strip()
    if configured:
        return Path(configured).expanduser()
    return root / "last_verification.json"


def _latest_catalog(root: Path) -> tuple[Path | None, bool]:
    sets = root / "sets"
    if sets.is_symlink() or not sets.is_dir():
        return None, False
    candidates = [entry for entry in sets.iterdir() if entry.is_dir() and _SET_ID_RE.fullmatch(entry.name)]
    candidates.sort(key=lambda entry: entry.name, reverse=True)
    for candidate in candidates:
        catalog = candidate / "catalog.json"
        if catalog.is_file() and not catalog.is_symlink():
            return catalog, True
    return None, False


def _default_probe_backup(
    _config: Any = None,
    *,
    now: datetime | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    current = _now(now)
    root = Path(os.environ.get("PENNY_BACKUP_ROOT", "~/.penny/backup")).expanduser()
    catalog_path, catalog_present = _latest_catalog(root)
    receipt_path = _verification_receipt_path(root)
    receipt_present = receipt_path.is_file() and not receipt_path.is_symlink()
    data: dict[str, Any] = {
        "verified": False,
        "backup_catalog_present": catalog_present,
        "backup_set_present": catalog_present,
        "latest_set_present": catalog_present,
    }
    if receipt_present:
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, TypeError):
            return {**data, "reason": "backup_unverified"}
        receipt_id = str(receipt.get("backup_set_id", ""))
        receipt_hash = str(receipt.get("catalog_sha256", "")).lower()
        receipt_set_catalog = root / "sets" / receipt_id / "catalog.json"
        receipt_set_present = (
            bool(_SET_ID_RE.fullmatch(receipt_id))
            and all(
                not component.is_symlink()
                for component in (
                    root,
                    root / "sets",
                    root / "sets" / receipt_id,
                    receipt_set_catalog,
                )
            )
            and receipt_set_catalog.is_file()
        )
        data["backup_set_present"] = receipt_set_present
        latest_set_matches = bool(catalog_path is not None and catalog_path.parent.name == receipt_id)
        data["latest_set_matches_receipt"] = latest_set_matches
        actual_catalog_sha = _sha256_file(receipt_set_catalog) if receipt_set_present else None
        database_metadata_bound = False
        receipt_row_count = receipt.get("row_count")
        receipt_max_id = receipt.get("max_transcript_id")
        if (
            receipt_set_present
            and "row_count" in receipt
            and "max_transcript_id" in receipt
            and isinstance(receipt_row_count, int)
            and not isinstance(receipt_row_count, bool)
            and receipt_row_count >= 0
            and (receipt_max_id is None or (isinstance(receipt_max_id, int) and not isinstance(receipt_max_id, bool) and receipt_max_id >= 0))
        ):
            try:
                catalog_value = json.loads(receipt_set_catalog.read_text(encoding="utf-8"))
                database = catalog_value.get("database") if isinstance(catalog_value, dict) else None
                catalog_row_count = database.get("row_count") if isinstance(database, dict) else None
                catalog_max_id = database.get("max_transcript_id") if isinstance(database, dict) else None
                database_metadata_bound = (
                    isinstance(catalog_row_count, int)
                    and not isinstance(catalog_row_count, bool)
                    and catalog_row_count == receipt_row_count
                    and catalog_max_id == receipt_max_id
                )
            except (OSError, UnicodeError, ValueError, TypeError):
                database_metadata_bound = False
        data["row_count"] = receipt_row_count if isinstance(receipt_row_count, int) else 0
        if isinstance(receipt_max_id, int):
            data["max_transcript_id"] = receipt_max_id
        data["database_metadata_bound"] = database_metadata_bound
        valid = bool(
            receipt.get("schema_version") == 1
            and receipt.get("status") == "verified"
            and receipt.get("valid") is True
            and receipt.get("remote_catalog_verified") is True
            and _SET_ID_RE.fullmatch(receipt_id)
            and re.fullmatch(r"[0-9a-f]{64}", receipt_hash)
            and receipt_set_present
            and latest_set_matches
            and actual_catalog_sha == receipt_hash
            and database_metadata_bound
        )
        timestamp = receipt.get("verified_at") or receipt.get("observed_at") or receipt.get("created_at")
        age, timestamp_valid = _age_seconds(timestamp, now=current)
        data["verified"] = valid and timestamp_valid
        data["age_seconds"] = age or 0
        data["timestamp_valid"] = timestamp_valid
        if not valid:
            data["reason"] = "backup_unverified"
        elif not timestamp_valid:
            data["reason"] = "timestamp_invalid"
        return data
    # A catalog proves a set was published, not that a scratch restore passed.
    # Keep that distinction explicit and fail closed until a verification
    # receipt is written by the backup operator.
    if catalog_path is not None:
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            timestamp = catalog.get("created_at") if isinstance(catalog, dict) else None
            age, timestamp_valid = _age_seconds(timestamp, now=current)
            data["age_seconds"] = age or 0
            data["timestamp_valid"] = timestamp_valid
        except (OSError, UnicodeError, ValueError, TypeError):
            data["reason"] = "backup_unverified"
    return data


def _default_probe_ingress(config: Any, *, now: datetime | None = None, **_kwargs: Any) -> dict[str, Any]:
    del now
    config_token = getattr(getattr(config, "webhook", None), "ingest_token", "")
    token = _configured_value(config_token)
    token = token or _configured_value(os.environ.get("PENNY_INGEST_TOKEN", ""))
    launchd_keys = _launchd_environment_keys(
        "com.penny.webhook", ("PENNY_INGEST_TOKEN",)
    )
    config_host = getattr(getattr(config, "webhook", None), "host", "")
    host_value = os.environ.get("PENNY_WEBHOOK_HOST", "")
    if not _configured_value(host_value):
        host_value = config_host
    host = str(host_value).strip().lower() if _configured_value(host_value) else ""
    launchd_host = _launchd_environment_value("com.penny.webhook", "PENNY_WEBHOOK_HOST")
    if launchd_host in {"loopback", "non_loopback"}:
        loopback = launchd_host == "loopback"
    else:
        loopback = host in {"127.0.0.1", "::1", "localhost"}
    launchd_protected = _launchd_environment_value(
        "com.penny.webhook", "PENNY_WEBHOOK_ALLOW_NONLOOPBACK"
    )
    protected = (
        os.environ.get("PENNY_WEBHOOK_ALLOW_NONLOOPBACK") == "1"
        or launchd_protected == "enabled"
    )
    callback_configured = _configured_value(os.environ.get("PENNY_WEBHOOK_SECRET", ""))
    callback_configured = callback_configured or bool(
        "PENNY_WEBHOOK_SECRET"
        in _launchd_environment_keys("com.penny.webhook", ("PENNY_WEBHOOK_SECRET",))
    )
    return {
        "secret_configured": bool(token) or "PENNY_INGEST_TOKEN" in launchd_keys,
        "loopback_bind": loopback,
        "protected_bind": protected,
        "callback_secret_configured": callback_configured,
    }


def _infer_status(name: str, data: Mapping[str, Any] | None) -> tuple[str, str]:
    values = data if isinstance(data, Mapping) else {}
    explicit = _safe_state(values.get("state")) if values.get("state") is not None else None
    if explicit is not None:
        if explicit == "unknown":
            return "unknown", _safe_reason(values.get("reason"), "unknown")
        if not _probe_has_required_evidence(name, values):
            return "unknown", "unknown"
        return explicit, _safe_reason(values.get("reason"), "ok")
    if not values:
        return "unknown", "unknown"
    if not _probe_has_required_evidence(name, values):
        return "unknown", "unknown"
    if name == "sqlite":
        if not values.get("query_ok", 0):
            return "unready", _safe_reason(values.get("reason"), "database_unavailable")
        if not values.get("integrity_ok", 0):
            return "unready", "integrity_failure"
        if not values.get("foreign_keys_ok", 0):
            return "unready", "foreign_key_failure"
        if not values.get("schema_ok", 0):
            return "unready", "schema_failure"
        return "ready", "ok"
    if name == "voice_memos":
        if not values.get("query_ok", 1) or values.get("health_error", 0):
            return "unready", "database_unavailable"
        if values.get("timestamp_valid") is not True or int(
            values.get("source_health_age_seconds", 0) or 0
        ) > _DEFAULT_HEALTH_MAX_AGE_SECONDS:
            return "unready", "source_stale"
        if not values.get("voicememos_responsive", False) or not values.get(
            "voice_db_ok", False
        ):
            return "unready", "source_unavailable"
        if int(values.get("terminal_failure_count", 0) or 0) > 0:
            return "unready", "terminal_failure"
        if int(values.get("completion_pending_count", 0) or 0) > 0:
            return "unready", "retryable_failure"
        if int(values.get("failed_count", 0) or 0) > 0:
            return "degraded", "retryable_failure"
        if int(values.get("retry_due_count", 0) or 0) > 0 or int(values.get("awaiting_file_count", 0) or 0) > 0:
            return "degraded", "backlog"
        return "ready", "ok"
    if name == "archive":
        if values.get("health_error", 0):
            return "unready", "database_unavailable"
        if any(int(values.get(key, 0) or 0) > 0 for key in ("failed_count", "invalid_count", "rebuild_needed_count", "archive_backfill_failed_count")):
            return "unready", "probe_error"
        if int(values.get("pending_count", 0) or 0) > 0:
            return "degraded", "backlog"
        return "ready", "ok"
    if name == "transcription":
        if not values.get("offline", 0):
            return "unready", "model_offline_required"
        if not values.get("verified", 0):
            return "unready", "model_unavailable"
        return "ready", "ok"
    if name == "apple_effects":
        if not values.get("query_ok", 1) or values.get("health_error", 0):
            return "unready", "database_unavailable"
        if int(values.get("uncertain_count", 0) or 0) > 0:
            return "unready", "uncertain_effect"
        if int(values.get("failed_count", 0) or 0) > 0:
            return "unready", "provider_failure"
        if int(values.get("migration_quarantine_count", 0) or 0) > 0:
            return "unready", "quarantine"
        if int(values.get("stale_in_flight_count", 0) or 0) > 0:
            return "degraded", "backlog"
        if int(values.get("quarantined_count", 0) or 0) > 0:
            return "degraded", "quarantine"
        return "ready", "ok"
    if name == "maya":
        if values.get("configuration_partial", False):
            return "unready", "configuration_missing"
        if not values.get("configured", False):
            return "degraded", "disabled"
        if not values.get("query_ok", 1) or values.get("health_error", 0):
            return "unready", "database_unavailable"
        if int(values.get("dead_letter_count", 0) or 0) > 0:
            return "degraded", "dead_letter"
        if int(values.get("failed_count", 0) or 0) > 0:
            return "degraded", "provider_failure"
        if int(values.get("pending_count", 0) or 0) > 0:
            return "degraded", "backlog"
        return "ready", "ok"
    if name == "slack":
        if not values.get("configured", False):
            return "unready", "configuration_missing"
        if not values.get("query_ok", 1) or values.get("health_error", 0):
            return "unready", "database_unavailable"
        if int(values.get("failed_count", 0) or 0) + int(values.get("slack_failed_count", 0) or 0) > 0:
            return "unready", "provider_failure"
        if int(values.get("pending_count", 0) or 0) > 0:
            return "degraded", "backlog"
        return "ready", "ok"
    if name == "backup":
        if not values.get("verified", False):
            return "unready", _safe_reason(values.get("reason"), "backup_unverified")
        if values.get("timestamp_valid") is False:
            return "unready", "timestamp_invalid"
        if int(values.get("age_seconds", 0) or 0) > _DEFAULT_BACKUP_MAX_AGE_SECONDS:
            return "unready", "backup_stale"
        return "ready", "ok"
    if name == "services":
        if values.get("timestamp_valid") is False:
            return "unready", "timestamp_invalid"
        if not values.get("voicememos_responsive", False) or not values.get(
            "voice_db_ok", False
        ):
            return "unready", "source_unavailable"
        if not values.get("watcher_ok", False) or not values.get("launchd_ok", False):
            return "unready", "launchd_unavailable"
        if int(values.get("age_seconds", 0) or 0) > _DEFAULT_HEALTH_MAX_AGE_SECONDS:
            return "unready", "health_stale"
        if not values.get("tasks_ok", True):
            return "degraded", "disabled"
        return "ready", "ok"
    if name == "ingress":
        if not values.get("secret_configured", False):
            return "unready", "secret_missing"
        if not values.get("callback_secret_configured", False):
            return "unready", "callback_secret_missing"
        if values.get("loopback_bind", False):
            return "ready", "ok"
        if values.get("protected_bind", False):
            return "degraded", "non_loopback_bind"
        return "unready", "bind_policy"
    return "unknown", "unknown"


_PROBE_NAMES = (
    "sqlite",
    "voice_memos",
    "archive",
    "transcription",
    "apple_effects",
    "maya",
    "slack",
    "backup",
    "services",
    "ingress",
)
_OPTIONAL_COMPONENTS = frozenset({"maya"})


def run_doctor(
    *,
    config: Any | None = None,
    now: datetime | None = None,
    probe_overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> DoctorReport:
    """Run every read-only probe and return a safe report."""

    current = _now(now)
    observed_at = _utc_text(current)
    if config is None and get_config is not None:
        try:
            config = get_config()
        except Exception:
            config = None
    overrides = probe_overrides or {}
    probe_functions: dict[str, Callable[..., dict[str, Any]]] = {
        "sqlite": _default_probe_sqlite,
        "voice_memos": _default_probe_voice_memos,
        "archive": _default_probe_archive,
        "transcription": _default_probe_transcription,
        "apple_effects": _default_probe_apple_effects,
        "maya": _default_probe_maya,
        "slack": _default_probe_slack,
        "backup": _default_probe_backup,
        "services": _default_probe_services,
        "ingress": _default_probe_ingress,
    }
    components: dict[str, ComponentStatus] = {}
    for name in _PROBE_NAMES:
        try:
            data = dict(overrides[name]) if name in overrides else probe_functions[name](config, now=current)
        except Exception:
            data = {"reason": "probe_error"}
        try:
            state, reason = _infer_status(name, data)
        except Exception:
            # Adapters are untrusted boundaries: a malformed counter or
            # provider-shaped value must never escape as a traceback or body.
            state, reason = "unready", "probe_error"
        if state == "unknown" and name not in _OPTIONAL_COMPONENTS:
            state, reason = "unready", "unknown"
        components[name] = ComponentStatus(
            component=name,
            state=state,
            reason=reason,
            details=_safe_details(data),
            observed_at=observed_at,
        )
    states = {status.state for status in components.values()}
    if "unready" in states:
        overall = "unready"
    elif "degraded" in states or "unknown" in states:
        overall = "degraded"
    else:
        overall = "ready"
    return DoctorReport(overall, components, observed_at, _source_revision())


def render_json(report: DoctorReport) -> str:
    return json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":"))


def render_human(report: DoctorReport) -> str:
    lines = [f"Penny Doctor: {report.overall} ({report.observed_at})"]
    for name, component in report.components.items():
        details = " ".join(f"{key}={value}" for key, value in component.details.items())
        lines.append(f"{name}: {component.state} ({component.reason})" + (f" [{details}]" if details else ""))
    return "\n".join(lines)


__all__ = [
    "ComponentStatus",
    "DoctorReport",
    "render_human",
    "render_json",
    "run_doctor",
    "_parse_observed_timestamp",
]
