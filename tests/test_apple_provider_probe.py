"""Regressions for live RPC versus durable delivery, errors and private receipts."""

import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

PATH = (
    Path(__file__).resolve().parents[1]
    / ".agents/skills/apple-effects-reliability/scripts/probe_providers.py"
)
spec = importlib.util.spec_from_file_location("apple_provider_probe", PATH)
probe_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe_module)


@pytest.mark.parametrize(
    "returncode,stdout,stderr,expected",
    [
        (0, "2\n", "", "responding"),
        (0, "private account title", "", "invalid_response"),
        (1, "", "private data: not authorized (-1743)", "permission_denied"),
        (1, "", "private data: timed out (-1712)", "appleevent_timeout"),
        (1, "", "arbitrary private provider message", "provider_error"),
    ],
)
def test_probe_distinguishes_failure_without_exposing_content(
    monkeypatch, returncode, stdout, stderr, expected
):
    monkeypatch.setattr(
        probe_module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=returncode, stdout=stdout, stderr=stderr
        ),
    )
    result = probe_module.probe("notes", 12)
    assert result["status"] == expected
    assert "private" not in json.dumps(result)
    assert "accounts" not in json.dumps(result)


def test_subprocess_timeout_is_not_permission_denial(monkeypatch):
    def fail(*a, **k):
        raise subprocess.TimeoutExpired("osascript", 12, stderr="private output")

    monkeypatch.setattr(probe_module.subprocess, "run", fail)
    assert probe_module.probe("reminders", 12)["status"] == "process_timeout"


def test_reachable_provider_does_not_claim_delivery(monkeypatch, capsys):
    monkeypatch.setattr(
        probe_module,
        "probe",
        lambda *a: {"status": "responding", "elapsed_seconds": 0.1},
    )
    assert probe_module.main(["--apps", "notes"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["delivery_verified"] is False
    assert report["repair_performed"] is False
    assert report["caller_context"] == "current_process_only"


def test_private_receipt_cannot_replace_existing_receipt_or_symlink(tmp_path):
    target = tmp_path / "receipt.json"
    probe_module.write_receipt(target, {"status": "responding"})
    before = target.read_bytes()
    assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        probe_module.write_receipt(target, {"status": "changed"})
    link = tmp_path / "symlink.json"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        probe_module.write_receipt(link, {"status": "changed"})
    assert target.read_bytes() == before
