#!/usr/bin/env python3
"""Seed local-only quality-held Penny audio and a bounded historical Atlas corpus."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apple_pilot import PilotStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--penny-db", type=Path, default=Path.home() / ".penny/transcripts.db"
    )
    parser.add_argument(
        "--atlas-audio", type=Path, default=Path("/Volumes/2TB_SSD/atlas-whisper/audio")
    )
    parser.add_argument("--atlas-limit", type=int, default=8)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    candidates = []
    db = sqlite3.connect(args.penny_db.as_uri() + "?mode=ro", uri=True)
    try:
        rows = db.execute("""SELECT id,audio_path,transcript,quality_status FROM transcripts
            WHERE quality_status='needs_review' AND audio_path IS NOT NULL ORDER BY id""").fetchall()
        for row_id, audio, text, quality in rows:
            path = Path(audio)
            if path.is_file():
                candidates.append(
                    (
                        path,
                        "penny_backlog",
                        str(row_id),
                        {"text": text, "quality_status": quality},
                    )
                )
    finally:
        db.close()
    files = sorted(
        (p for p in args.atlas_audio.glob("*.mp3") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    candidates.extend(
        (p, "atlas_backlog", None, None) for p in files[: max(0, args.atlas_limit)]
    )
    report = {
        "mode": "apply" if args.apply else "dry_run",
        "penny_candidates": len(rows),
        "penny_available": sum(c[1] == "penny_backlog" for c in candidates),
        "atlas_historical_candidates": sum(c[1] == "atlas_backlog" for c in candidates),
        "admitted": 0,
        "errors": {},
    }
    if args.apply:
        store = PilotStore(args.root)
        for path, client, ref, baseline in candidates:
            try:
                store.capture(path, client, baseline, ref)
                report["admitted"] += 1
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                code = type(exc).__name__
                report["errors"][code] = report["errors"].get(code, 0) + 1
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
