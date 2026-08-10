from __future__ import annotations

import json
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
        "slack": {"query_ok": 1, "failed_count": 0, "pending_count": 0},
        "backup": {"verified": True, "age_seconds": 2},
        "services": {"watcher_ok": True, "tasks_ok": True, "launchd_ok": True, "age_seconds": 2},
        "ingress": {"secret_configured": True, "loopback_bind": True},
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


def test_health_workflow_has_no_mutating_recovery_commands():
    workflow = Path(__file__).parents[1] / ".github/workflows/health-check.yml"
    text = workflow.read_text(encoding="utf-8").lower()
    for forbidden in ("kickstart", "reset", "delete", "replay", "repair", "tail"):
        assert re.search(rf"\\b{forbidden}\\b", text) is None
    assert "open -a" not in text
