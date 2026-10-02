#!/usr/bin/env python3
"""Inspect or explicitly retry one capped Penny Note; never replay a capture."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import apple_effects
import reminders
import transcript_log
from core import normalize_transcript_text


def snapshot(effect_key: str) -> tuple[dict, str]:
    conn = sqlite3.connect(f"file:{transcript_log.TRANSCRIPT_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM apple_effects WHERE effect_key=?", (effect_key,)).fetchone()
        if row is None:
            raise ValueError("effect_not_found")
        effect = dict(row)
        row = conn.execute(
            "SELECT transcript, quality_status, routing_suppressed FROM transcripts WHERE id=?",
            (effect["transcript_id"],),
        ).fetchone()
        if row is None or row["quality_status"] != "passed" or row["routing_suppressed"]:
            raise ValueError("capture_not_eligible")
        text = normalize_transcript_text(row["transcript"])
        if (effect["effect_type"] != "note" or effect["fallback_target"]
                or effect["state"] != "failed" or effect["last_error_code"] != "attempt_cap"
                or effect["provider_id"] or effect["lease_owner"]):
            raise ValueError("effect_not_capped_note")
        if apple_effects.normalized_payload_sha256(text) != effect["payload_sha256"]:
            raise ValueError("payload_mismatch")
        if apple_effects.effect_key_for(effect["transcript_id"], "note", effect["requested_target"], payload=text) != effect_key:
            raise ValueError("identity_mismatch")
        return effect, text
    finally:
        conn.close()


def exact_folder(folder: str) -> str:
    name = reminders._escape_applescript(folder)
    return reminders._run_osascript(f'''
tell application "Notes"
    set candidates to every folder whose name is "{name}"
    if (count of candidates) is not 1 then error "ambiguous target"
    return id of item 1 of candidates as text
end tell
''').strip()


def verify_content(provider_id: str, folder_id: str, effect_key: str, payload_hash: str) -> None:
    ident = reminders._escape_applescript(provider_id)
    result = reminders._run_osascript(f'''
tell application "Notes"
    set n to note id "{ident}"
    return (id of container of n as text) & linefeed & (plaintext of n as text)
end tell
''')
    actual_folder, _, plain = result.partition("\n")
    marker = reminders._marker(effect_key)
    if actual_folder != folder_id or plain.count(marker) != 1:
        raise ValueError("provider_target_or_marker_mismatch")
    payload = plain.split(marker, 1)[1]
    if apple_effects.normalized_payload_sha256(payload) != payload_hash:
        raise ValueError("provider_payload_mismatch")


def save(directory: Path, name: str, value: dict) -> None:
    fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("effect_key")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-attempts", type=int)
    parser.add_argument("--receipt-dir", type=Path)
    args = parser.parse_args()
    directory = None
    try:
        effect, text = snapshot(args.effect_key)
        folder_id = exact_folder(effect["requested_target"])
        matches = reminders.find_note_by_marker(args.effect_key, effect["requested_target"])
        if len(matches) > 1:
            raise ValueError("marker_conflict")
        if matches:
            verify_content(matches[0], folder_id, args.effect_key, effect["payload_sha256"])
        report = {"effect_key": args.effect_key, "transcript_id": effect["transcript_id"],
                  "attempt_count": effect["attempt_count"], "marker_matches": len(matches),
                  "payload_verified": True, "target_id": folder_id, "applied": False}
        if not args.apply:
            print(json.dumps(report))
            return 0
        if args.expected_attempts != effect["attempt_count"] or args.expected_attempts < transcript_log.APPLE_EFFECT_MAX_ATTEMPTS:
            raise ValueError("expected_attempt_mismatch")
        if args.receipt_dir is None:
            raise ValueError("private_receipt_directory_required")
        # A new directory is mandatory. Re-running an uncertain operation must
        # inspect its existing intent/receipt rather than silently resend.
        candidate = args.receipt_dir.absolute()
        if any(parent.is_symlink() for parent in [candidate, *candidate.parents]):
            raise ValueError("receipt_symlink")
        candidate.mkdir(mode=0o700)
        directory = candidate
        save(directory, "intent.json", {
            "at": datetime.now(timezone.utc).isoformat(), "before": effect,
            "target_id": folder_id, "marker_matches": len(matches),
            "authorization": "explicit operator one-effect repair",
        })
        def verified_matches():
            if exact_folder(effect["requested_target"]) != folder_id:
                raise ValueError("target_changed")
            found = reminders.find_note_by_marker(args.effect_key, effect["requested_target"])
            if len(found) == 1:
                verify_content(found[0], folder_id, args.effect_key, effect["payload_sha256"])
            return found

        receipt = apple_effects._ensure_effect(
            transcript_id=effect["transcript_id"], effect_type="note", text=text,
            requested_target=effect["requested_target"], fallback_target="",
            find=verified_matches,
            create=lambda: reminders.create_note_with_marker(
                args.effect_key, text, effect["requested_target"],
            ),
            operator_retry_at_attempt=args.expected_attempts,
        )
        if receipt.state != "succeeded" or not receipt.provider_id:
            raise ValueError("repair_not_succeeded")
        verify_content(receipt.provider_id, folder_id, args.effect_key, effect["payload_sha256"])
        resumed = transcript_log.resume_route_after_note_repair(args.effect_key)
        report.update({"applied": True, "provider_content_verified": True,
                       "ordinary_route_resumed": resumed, "receipt": asdict(receipt)})
        save(directory, "verified.json", report)
        print(json.dumps({"transcript_id": receipt.transcript_id, "state": receipt.state,
                          "attempt_count": receipt.attempt_count, "provider_content_verified": True}))
        return 0
    except Exception as exc:
        # Never print provider bodies, script text, payload or arbitrary errors.
        if directory is not None and directory.is_dir():
            save(directory, "uncertain.json", {"error_type": type(exc).__name__, "retry_automatically": False})
        print(json.dumps({"state": "not_verified", "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
