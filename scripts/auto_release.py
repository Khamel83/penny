#!/usr/bin/env python3
"""Unattended Penny release on merge.

Fetches origin/main, compares the changed paths between the last processed
revision and origin/main (paths, not commit counts), and runs
scripts/deploy_penny.py exactly once when a release path changed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = Path(os.environ.get("PENNY_AUTO_RELEASE_STATE",
                                Path.home() / ".penny" / "auto_release_state.json"))
STATUS_PATH = Path(os.environ.get("PENNY_AUTO_RELEASE_STATUS",
                                 Path.home() / ".penny" / "auto_release_status.json"))


def is_release_path(path: str) -> bool:
    path = path.strip()
    if not path:
        return False
    if path.startswith("docs/"):
        return False
    if path.endswith(".md"):
        return False
    if path.startswith("tests/"):
        return False
    return True


def run(args, *, cwd=ROOT, check=False):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result


def current_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def write_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def write_status(status):
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run(["git", "fetch", "origin"], check=True)
    new_sha = run(["git", "rev-parse", "origin/main"], check=True).stdout.strip()

    state = current_state()
    last_sha = state.get("last_sha")

    if last_sha == new_sha:
        write_status({"status": "current", "sha": new_sha})
        print(f"auto_release: current {new_sha}")
        return 0

    if last_sha:
        diff = run(["git", "diff", "--name-only", f"{last_sha}..{new_sha}"])
        changed = diff.stdout.splitlines()
    else:
        changed = []

    release_changed = [p for p in changed if is_release_path(p)]

    if not release_changed:
        write_state({"last_sha": new_sha, "released": False})
        write_status({"status": "no_release_paths", "sha": new_sha,
                      "changed": changed})
        print(f"auto_release: no release paths in {new_sha}")
        return 0

    if args.dry_run:
        print("auto_release: would release", new_sha, release_changed)
        return 0

    # Try once per commit.
    attempt_key = f"attempted:{new_sha}"
    if state.get(attempt_key):
        write_status({"status": "already_attempted", "sha": new_sha})
        print(f"auto_release: already attempted {new_sha}")
        return 1
    state[attempt_key] = True
    write_state(state)

    deploy = run([sys.executable, str(ROOT / "scripts" / "deploy_penny.py"), "--apply"])
    status = {
        "sha": new_sha,
        "changed": release_changed,
        "returncode": deploy.returncode,
        "stdout": deploy.stdout.strip(),
        "stderr": deploy.stderr.strip(),
    }
    if deploy.returncode == 0:
        state["last_sha"] = new_sha
        state["released"] = True
        write_state(state)
        status["status"] = "released"
        write_status(status)
        print(f"auto_release: released {new_sha}")
        return 0
    status["status"] = "failed"
    write_status(status)
    print(f"auto_release: FAILED {new_sha}\n{deploy.stderr}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
