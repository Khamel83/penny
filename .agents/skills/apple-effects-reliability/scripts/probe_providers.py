#!/usr/bin/env python3
"""Bounded read-only Apple provider reachability; no delivery or repair claims."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time

QUERIES = {
    "notes": 'tell application "Notes" to count accounts',
    "reminders": 'tell application "Reminders" to count lists',
    "finder": 'tell application "Finder" to count windows',
}


def probe(app: str, timeout: float) -> dict:
    started = time.monotonic()
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", QUERIES[app]],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            status = (
                "responding"
                if result.stdout.strip().isascii() and result.stdout.strip().isdigit()
                else "invalid_response"
            )
        elif "-1743" in result.stderr:
            status = "permission_denied"
        elif "-1712" in result.stderr:
            status = "appleevent_timeout"
        else:
            status = "provider_error"
    except subprocess.TimeoutExpired:
        status = "process_timeout"
    except OSError:
        status = "runner_unavailable"
    return {"status": status, "elapsed_seconds": round(time.monotonic() - started, 3)}


def write_receipt(path: Path, report: dict) -> None:
    # Refuse overwrite/symlink replacement; keep receipts and credentials separate.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apps", nargs="+", choices=tuple(QUERIES), default=["notes", "reminders"]
    )
    parser.add_argument("--timeout", type=float, default=12)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 30:
        parser.error("--timeout must be greater than 0 and no more than 30 seconds")
    apps = list(dict.fromkeys(args.apps))
    with ThreadPoolExecutor(max_workers=len(apps)) as pool:
        results = dict(zip(apps, pool.map(lambda app: probe(app, args.timeout), apps)))
    responding = sum(value["status"] == "responding" for value in results.values())
    report = {
        "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read_only_provider_reachability",
        "caller_context": "current_process_only",
        "delivery_verified": False,
        "repair_performed": False,
        "providers": results,
    }
    if args.output:
        try:
            write_receipt(args.output, report)
        except OSError:
            print(
                json.dumps(
                    {"status": "receipt_write_failed", "repair_performed": False}
                )
            )
            return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if responding == len(apps) else 1 if responding else 2


if __name__ == "__main__":
    raise SystemExit(main())
