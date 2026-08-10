from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


def _config(tmp_path: Path, *, token: str = "ingest-secret", host: str = "127.0.0.1"):
    return SimpleNamespace(
        webhook=SimpleNamespace(ingest_token=token, host=host),
        maya=SimpleNamespace(transcript_url="", ingest_token=""),
        archive=SimpleNamespace(object_root=tmp_path / "objects", mirror_root=tmp_path / "mirror"),
        voice_memos=SimpleNamespace(
            whisper_model_path=tmp_path / "model",
            whisper_model_repository="repo",
            whisper_model_revision="revision",
        ),
    )


def _ready_probes(tmp_path: Path):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "sqlite": {"query_ok": 1, "integrity_ok": 1, "foreign_keys_ok": 1, "schema_ok": 1},
        "voice_memos": {"query_ok": 1, "terminal_failure_count": 0, "failed_count": 0, "retry_due_count": 0, "awaiting_file_count": 0, "source_watermark": 4},
        "archive": {"health_error": 0, "failed_count": 0, "invalid_count": 0, "rebuild_needed_count": 0, "pending_count": 0},
        "transcription": {"verified": True, "offline": True},
        "apple_effects": {"query_ok": 1, "uncertain_count": 0, "quarantined_count": 0, "stale_in_flight_count": 0},
        "maya": {"configured": False, "query_ok": 1, "pending_count": 0, "dead_letter_count": 0},
        "slack": {"configured": True, "query_ok": 1, "failed_count": 0, "pending_count": 0},
        "backup": {"verified": True, "age_seconds": 2, "timestamp_valid": True},
        "services": {
            "watcher_ok": True,
            "tasks_ok": True,
            "launchd_ok": True,
            "age_seconds": 2,
            "timestamp_valid": True,
        },
        "ingress": {
            "secret_configured": True,
            "callback_secret_configured": True,
            "loopback_bind": True,
            "protected_bind": False,
        },
    }


def test_doctor_marks_source_terminal_failure_unready(tmp_path: Path):
    from doctor import run_doctor

    probes = _ready_probes(tmp_path)
    probes["voice_memos"] = {**probes["voice_memos"], "terminal_failure_count": 1}
    report = run_doctor(config=_config(tmp_path), probe_overrides=probes)
    assert report.overall == "unready"
    assert report.components["voice_memos"].reason == "terminal_failure"


def test_doctor_separates_liveness_from_readiness(tmp_path: Path):
    from doctor import run_doctor
    from webhook import server

    probes = _ready_probes(tmp_path)
    probes["backup"] = {"verified": False, "age_seconds": 0}
    report = run_doctor(config=_config(tmp_path), probe_overrides=probes)
    assert report.overall == "unready"
    with server.app.test_client() as client:
        # Route-level liveness must not depend on readiness probes.
        assert client.get("/health").status_code == 200


def test_doctor_json_contains_no_secret_or_transcript(tmp_path: Path):
    from doctor import render_json, run_doctor

    probes = _ready_probes(tmp_path)
    probes["voice_memos"] = {**probes["voice_memos"], "secret": "secret-value", "body": "verbatim transcript"}
    report = run_doctor(config=_config(tmp_path), probe_overrides=probes)
    output = render_json(report)
    assert "secret-value" not in output
    assert "verbatim transcript" not in output
    decoded = json.loads(output)
    assert decoded["source_revision"]
    assert decoded["components"]["voice_memos"]["details"]


def test_doctor_rejects_naive_and_future_timestamps(tmp_path: Path):
    from doctor import _parse_observed_timestamp

    assert _parse_observed_timestamp("2026-08-10T10:00:00") is None
    future = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    assert _parse_observed_timestamp(future) is None


def test_required_explicit_unknown_does_not_infer_ready(tmp_path: Path):
    from doctor import run_doctor

    probes = _ready_probes(tmp_path)
    probes["voice_memos"] = {"state": "unknown", "terminal_failure_count": 0}
    report = run_doctor(config=_config(tmp_path), probe_overrides=probes)
    assert report.overall == "unready"
    assert report.components["voice_memos"].state == "unready"
    assert report.components["voice_memos"].reason == "unknown"


def test_slack_configuration_and_apple_failures_are_truthful(tmp_path: Path, monkeypatch):
    from doctor import run_doctor

    monkeypatch.delenv("PENNY_SLACK_BOT_TOKEN", raising=False)
    probes = _ready_probes(tmp_path)
    probes["slack"] = {"configured": False, "query_ok": 1, "pending_count": 0}
    probes["apple_effects"] = {"query_ok": 1, "failed_count": 1, "migration_quarantine_count": 0}
    report = run_doctor(config=_config(tmp_path), probe_overrides=probes)
    assert report.components["slack"].reason == "configuration_missing"
    assert report.components["apple_effects"].reason == "provider_failure"


def test_launchd_secret_presence_probe_keeps_values_out_of_report(monkeypatch):
    import doctor

    monkeypatch.delenv("PENNY_SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setattr(
        doctor.transcript_log,
        "get_slack_delivery_health",
        lambda: {"query_ok": 1, "health_error": 0, "pending_count": 0, "failed_count": 0},
    )
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "Result", (), {"returncode": 0, "stdout": "PENNY_SLACK_BOT_TOKEN = secret-value"}
        )(),
    )
    probe = doctor._default_probe_slack()
    assert probe["configured"] is True
    report = doctor.run_doctor(
        config=_config(Path("/tmp")),
        probe_overrides={name: _ready_probes(Path("/tmp"))[name] for name in _ready_probes(Path("/tmp"))},
    )
    assert "secret-value" not in doctor.render_json(report)


def test_secret_templates_and_empty_environment_values_are_not_configured(monkeypatch):
    import doctor

    monkeypatch.setenv("PENNY_SLACK_BOT_TOKEN", "YOUR_SLACK_BOT_TOKEN_HERE")
    monkeypatch.setenv("PENNY_INGEST_TOKEN", "<set-me>")
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "")
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": (
                    'PENNY_SLACK_BOT_TOKEN = "YOUR_SLACK_BOT_TOKEN_HERE"\n'
                    'PENNY_INGEST_TOKEN = "YOUR_PENNY_INGEST_TOKEN_HERE"\n'
                    'PENNY_WEBHOOK_SECRET = ""\n'
                ),
            },
        )(),
    )
    assert doctor._default_probe_slack()["configured"] is False
    ingress = doctor._default_probe_ingress(
        _config(Path("/tmp"), token="YOUR_PENNY_INGEST_TOKEN_HERE")
    )
    assert ingress["secret_configured"] is False
    assert ingress["callback_secret_configured"] is False


def test_loaded_webhook_environment_controls_bind_and_callback_presence(monkeypatch):
    import doctor

    for key in ("PENNY_INGEST_TOKEN", "PENNY_WEBHOOK_SECRET", "PENNY_WEBHOOK_HOST", "PENNY_WEBHOOK_ALLOW_NONLOOPBACK"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": (
                    "PENNY_INGEST_TOKEN = ingest-value\n"
                    "PENNY_WEBHOOK_SECRET = callback-value\n"
                    "PENNY_WEBHOOK_HOST = 0.0.0.0\n"
                    "PENNY_WEBHOOK_ALLOW_NONLOOPBACK = 1\n"
                ),
            },
        )(),
    )
    ingress = doctor._default_probe_ingress(
        _config(Path("/tmp"), token="YOUR_PENNY_INGEST_TOKEN_HERE")
    )
    assert ingress == {
        "secret_configured": True,
        "callback_secret_configured": True,
        "loopback_bind": False,
        "protected_bind": True,
    }


def test_source_revision_prefers_environment_then_uses_git_fallback(monkeypatch):
    import doctor

    monkeypatch.setenv("PENNY_SOURCE_REVISION", "a" * 40)
    assert doctor._source_revision() == "a" * 40

    monkeypatch.delenv("PENNY_SOURCE_REVISION", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.setattr(doctor, "_STARTUP_SOURCE_REVISION", "b" * 40)
    assert doctor._source_revision() == "b" * 40

    monkeypatch.setattr(doctor, "_STARTUP_SOURCE_REVISION", "unknown")
    assert doctor._source_revision() == "unknown"


def test_startup_source_revision_requires_clean_checkout(monkeypatch):
    import doctor

    dirty_calls: list[list[str]] = []

    def dirty_runner(command, **kwargs):
        dirty_calls.append(command)
        return type("Result", (), {"returncode": 1, "stdout": ""})()

    assert doctor._capture_startup_source_revision(runner=dirty_runner) == "unknown"
    assert dirty_calls and dirty_calls[0][-3:] == ["diff", "--quiet", "HEAD", "--"][-3:]

    clean_results = iter(
        (
            type("Result", (), {"returncode": 0, "stdout": ""})(),
            type("Result", (), {"returncode": 0, "stdout": ""})(),
            type("Result", (), {"returncode": 0, "stdout": "c" * 40 + "\n"})(),
        )
    )
    assert doctor._capture_startup_source_revision(runner=lambda *args, **kwargs: next(clean_results)) == "c" * 40


def test_incomplete_required_probe_evidence_cannot_be_ready(tmp_path: Path):
    from doctor import run_doctor

    probes = _ready_probes(tmp_path)
    probes["backup"] = {"verified": True, "age_seconds": 1}
    probes["services"] = {"watcher_ok": True, "tasks_ok": True, "launchd_ok": True, "age_seconds": 1}
    probes["ingress"] = {
        "secret_configured": True,
        "callback_secret_configured": True,
        "loopback_bind": True,
    }
    report = run_doctor(config=_config(tmp_path), probe_overrides=probes)
    for name in ("backup", "services", "ingress"):
        assert report.components[name].state == "unready"
        assert report.components[name].reason == "unknown"


def test_backup_receipt_hash_and_latest_set_are_bound(tmp_path: Path, monkeypatch):
    from doctor import _default_probe_backup

    root = tmp_path / "backup"
    old_set = root / "sets" / "20260809T120000Z"
    latest_set = root / "sets" / "20260810T120000Z"
    old_set.mkdir(parents=True)
    latest_set.mkdir(parents=True)
    catalog = latest_set / "catalog.json"
    catalog.write_text(
        json.dumps({"database": {"row_count": 1, "max_transcript_id": 1}}),
        encoding="utf-8",
    )
    digest = hashlib.sha256(catalog.read_bytes()).hexdigest()
    receipt = root / "last_verification.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "verified",
                "valid": True,
                "backup_set_id": latest_set.name,
                "catalog_sha256": digest,
                "row_count": 1,
                "max_transcript_id": 1,
                "verified_at": "2026-08-10T12:00:00Z",
                "remote_catalog_verified": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PENNY_BACKUP_ROOT", str(root))
    good = _default_probe_backup(now=datetime(2026, 8, 10, 12, 1, tzinfo=timezone.utc))
    assert good["verified"] is True

    catalog.write_text("catalog-tampered\n", encoding="utf-8")
    tampered = _default_probe_backup(now=datetime(2026, 8, 10, 12, 1, tzinfo=timezone.utc))
    assert tampered["verified"] is False

    receipt_data = json.loads(receipt.read_text(encoding="utf-8"))
    receipt_data["backup_set_id"] = old_set.name
    receipt.write_text(json.dumps(receipt_data), encoding="utf-8")
    mismatched = _default_probe_backup(now=datetime(2026, 8, 10, 12, 1, tzinfo=timezone.utc))
    assert mismatched["verified"] is False


def test_doctor_probes_are_read_only_and_do_not_open_bodies_or_tcc(tmp_path: Path, monkeypatch):
    from doctor import run_doctor

    calls: list[str] = []
    probes = _ready_probes(tmp_path)
    probes["sqlite"] = {"query_ok": 1, "integrity_ok": 1, "foreign_keys_ok": 1, "schema_ok": 1}
    monkeypatch.setattr("doctor._default_probe_sqlite", lambda *a, **k: calls.append("sqlite") or probes["sqlite"])
    monkeypatch.setattr("doctor._default_probe_apple_effects", lambda *a, **k: calls.append("apple") or probes["apple_effects"])
    report = run_doctor(config=_config(tmp_path), probe_overrides=probes)
    assert report.components["sqlite"].state in {"ready", "degraded"}
    # Explicit fixtures replace default probes, so no source/TCC/body adapter
    # is invoked while exercising report rendering.
    assert calls == []


def test_cli_exit_codes_are_ready_degraded_unready(tmp_path: Path, monkeypatch, capsys):
    from doctor import DoctorReport, ComponentStatus
    from scripts import penny_doctor

    now = "2026-08-10T10:00:00Z"
    component = ComponentStatus("services", "ready", "ok", {}, now)
    for state, code in (("ready", 0), ("degraded", 1), ("unready", 2)):
        report = DoctorReport(state, {"services": component}, now, "test")
        monkeypatch.setattr(penny_doctor, "run_doctor", lambda **_: report)
        assert penny_doctor.main(["--json"]) == code
        assert capsys.readouterr().out


def test_cli_exception_fallback_preserves_safe_json_schema(monkeypatch, capsys):
    from scripts import penny_doctor

    monkeypatch.setattr(
        penny_doctor,
        "run_doctor",
        lambda **_: (_ for _ in ()).throw(RuntimeError("secret /private/transcript")),
    )
    assert penny_doctor.main(["--json"]) == 2
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert set(payload) == {"overall", "components", "observed_at", "source_revision"}
    assert payload["overall"] == "unready"
    assert payload["components"] == {}
    assert payload["source_revision"] == "unknown"
    assert payload["observed_at"].endswith("Z")
    parsed = datetime.fromisoformat(payload["observed_at"].replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert "secret /private/transcript" not in output


def test_health_workflow_has_no_mutating_recovery_commands():
    workflow = Path(__file__).parents[1] / ".github/workflows/health-check.yml"
    text = workflow.read_text(encoding="utf-8").lower()
    for forbidden in ("kickstart", "reset", "delete", "replay", "repair", "tail"):
        assert re.search(rf"\\b{forbidden}\\b", text) is None
    assert "open -a" not in text
