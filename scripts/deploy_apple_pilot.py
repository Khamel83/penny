#!/usr/bin/env python3
"""Deploy the opt-in Apple shadow worker and capture hook from pushed main."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apple_pilot import PilotStore, file_hash, private_json, run_bounded, volume_uuid
from scripts import deploy_penny

LABEL = "com.penny.apple-pilot"
PILOT_ROOT = Path("/Volumes/2TB_SSD/penny-apple-pilot")


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({"runtime": deploy_penny.runtime(LABEL)}))
        return 0
    sha = deploy_penny.pushed_revision()
    volume = PILOT_ROOT.parent
    if not volume.is_mount():
        raise RuntimeError("pilot_volume_not_mounted")
    uuid = volume_uuid(volume)
    os.environ["PENNY_APPLE_PILOT_VOLUME_UUID"] = uuid
    store = PilotStore(PILOT_ROOT)
    receipt_dir = (
        Path.home()
        / ".penny/deployments"
        / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-apple-pilot")
    )
    receipt_dir.mkdir(parents=True, mode=0o700)
    deploy_penny.backup_before_deploy()
    binary_dir = Path.home() / ".penny/bin"
    binary_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    binary = binary_dir / ("apple-transcribe-" + sha)
    binary_receipt = binary.with_suffix(".json")
    if binary.exists():
        identity = json.loads(binary_receipt.read_text())
        if identity != {
            "revision": sha,
            "source_sha256": file_hash(ROOT / "native/apple_transcribe.swift"),
            "binary_sha256": file_hash(binary),
        }:
            raise RuntimeError("pilot_binary_identity_mismatch")
    else:
        run_bounded(
            [
                "xcrun",
                "swiftc",
                "-parse-as-library",
                "-O",
                "-framework",
                "Speech",
                "-framework",
                "AVFoundation",
                str(ROOT / "native/apple_transcribe.swift"),
                "-o",
                str(binary),
            ],
            120,
        )
        os.chmod(binary, 0o700)
        private_json(
            binary_receipt,
            {
                "revision": sha,
                "source_sha256": file_hash(ROOT / "native/apple_transcribe.swift"),
                "binary_sha256": file_hash(binary),
            },
        )
    run_bounded([str(binary), "--install-assets"], 300)
    probe = json.loads(run_bounded([str(binary), "--probe"], 30))
    if probe.get("asset_status") != "installed":
        raise RuntimeError("pilot_assets_unverified")
    plist_path = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
    if plist_path.exists():
        existing = plistlib.loads(plist_path.read_bytes())
        if (
            existing.get("WorkingDirectory") != str(ROOT)
            or existing.get("Label") != LABEL
        ):
            raise RuntimeError("pilot_existing_owner_mismatch")
        shutil.copy2(plist_path, receipt_dir / plist_path.name)
        if deploy_penny.runtime(LABEL)["loaded"]:
            run_bounded(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], 30)
    data = {
        "Label": LABEL,
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProgramArguments": [
            str(ROOT / "venv/bin/python"),
            "-m",
            "apple_pilot",
            "--root",
            str(PILOT_ROOT),
            "--binary",
            str(binary),
        ],
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/bin:/bin",
            "HF_HUB_OFFLINE": "1",
            "PENNY_SOURCE_REVISION": sha,
            "PENNY_APPLE_PILOT_VOLUME_UUID": uuid,
        },
        "StandardOutPath": str(Path.home() / ".penny/logs/apple-pilot.system.log"),
        "StandardErrorPath": str(Path.home() / ".penny/logs/apple-pilot.system.log"),
        "ThrottleInterval": 30,
    }
    plist_path.write_bytes(plistlib.dumps(data))
    os.chmod(plist_path, 0o600)
    run_bounded(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path)], 30)
    # Enable capture on the existing owner. Its credentials and paths are preserved.
    shared_path, shared = deploy_penny.installed("com.penny.shared-whisper")
    shutil.copy2(shared_path, receipt_dir / shared_path.name)
    shared["EnvironmentVariables"]["PENNY_APPLE_PILOT_DIR"] = str(PILOT_ROOT)
    shared["EnvironmentVariables"]["PENNY_APPLE_PILOT_VOLUME_UUID"] = uuid
    temporary = shared_path.with_suffix(".pilot-new")
    temporary.write_bytes(plistlib.dumps(shared))
    os.chmod(temporary, 0o600)
    os.replace(temporary, shared_path)
    # Existing deploy command performs trust/backup checks and avoids active ASR restart.
    run_bounded(
        [
            str(ROOT / "venv/bin/python"),
            str(ROOT / "scripts/deploy_penny.py"),
            "--apply",
        ],
        600,
    )
    runtime = deploy_penny.runtime(LABEL)
    for _ in range(40):
        try:
            health = json.loads((PILOT_ROOT / "health.json").read_text())
            if (
                health.get("source_revision") == sha
                and time.time() - health["observed_at"] < 10
            ):
                break
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    else:
        raise RuntimeError("pilot_freshness_unverified")
    with urlopen("http://127.0.0.1:10311/health", timeout=10) as response:
        shared_health = json.load(response)
    if (
        not runtime["loaded"]
        or runtime["revision"] != sha
        or health.get("source_revision") != sha
        or not shared_health.get("apple_pilot_enabled")
    ):
        raise RuntimeError("pilot_runtime_unverified")
    receipt = {
        "revision": sha,
        "runtime": runtime,
        "probe": probe,
        "queue": store.status(),
        "mode": "shadow",
        "canonical_backend": "shared-mlx-whisper",
    }
    private_json(receipt_dir / "receipt.json", receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "failed", "error_class": type(exc).__name__}))
        raise SystemExit(2) from None
