import os
import plistlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLIST = ROOT / "launchd" / "com.penny.shared-whisper-keeper.plist.template"
HEALTHY = '{"active_client":null,"service":"penny-shared-whisper","state":"idle"}'


def _values():
    return plistlib.loads(PLIST.read_bytes())


def test_keeper_runs_every_two_minutes_without_the_ssd():
    values = _values()
    script = values["ProgramArguments"][2]

    assert values["Label"] == "com.penny.shared-whisper-keeper"
    assert values["ProgramArguments"][:2] == ["/bin/sh", "-c"]
    assert values["StartInterval"] == 120
    assert values["RunAtLoad"] is True
    assert "/Volumes/" not in script
    assert "telegram" not in script.lower()


def _run(tmp_path, *, health_ok):
    """Run the keeper with stub curl/launchctl/logger and a temp marker."""
    stubs = tmp_path / "bin"
    stubs.mkdir(exist_ok=True)
    calls = tmp_path / "calls"
    body = HEALTHY if health_ok else ""
    (stubs / "curl").write_text(
        f"#!/bin/sh\n[ -n '{body}' ] || exit 7\nprintf '%s' '{body}'\n"
    )
    (stubs / "launchctl").write_text(f"#!/bin/sh\necho \"$*\" >> {calls}\n")
    (stubs / "logger").write_text("#!/bin/sh\nexit 0\n")
    for stub in stubs.iterdir():
        stub.chmod(0o755)
    script = (
        _values()["ProgramArguments"][2]
        .replace("/usr/bin/curl", str(stubs / "curl"))
        .replace("/bin/launchctl", str(stubs / "launchctl"))
        .replace("/usr/bin/logger", str(stubs / "logger"))
        .replace("/tmp/penny-shared-whisper-keeper.strike", str(tmp_path / "strike"))
    )
    subprocess.run(["/bin/sh", "-c", script], check=True, env={**os.environ, "HOME": str(tmp_path)})
    return calls.read_text().splitlines() if calls.exists() else []


def test_healthy_server_is_left_alone_and_clears_a_strike(tmp_path):
    (tmp_path / "strike").write_text("")

    assert _run(tmp_path, health_ok=True) == []
    assert not (tmp_path / "strike").exists()


def test_one_failure_only_records_a_strike(tmp_path):
    assert _run(tmp_path, health_ok=False) == []
    assert (tmp_path / "strike").exists()


def test_second_consecutive_failure_kickstarts_the_server(tmp_path):
    _run(tmp_path, health_ok=False)
    calls = _run(tmp_path, health_ok=False)

    assert len(calls) == 1
    assert calls[0].startswith("kickstart -k gui/")
    assert calls[0].endswith("/com.penny.shared-whisper")
    assert not (tmp_path / "strike").exists()
