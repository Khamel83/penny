"""Bounded local SpeechAnalyzer throughput probe; no application state writes."""

import argparse
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser()
    p.add_argument("binary", type=Path)
    p.add_argument("audio", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--timeout", type=float, default=180)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    jobs = []
    streams = []
    for i in range(args.jobs):
        out = (args.output / f"job-{i}.json").open("w")
        err = (args.output / f"job-{i}.stderr").open("w")
        streams.extend([out, err])
        jobs.append(
            subprocess.Popen(
                [str(args.binary), str(args.audio)],
                stdout=out,
                stderr=err,
                start_new_session=True,
            )
        )
    samples = []
    footprints = {}
    timed_out = False
    while any(job.poll() is None for job in jobs):
        elapsed = time.perf_counter() - started
        listing = subprocess.run(
            ["ps", "-axo", "pid=,rss=,comm="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        ).stdout
        lines = [
            line.strip()
            for line in listing.splitlines()
            if re.search(r"speech|Speech|aned|aneuser", line)
        ]
        samples.append({"elapsed_seconds": elapsed, "processes": lines})
        if elapsed > 2:
            for line in lines:
                pid = line.split()[0]
                if pid in footprints or "localspeechrecognition" not in line:
                    continue
                result = subprocess.run(
                    ["vmmap", "-summary", pid],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                footprints[pid] = dict(
                    re.findall(
                        r"^(Physical footprint(?: \(peak\))?):\s*(.+)$",
                        result.stdout,
                        re.MULTILINE,
                    )
                )
        if elapsed > args.timeout:
            timed_out = True
            for job in jobs:
                if job.poll() is None:
                    os.killpg(job.pid, signal.SIGKILL)
            break
        time.sleep(0.25)
    for job in jobs:
        job.wait()
    for stream in streams:
        stream.close()
    report = {
        "jobs": args.jobs,
        "wall_seconds": time.perf_counter() - started,
        "exit_codes": [job.returncode for job in jobs],
        "timed_out": timed_out,
        "system_service_footprints_sampled": footprints,
        "samples": samples,
    }
    (args.output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "samples"}), flush=True)


if __name__ == "__main__":
    main()
