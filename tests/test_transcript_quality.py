import sys
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from config import WHISPER_MODEL_REPOSITORY, WHISPER_MODEL_REVISION
from transcript_quality import evaluate_transcript, transcribe_with_quality


def _verified_model(tmp_path: Path) -> Path:
    model = tmp_path / "models" / WHISPER_MODEL_REVISION
    model.mkdir(parents=True)
    config = model / "config.json"
    weights = model / "weights.npz"
    config.write_text(json.dumps({"model_type": "whisper"}), encoding="utf-8")
    weights.write_bytes(b"test weights")
    os.chmod(config, 0o400)
    os.chmod(weights, 0o400)
    files = []
    for path in (config, weights):
        files.append(
            {
                "path": path.name,
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    (model / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repository": WHISPER_MODEL_REPOSITORY,
                "revision": WHISPER_MODEL_REVISION,
                "config_path": "config.json",
                "weights_path": "weights.npz",
                "files": files,
            }
        ),
        encoding="utf-8",
    )
    os.chmod(model / "manifest.json", 0o400)
    os.chmod(model, 0o700)
    (model / ".penny-committed").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repository": WHISPER_MODEL_REPOSITORY,
                "revision": WHISPER_MODEL_REVISION,
                "manifest_sha256": hashlib.sha256(
                    (model / "manifest.json").read_bytes()
                ).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    os.chmod(model / ".penny-committed", 0o400)
    return model


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


def test_transcription_retries_once_and_selects_clean_second_result(monkeypatch, tmp_path):
    transcribe = Mock(
        side_effect=[
            {"text": "A valid memo first. " + "Vous " * 20},
            {"text": "Create one ticket in the repository after checking the API."},
        ]
    )
    monkeypatch.setitem(sys.modules, "mlx_whisper", SimpleNamespace(transcribe=transcribe))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    path = Path("/tmp/penny-test.m4a")

    result = transcribe_with_quality(path, model=str(_verified_model(tmp_path)))

    assert result.text == "Create one ticket in the repository after checking the API."
    assert result.quality.passed is True
    assert result.attempts == 2
    assert transcribe.call_count == 2
    for invocation in transcribe.call_args_list:
        assert invocation.kwargs["language"] == "en"
        assert invocation.kwargs["task"] == "transcribe"
        assert invocation.kwargs["condition_on_previous_text"] is False


def test_transcription_stops_after_two_bad_results_and_needs_review(monkeypatch, tmp_path):
    transcribe = Mock(
        side_effect=[
            {"text": "A valid memo first. " + "Vous " * 20},
            {"text": "<|hr|><|hr|><|hr|>"},
        ]
    )
    monkeypatch.setitem(sys.modules, "mlx_whisper", SimpleNamespace(transcribe=transcribe))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")

    result = transcribe_with_quality(
        Path("/tmp/penny-test.m4a"), model=str(_verified_model(tmp_path))
    )

    assert result.quality.passed is False
    assert result.quality.reason == "needs_review"
    assert result.quality_detail == (
        "attempt_1=consecutive_token_repetition;attempt_2=control_token"
    )
    assert result.attempts == 2
    assert transcribe.call_count == 2
