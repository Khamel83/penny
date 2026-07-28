import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

from transcript_quality import evaluate_transcript, transcribe_with_quality


def test_repeated_suffix_fails():
    result = evaluate_transcript("A valid memo first. " + "Vous " * 20)

    assert result.passed is False
    assert result.reason == "consecutive_token_repetition"


def test_clean_english_passes():
    assert evaluate_transcript(
        "Create one ticket in the repository after checking the API."
    ).passed


def test_transcription_retries_once_and_selects_clean_second_result(monkeypatch):
    transcribe = Mock(
        side_effect=[
            {"text": "A valid memo first. " + "Vous " * 20},
            {"text": "Create one ticket in the repository after checking the API."},
        ]
    )
    monkeypatch.setitem(sys.modules, "mlx_whisper", SimpleNamespace(transcribe=transcribe))
    path = Path("/tmp/penny-test.m4a")

    result = transcribe_with_quality(path, model="test-model")

    assert result.text == "Create one ticket in the repository after checking the API."
    assert result.quality.passed is True
    assert result.attempts == 2
    assert transcribe.call_count == 2
    for invocation in transcribe.call_args_list:
        assert invocation.kwargs["language"] == "en"
        assert invocation.kwargs["task"] == "transcribe"
        assert invocation.kwargs["condition_on_previous_text"] is False


def test_transcription_stops_after_two_bad_results_and_needs_review(monkeypatch):
    transcribe = Mock(
        side_effect=[
            {"text": "A valid memo first. " + "Vous " * 20},
            {"text": "<|hr|><|hr|><|hr|>"},
        ]
    )
    monkeypatch.setitem(sys.modules, "mlx_whisper", SimpleNamespace(transcribe=transcribe))

    result = transcribe_with_quality(Path("/tmp/penny-test.m4a"), model="test-model")

    assert result.quality.passed is False
    assert result.quality.reason == "needs_review"
    assert result.attempts == 2
    assert transcribe.call_count == 2
