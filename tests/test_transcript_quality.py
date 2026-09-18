from pathlib import Path
from unittest.mock import Mock

import pytest

from transcript_quality import evaluate_transcript, transcribe_with_quality


def test_repeated_suffix_fails():
    result = evaluate_transcript("A valid memo first. " + "Vous " * 20)

    assert result.passed is False
    assert result.reason == "consecutive_token_repetition"


def test_natural_triplicate_passes():
    result = evaluate_transcript("No no no, I mean the other folder.")

    assert result.passed is True


def test_longer_consecutive_repetition_still_fails():
    result = evaluate_transcript("No no no no, I mean the other folder.")

    assert result.passed is False
    assert result.reason == "consecutive_token_repetition"


@pytest.mark.parametrize("text", ["The the the, use the other folder.", "Vous vous vous."])
def test_non_natural_triplicates_still_fail(text):
    result = evaluate_transcript(text)

    assert result.passed is False
    assert result.reason == "consecutive_token_repetition"


def test_clean_english_passes():
    assert evaluate_transcript(
        "Create one ticket in the repository after checking the API."
    ).passed


def test_low_diversity_suffix_fails():
    result = evaluate_transcript("A valid memo first. " + "alpha beta " * 10)

    assert result.passed is False
    assert result.reason == "low_diversity_suffix"


def test_whisper_control_token_remnant_fails():
    result = evaluate_transcript("Create a ticket <|notimestamps|> after review.")

    assert result.passed is False
    assert result.reason == "control_token"


@pytest.mark.parametrize("text", ["", "   ", "...?! —"])
def test_empty_or_punctuation_only_output_fails(text):
    result = evaluate_transcript(text)

    assert result.passed is False
    assert result.reason == "empty_output"


def test_transcription_retries_once_and_selects_clean_second_result():
    client = Mock()
    client.transcribe.side_effect = [
        {"text": "A valid memo first. " + "Vous " * 20},
        {"text": "Create one ticket in the repository after checking the API."},
    ]
    path = Path("/tmp/penny-test.m4a")

    result = transcribe_with_quality(path, client=client)

    assert result.text == "Create one ticket in the repository after checking the API."
    assert result.quality.passed is True
    assert result.attempts == 2
    assert client.transcribe.call_count == 2
    for invocation in client.transcribe.call_args_list:
        assert invocation.kwargs["language"] == "en"
        assert invocation.kwargs["task"] == "transcribe"
        assert invocation.kwargs["condition_on_previous_text"] is False


def test_transcription_stops_after_two_bad_results_and_needs_review():
    client = Mock()
    client.transcribe.side_effect = [
        {"text": "A valid memo first. " + "Vous " * 20},
        {"text": "<|hr|><|hr|><|hr|>"},
    ]

    result = transcribe_with_quality(
        Path("/tmp/penny-test.m4a"), client=client
    )

    assert result.quality.passed is False
    assert result.quality.reason == "needs_review"
    assert result.quality_detail == (
        "attempt_1=consecutive_token_repetition;attempt_2=control_token"
    )
    assert result.attempts == 2
    assert client.transcribe.call_count == 2
