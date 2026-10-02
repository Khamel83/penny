from types import SimpleNamespace

import pytest

from scripts import benchmark_parakeet_corpus as benchmark
from scripts.reference_alignment import align


def test_extra_sponsor_words_do_not_hide_reference_content():
    reference = "the model improves rapidly then costs fall".split()
    hypothesis = "the model improves rapidly sponsor advertising buy this then costs fall".split()
    result = align(reference, hypothesis, insertion_cost=0)
    assert result["equal_tokens"] == len(reference)
    assert result["insertions"] == 4


def test_missing_negation_remains_a_reference_error():
    result = align(
        "this does not imply success".split(),
        "this does imply success".split(),
        insertion_cost=0,
    )
    assert result["equal_tokens"] == 4
    assert result["deletions"] == 1
    assert result["changes"][0]["reference"] == "not"


def test_changed_number_remains_a_reference_error():
    result = align(
        "ninety nine percent".split(), "ninety eight percent".split(), insertion_cost=0
    )
    assert result["substitutions"] == 1
    assert result["equal_tokens"] == 2


def test_footprint_requires_both_physical_measurements(monkeypatch):
    monkeypatch.setattr(
        benchmark.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="Physical footprint: 1.5G\n"
        ),
    )
    with pytest.raises(RuntimeError, match="vmmap_missing_measurement"):
        benchmark.footprint()


def test_footprint_failure_cannot_become_zero_memory(monkeypatch):
    monkeypatch.setattr(
        benchmark.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout=""),
    )
    with pytest.raises(RuntimeError, match="vmmap_failed"):
        benchmark.footprint()
