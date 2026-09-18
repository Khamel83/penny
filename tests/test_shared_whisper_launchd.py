import plistlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLIST = ROOT / "launchd" / "com.penny.shared-whisper.plist.template"


def test_shared_whisper_launchd_has_one_named_model_owner():
    values = plistlib.loads(PLIST.read_bytes())
    environment = values["EnvironmentVariables"]
    arguments = values["ProgramArguments"]

    assert values["Label"] == "com.penny.shared-whisper"
    assert arguments[-2:] == ["-m", "shared_whisper.server"]
    assert "agent-cli" not in " ".join(arguments)
    assert environment["HF_HUB_OFFLINE"] == "1"
    assert environment["PENNY_SHARED_WHISPER_PORT"] == "10311"
    assert environment["PENNY_SHARED_WHISPER_IDLE_TTL_SECONDS"] == "300"
    assert environment["PENNY_SHARED_WHISPER_MIN_FREE_PERCENT"] == "12"
    assert environment["PENNY_WHISPER_MODEL_PATH"].endswith(
        "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb"
    )
    assert "YOUR_SHARED_WHISPER_TOKEN_HERE" in environment[
        "PENNY_SHARED_WHISPER_TOKEN"
    ]
