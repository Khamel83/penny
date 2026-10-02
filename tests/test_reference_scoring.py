"""Reference scoring must count real edits and ignore only outer clip padding."""

from scripts.benchmark_apple_references import align, normalize


def test_identical_and_outer_clip_padding():
    s = align(["a", "b", "c"], ["intro", "a", "b", "c", "outro"])
    assert s["error_percent"] == 0
    assert (s["hypothesis_start"], s["hypothesis_end"]) == (1, 4)


def test_substitution_deletion_and_internal_insertion():
    s = align(
        ["start", "red", "mark", "anchor", "lost", "near", "finish", "end"],
        ["start", "blue", "extra", "mark", "anchor", "near", "finish", "end"],
    )
    assert (s["substitutions"], s["deletions"], s["insertions"]) == (1, 1, 1)
    assert s["error_percent"] == 37.5


def test_missing_speech_is_not_hidden_by_padding():
    s = align(["alpha", "beta", "gamma", "delta"], ["alpha", "delta"])
    assert s["deletions"] == 2
    assert s["error_percent"] == 50


def test_contractions_case_and_punctuation_do_not_create_errors():
    assert normalize("I CAN'T; it's here.") == normalize("I can not it is here")


def test_content_score_is_explicitly_different_from_strict():
    assert normalize("I I um know") == ["i", "i", "um", "know"]
    assert normalize("I I um know", True) == ["i", "know"]


def test_number_ordinal_and_compound_formatting():
    assert normalize("Apple II six 1st spacetime BattleBots") == normalize(
        "Apple 2 6 first space time battle bots"
    )


def test_real_technical_substitution_is_not_corrected():
    assert normalize("qubits") != normalize("cubits")
    assert normalize("Bostrom") != normalize("Boston")


def test_completed_campaign_manifest_rejects_changed_inputs_and_binary(tmp_path):
    from scripts.benchmark_apple_references import (
        required_artifacts,
        record_manifest,
        verify_manifest,
    )
    import pytest

    binary = tmp_path / "binary"
    binary.write_bytes(b"original binary")
    for artifact in required_artifacts(tmp_path):
        artifact.write_bytes(b"original artifact")
    record_manifest(tmp_path, binary)
    verify_manifest(tmp_path, binary)
    for name in [
        "musk-clip.wav",
        "musk-reference.txt",
        "musk-apple.json",
        "musk-scope.json",
    ]:
        p = tmp_path / name
        p.write_bytes(b"changed")
        with pytest.raises(RuntimeError, match="recognition_artifact_changed"):
            verify_manifest(tmp_path, binary)
        p.write_bytes(b"original artifact")
    binary.write_bytes(b"changed binary")
    with pytest.raises(RuntimeError, match="recognition_identity_mismatch"):
        verify_manifest(tmp_path, binary)


def test_recognition_never_silently_reuses_partial_results(tmp_path):
    from scripts.benchmark_apple_references import recognize
    import pytest

    (tmp_path / "musk-apple.json").write_text("{}")
    with pytest.raises(RuntimeError, match="existing_recognition_use_verified_score"):
        recognize(tmp_path, tmp_path / "unused-binary")
