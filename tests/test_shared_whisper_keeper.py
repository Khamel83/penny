import os
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLIST = ROOT / "launchd" / "com.penny.shared-whisper-keeper.plist.template"
HEALTHY = '{"active_client":null,"service":"penny-shared-whisper","state":"idle"}'


def _values():
    return plistlib.loads(PLIST.read_bytes())


def _state(tmp_path):
    return tmp_path / "private-temp" / "penny-shared-whisper-keeper"


def test_keeper_runs_every_two_minutes_without_the_ssd():
    values = _values()
    script = values["ProgramArguments"][2]

    assert values["Label"] == "com.penny.shared-whisper-keeper"
    assert values["ProgramArguments"][:2] == ["/bin/sh", "-c"]
    assert values["StartInterval"] == 120
    assert values["RunAtLoad"] is True
    assert values["KeepAlive"] is False
    assert values["WorkingDirectory"] == "/"
    assert "/Volumes/" not in script
    assert "telegram" not in script.lower()


def _run(tmp_path, *, health=HEALTHY, kickstart_status=0, bootstrap_status=0):
    """Run the keeper with host calls stubbed and real private state handling."""
    stubs = tmp_path / "bin"
    stubs.mkdir(exist_ok=True)
    temp_root = tmp_path / "private-temp"
    if not temp_root.exists() and not temp_root.is_symlink():
        temp_root.mkdir(mode=0o700)
    calls = tmp_path / "calls"
    logs = tmp_path / "logs"
    health_file = tmp_path / "health"
    health_file.write_text(health or "")
    scripts = {
        "curl": f"cat {shlex.quote(str(health_file))}\nexit {0 if health is not None else 7}",
        "getconf": f"printf '%s\\n' {shlex.quote(str(temp_root))}",
        "launchctl": (
            f"printf '%s\\n' \"$*\" >> {shlex.quote(str(calls))}\n"
            f"[ \"$1\" = kickstart ] && exit {kickstart_status}\n"
            f"exit {bootstrap_status}"
        ),
        "logger": f"printf '%s\\n' \"$*\" >> {shlex.quote(str(logs))}",
        "stat": (
            "/usr/bin/stat -f '%u:%OLp' \"$3\""
            if sys.platform == "darwin"
            else "/usr/bin/stat -c '%u:%a' \"$3\""
        ),
    }
    script = _values()["ProgramArguments"][2]
    for name, body in scripts.items():
        stub = stubs / name
        stub.write_text(f"#!/bin/sh\n{body}\n")
        stub.chmod(0o755)
        executable = f"/bin/{name}" if name == "launchctl" else f"/usr/bin/{name}"
        script = script.replace(executable, shlex.quote(str(stub)))
    result = subprocess.run(
        ["/bin/sh", "-c", script],
        env={**os.environ, "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    return result, calls.read_text().splitlines() if calls.exists() else [], logs.read_text() if logs.exists() else ""


def test_healthy_server_is_left_alone_and_clears_a_strike(tmp_path):
    _run(tmp_path, health=None)
    result, calls, _ = _run(tmp_path)

    assert result.returncode == 0
    assert calls == []
    assert not (_state(tmp_path) / "strike").exists()


@pytest.mark.parametrize("health", [
    '{"service": "penny-shared-whisper", "state": "busy"}',
    '{\n  "service"\n:\n "penny-shared-whisper"\n}',
])
def test_valid_json_whitespace_does_not_restart_a_healthy_server(tmp_path, health):
    _run(tmp_path, health=None)
    result, calls, _ = _run(tmp_path, health=health)

    assert result.returncode == 0
    assert calls == []
    assert not (_state(tmp_path) / "strike").exists()


def test_one_failure_only_records_a_private_strike(tmp_path):
    result, calls, _ = _run(tmp_path, health=None)

    assert result.returncode == 0
    assert calls == []
    assert (_state(tmp_path) / "strike").is_dir()
    assert _state(tmp_path).stat().st_mode & 0o777 == 0o700


def test_second_consecutive_failure_kickstarts_the_server(tmp_path):
    _run(tmp_path, health=None)
    result, calls, logs = _run(tmp_path, health=None)

    assert result.returncode == 0
    assert len(calls) == 1
    assert calls[0].startswith("kickstart -k gui/")
    assert calls[0].endswith("/com.penny.shared-whisper")
    assert "recovery requested" in logs
    assert "restarted" not in logs
    assert not (_state(tmp_path) / "strike").exists()


def test_failed_kickstart_falls_back_to_bootstrap(tmp_path):
    _run(tmp_path, health=None)
    result, calls, logs = _run(tmp_path, health=None, kickstart_status=1)

    assert result.returncode == 0
    assert len(calls) == 2
    assert calls[1].startswith("bootstrap gui/")
    assert "recovery requested" in logs


def test_failed_recovery_returns_failure_and_logs_it(tmp_path):
    _run(tmp_path, health=None)
    result, calls, logs = _run(tmp_path, health=None, kickstart_status=1, bootstrap_status=1)

    assert result.returncode == 1
    assert len(calls) == 2
    assert "recovery failed" in logs
    assert "recovery requested" not in logs


@pytest.mark.parametrize("hostile_path", ["private-temp", "state", "strike"])
def test_symlinks_are_rejected_without_touching_the_target(tmp_path, hostile_path):
    target = tmp_path / "preserved"
    target.write_text("keep these bytes")
    if hostile_path == "private-temp":
        link = tmp_path / "private-temp"
    else:
        (tmp_path / "private-temp").mkdir(mode=0o700)
        if hostile_path == "state":
            link = _state(tmp_path)
        else:
            _state(tmp_path).mkdir(mode=0o700)
            link = _state(tmp_path) / "strike"
    link.symlink_to(target)

    result, calls, _ = _run(tmp_path, health=None)

    assert result.returncode == 1
    assert calls == []
    assert target.read_text() == "keep these bytes"
    assert link.is_symlink()


@pytest.mark.parametrize("hostile_path", ["private-temp", "state"])
def test_shared_writable_state_is_rejected(tmp_path, hostile_path):
    root = tmp_path / "private-temp"
    root.mkdir(mode=0o700)
    target = root
    if hostile_path == "state":
        target = _state(tmp_path)
        target.mkdir(mode=0o700)
    target.chmod(0o777)

    result, calls, _ = _run(tmp_path, health=None)

    assert result.returncode == 1
    assert calls == []


@pytest.mark.parametrize("health", [
    '{"service": "another-service"}',
    '{"service": "penny- shared-whisper"}',
])
def test_wrong_service_is_a_failed_probe(tmp_path, health):
    _run(tmp_path, health=health)
    result, calls, _ = _run(tmp_path, health=health)

    assert result.returncode == 0
    assert len(calls) == 1
    assert calls[0].startswith("kickstart -k gui/")
