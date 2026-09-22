from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from content_detector import (
    DetectionStatus,
    MagikaDetector,
    classify_magika_result,
)


def _result(
    label: str,
    *,
    mime_type: str | None = None,
    group: str | None = None,
    raw_label: str | None = None,
) -> SimpleNamespace:
    output = SimpleNamespace(label=label, mime_type=mime_type, group=group)
    prediction = SimpleNamespace(
        output=output,
        dl=SimpleNamespace(label=raw_label) if raw_label is not None else None,
    )
    return SimpleNamespace(output=output, prediction=prediction)


def test_allowlisted_audio_uses_magika_label_not_suffix(tmp_path: Path) -> None:
    path = tmp_path / "renamed-anything.bin"
    path.write_bytes(b"fixture")
    detector = MagikaDetector(
        SimpleNamespace(
            identify_path=lambda value: _result(
                "mp4", mime_type="audio/mp4", group="media"
            )
        )
    )

    result = detector.classify(path)

    assert result.status is DetectionStatus.ALLOWED_AUDIO
    assert result.format == "m4a"
    assert result.allowed


def test_renamed_non_audio_content_is_rejected() -> None:
    result = classify_magika_result(
        _result("pdf", mime_type="application/pdf", group="document")
    )

    assert result.status is DetectionStatus.NON_AUDIO
    assert not result.allowed


def test_unsupported_audio_is_structured() -> None:
    result = classify_magika_result(
        _result("midi", mime_type="audio/midi", group="audio")
    )

    assert result.status is DetectionStatus.UNSUPPORTED_AUDIO
    assert result.reason == "audio_format_not_allowlisted"
    assert result.label == "midi"


def test_unknown_classification_is_structured() -> None:
    result = classify_magika_result(
        _result("unknown", mime_type="application/octet-stream", group="unknown")
    )

    assert result.status is DetectionStatus.UNKNOWN
    assert result.reason == "unrecognized_content_label"


def test_conflicting_magika_classifications_are_rejected() -> None:
    result = classify_magika_result(
        _result(
            "mp3",
            mime_type="audio/mpeg",
            group="audio",
            raw_label="pdf",
        )
    )

    assert result.status is DetectionStatus.CONFLICT
    assert result.reason == "model_and_output_labels_disagree"
