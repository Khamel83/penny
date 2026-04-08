#!/usr/bin/env python3
"""Export transcript history to JSON and rsync to homelab backup."""
from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import sys
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
        log.error("Database not found: %s", TRANSCRIPT_DB)
        sys.exit(1)

    conn = None
    try:
        conn = sqlite3.connect(str(TRANSCRIPT_DB), timeout=5.0)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT id, content_hash, source, transcript, audio_path,
                      status, routing_result, error_message,
                      created_at, routed_at, routed_to
               FROM transcripts
               ORDER BY id ASC"""
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        log.error("Failed to read database: %s", e)
        sys.exit(1)
    finally:
        if conn:
            conn.close()


def export_json(records: list[dict]) -> None:
    EXPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    EXPORT_FILE.write_text(
        json.dumps(records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Exported %d transcripts to %s", len(records), EXPORT_FILE)


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
            log.error("rsync failed: %s", result.stderr)
            return False
        log.info("Synced to %s:%s", BACKUP_HOST, BACKUP_DIR)
        return True
    except Exception as e:
        log.error("rsync error: %s", e)
        return False


def main() -> None:
    records = dump_transcripts()
    log.info("Read %d transcript(s) from database", len(records))
    export_json(records)
    rsync_to_homelab()


if __name__ == "__main__":
    main()
