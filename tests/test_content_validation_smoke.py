from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import transcript_log

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke_content_validation.py"


def _load_smoke_module():
    name = "content_validation_smoke"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_smoke_records_local_validation_outcomes(monkeypatch, tmp_path):
    db_path = tmp_path / "smoke.db"
    monkeypatch.setattr(transcript_log, "TRANSCRIPT_DB_PATH", db_path)
    transcript_log.init_db()

    smoke = _load_smoke_module()
    results = smoke.run_smoke(tmp_path)
    assert [(item.case, item.outcome) for item in results] == [
        ("valid_audio", "accepted"),
        ("audio_extension_non_audio_bytes", "rejected"),
        ("unsupported_audio", "rejected"),
        ("incomplete_input", "retryable"),
        ("unreadable_input", "retryable"),
    ]
    rows = [transcript_log.get_transcript(item.row_id) for item in results]
    assert all(row is not None for row in rows)
    assert rows[0]["quality_status"] == "passed"
    assert all(row["quality_status"] == "needs_review" for row in rows[1:])
    assert all("content_validation=" in row["quality_detail"] for row in rows)
    assert transcript_log.get_pending_slack_deliveries() == []


def test_smoke_command_is_metadata_only_and_does_not_deliver():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["ledger_rows"] == 5
    assert payload["downstream_delivery"] == "not_attempted"
    assert "synthetic" in payload["detector"]
    assert str(ROOT) not in completed.stdout
