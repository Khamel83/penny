from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from archive import StagedAudio
from historical_transcription import transcribe_historical
from transcript_quality import QualityResult, TranscriptionResult


def test_long_recovery_resumes_chunks_and_keeps_quality_failure(tmp_path, monkeypatch):
    audio = tmp_path / 'original.m4a'
    audio.write_bytes(b'original')
    staged = StagedAudio(audio, 'a' * 64, 8, '.m4a')
    def decode(args, **kwargs):
        Path(args[-1]).write_bytes(b'w' * 100)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr('historical_transcription.subprocess.run', decode)
    transcribe = Mock(side_effect=[
        TranscriptionResult('first', QualityResult(True), 1),
        TranscriptionResult('second', QualityResult(False), 2),
    ])
    result = transcribe_historical(staged, duration_seconds=400, model='local', transcribe=transcribe)
    assert result.text == 'first\nsecond'
    assert not result.quality.passed
    assert audio.read_bytes() == b'original'
    transcribe.reset_mock()
    resumed = transcribe_historical(staged, duration_seconds=400, model='local', transcribe=transcribe)
    assert resumed.text == result.text
    transcribe.assert_not_called()
