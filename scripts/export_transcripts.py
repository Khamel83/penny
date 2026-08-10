#!/usr/bin/env python3
"""Export transcript history to JSON and rsync to homelab backup."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
log = logging.getLogger(__name__)

TRANSCRIPT_DB = Path("~/.penny/transcripts.db").expanduser()
EXPORT_FILE = Path("~/.penny/transcript_history.json").expanduser()
BACKUP_HOST = "homelab"
BACKUP_DIR = "~/backups/penny/"


def dump_transcripts() -> list[dict]:
    if not TRANSCRIPT_DB.exists():
        log.error("transcript export database unavailable")
        raise RuntimeError("database_unavailable")

    conn = None
    try:
        conn = sqlite3.connect(
            f"file:{TRANSCRIPT_DB.resolve()}?mode=ro", uri=True, timeout=5.0
        )
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT id, content_hash, source, transcript, audio_path,
                      status, routing_result, error_message,
                      created_at, routed_at, routed_to
               FROM transcripts
               ORDER BY id ASC"""
        ).fetchall()
        return [dict(row) for row in rows]
    except (OSError, sqlite3.Error) as e:
        log.error("transcript export database unavailable")
        raise RuntimeError("database_unavailable") from e
    finally:
        if conn:
            conn.close()


def export_json(records: list[dict], destination: Path | None = None) -> Path:
    """Write the human-readable export atomically and return its path."""
    destination = Path(destination or EXPORT_FILE).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(records, indent=2, ensure_ascii=False).encode("utf-8")
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.partial")
    try:
        with temporary.open("wb") as writer:
            writer.write(payload)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, destination)
        with destination.open("rb") as reader:
            os.fsync(reader.fileno())
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
    log.info("exported %d transcript(s)", len(records))
    return destination


def rsync_to_homelab() -> bool:
    try:
        result = subprocess.run(
            [
                "rsync", "-avz",
                "--include", "transcript_history.json",
                "--exclude", "*",
                str(EXPORT_FILE.parent) + "/",
                f"{BACKUP_HOST}:{BACKUP_DIR}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.error("transcript export sync failed")
            return False
        log.info("transcript export synced")
        return True
    except (OSError, subprocess.SubprocessError):
        log.error("transcript export sync failed")
        return False


def main() -> int:
    try:
        records = dump_transcripts()
        export_json(records)
        if not rsync_to_homelab():
            return 1
    except (RuntimeError, OSError, ValueError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
