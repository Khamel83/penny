from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import watcher
from archive import StagedAudio
from content_detector import ContentClassification, DetectionStatus


def test_watcher_rejects_content_before_whisper(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "renamed-photo.m4a"
    source.write_bytes(b"not audio")
    staged = StagedAudio(source, "a" * 64, source.stat().st_size, ".m4a")
    detector = SimpleNamespace(
        classify=Mock(
            return_value=ContentClassification(
                DetectionStatus.NON_AUDIO,
                label="pdf",
                reason="content_group_not_audio",
            )
        )
    )
    transcribe = Mock()
    monkeypatch.setattr(watcher, "stage_audio", lambda *args, **kwargs: staged)
    monkeypatch.setattr(watcher, "get_file_hash", lambda *args, **kwargs: "source-hash")
    monkeypatch.setattr(watcher, "transcribe_with_quality", transcribe)

    processed = watcher._process_audio_file(
        source,
        file_hash="source-hash",
        content_detector=detector,
    )

    assert not processed
    detector.classify.assert_called_once_with(staged.path)
    transcribe.assert_not_called()
