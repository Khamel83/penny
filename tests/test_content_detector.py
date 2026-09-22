from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from content_detector import ContentDetector


def _result(label: str, *, group: str, mime_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        ok=True,
        output=SimpleNamespace(label=label, group=group, mime_type=mime_type),
    )


def test_allowlisted_audio_uses_content_label_not_extension(tmp_path: Path) -> None:
    capture = tmp_path / "renamed.txt"
    capture.write_bytes(b"bytes")
    engine = SimpleNamespace(
        identify_stream=lambda stream: _result(
            "mp4", group="video", mime_type="video/mp4"
        )
    )

    result = ContentDetector(engine).classify(capture)

    assert result.status == "supported_audio"
    assert result.label == "mp4"


def test_non_audio_with_audio_extension_is_rejected(tmp_path: Path) -> None:
    capture = tmp_path / "renamed.m4a"
    capture.write_bytes(b"not audio")
    engine = SimpleNamespace(
        identify_stream=lambda stream: _result(
            "pdf", group="document", mime_type="application/pdf"
        )
    )

    result = ContentDetector(engine).classify(capture)

    assert result.status == "non_audio"
    assert result.accepted is False


def test_unsupported_audio_is_rejected(tmp_path: Path) -> None:
    capture = tmp_path / "capture.m4a"
    capture.write_bytes(b"audio")
    engine = SimpleNamespace(
        identify_stream=lambda stream: _result(
            "midi", group="audio", mime_type="audio/midi"
        )
    )

    result = ContentDetector(engine).classify(capture)

    assert result.status == "unsupported_audio"
    assert result.label == "midi"


def test_read_failure_is_retryable(tmp_path: Path) -> None:
    capture = tmp_path / "capture.m4a"
    capture.write_bytes(b"audio")
    engine = SimpleNamespace(
        identify_stream=lambda stream: (_ for _ in ()).throw(OSError("not ready"))
    )

    result = ContentDetector(engine).classify(capture)

    assert result.status == "retryable"
    assert result.retryable is True
