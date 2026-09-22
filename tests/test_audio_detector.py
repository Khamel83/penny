from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from audio_detector import AudioDetection
from transcript_log import get_transcript_by_hash, init_db
from transcript_quality import QualityResult, TranscriptionResult
import transcript_log
import watcher


def _process(tmp_path: Path, name: str, content: bytes, content_hash: str):
    source = tmp_path / name
    source.write_bytes(content)
    with patch.object(watcher.cfg.archive, "object_root", tmp_path / "objects"), patch.object(
        watcher, "transcribe_with_quality", return_value=TranscriptionResult(
            "accepted transcript", QualityResult(True), 1
        )
    ), patch.object(watcher, "classify_and_route"):
        assert watcher._process_audio_file(source, file_hash=content_hash)
    return get_transcript_by_hash(content_hash)


def test_valid_audio_persists_magika_compatible_detector_record(tmp_path):
    with patch.object(transcript_log, "TRANSCRIPT_DB_PATH", tmp_path / "db.sqlite"), patch.object(
        transcript_log, "_MIGRATION_SOURCES", []
    ):
        init_db()
        row = _process(tmp_path, "memo.m4a", b"RIFF0000WAVEaudio", "valid-audio")

    progress = json.loads(row["routing_progress"])
    assert progress["audio_detector"]["status"] == "accepted"
    assert progress["audio_detector"]["label"] == "wav"
    assert progress["audio_detector"]["mime_type"] == "audio/wav"


def test_renamed_non_audio_is_retained_as_review_record(tmp_path):
    with patch.object(transcript_log, "TRANSCRIPT_DB_PATH", tmp_path / "db.sqlite"), patch.object(
        transcript_log, "_MIGRATION_SOURCES", []
    ):
        init_db()
        row = _process(tmp_path, "renamed.m4a", b"plain text: not audio", "renamed-non-audio")

    assert row["quality_status"] == "needs_review"
    assert row["ingest_state"] == "needs_review"
    assert "detected_label=text" in row["quality_detail"]
    assert "detected_mime=text/plain" in row["quality_detail"]
    assert json.loads(row["routing_progress"])["audio_detector"]["reason"] == "non_audio_content"


def test_unsupported_audio_is_retained_as_review_record(tmp_path):
    with patch.object(transcript_log, "TRANSCRIPT_DB_PATH", tmp_path / "db.sqlite"), patch.object(
        transcript_log, "_MIGRATION_SOURCES", []
    ):
        init_db()
        row = _process(tmp_path, "unsupported.m4a", b"fLaCunsupported", "unsupported-audio")

    assert row["quality_status"] == "needs_review"
    assert "detected_label=flac" in row["quality_detail"]
    assert "detected_mime=audio/flac" in row["quality_detail"]
    assert json.loads(row["routing_progress"])["audio_detector"]["status"] == "rejected"


def test_unreadable_input_retains_bounded_read_error(tmp_path):
    with patch.object(transcript_log, "TRANSCRIPT_DB_PATH", tmp_path / "db.sqlite"), patch.object(
        transcript_log, "_MIGRATION_SOURCES", []
    ):
        init_db()
        source = tmp_path / "unreadable.m4a"
        source.write_bytes(b"audio")
        with patch.object(watcher, "detect_audio_content", return_value=AudioDetection(
            "read_error", "unreadable", None, "read_error:PermissionError"
        )):
            assert watcher._process_audio_file(source, file_hash="unreadable-input")
        row = get_transcript_by_hash("unreadable-input")

    assert row["quality_status"] == "needs_review"
    assert row["error_message"] == "read_error:PermissionError"
    assert "detector_status=read_error" in row["quality_detail"]
    assert "detected_label=unreadable" in row["quality_detail"]
