from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("HOME", "/tmp/penny_test_home")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("GOOGLE_CREDENTIALS_FILE", "/tmp/penny_test_home/.penny/google_credentials.json")
os.environ.setdefault("GOOGLE_TOKEN_FILE", "/tmp/penny_test_home/.penny/google_token.json")

import watcher  # noqa: E402


def test_voicememos_sync_is_refreshed_even_when_process_is_running():
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[0] == "osascript":
            return SimpleNamespace(returncode=0, stdout="Voice Memos", stderr="")
        return SimpleNamespace(returncode=0, stdout="411\n", stderr="")

    with patch.object(watcher.subprocess, "run", side_effect=fake_run):
        watcher._voicememos_unresponsive_streak = 0
        watcher._ensure_voicememos_running()

    assert calls == [
        ["pgrep", "-x", "VoiceMemos"],
        ["osascript", "-e", watcher.VOICE_MEMOS_RESPONSIVENESS_SCRIPT],
        ["open", "-g", "-a", "VoiceMemos"],
    ]


def test_voicememos_unresponsive_is_relaunched_after_three_probes():
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[0] == "osascript":
            return SimpleNamespace(returncode=1, stdout="", stderr="timed out")
        return SimpleNamespace(returncode=0, stdout="411\n", stderr="")

    with patch.object(watcher.subprocess, "run", side_effect=fake_run):
        watcher._voicememos_unresponsive_streak = 0
        watcher._ensure_voicememos_running()
        watcher._ensure_voicememos_running()
        watcher._ensure_voicememos_running()

    assert ["pkill", "-TERM", "-x", "VoiceMemos"] in calls
    assert calls[-1] == ["open", "-g", "-a", "VoiceMemos"]


def test_cloud_recording_snapshot_reports_database_and_wal(tmp_path):
    db_path = tmp_path / "CloudRecordings.db"
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE ZCLOUDRECORDING (Z_PK INTEGER, ZDATE REAL)")
    conn.execute("INSERT INTO ZCLOUDRECORDING VALUES (123, 800000000)")
    conn.commit()

    with patch.object(watcher, "CLOUDRECORDINGS_DB", db_path):
        snapshot = watcher._cloud_recording_snapshot()

    conn.close()

    assert snapshot["db_ok"] is True
    assert snapshot["record_count"] == 1
    assert snapshot["latest_pk"] == 123
    assert snapshot["wal_exists"] is True
