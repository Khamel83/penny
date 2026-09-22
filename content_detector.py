"""Local content classification for completed Penny audio files."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class DetectionStatus(str, Enum):
    """Bounded outcomes exposed to the watcher and review paths."""

    ALLOWED_AUDIO = "allowed_audio"
    UNSUPPORTED_AUDIO = "unsupported_audio"
    NON_AUDIO = "non_audio"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


# These are Magika's stable content labels, not filename extensions.  ``mp4``
# is the container label Magika returns for Voice Memos' MPEG-4 audio files;
# Penny retains the input's .m4a extension for archive compatibility.
MAGIKA_AUDIO_FORMATS: dict[str, str] = {
    "flac": "flac",
    "mp3": "mp3",
    "mp4": "m4a",
    "ogg": "ogg",
    "wav": "wav",
}

_AUDIO_MIME_TYPES = frozenset(
    {
        "audio/flac",
        "audio/mpeg",
        "audio/mp4",
        "audio/ogg",
        "audio/wav",
        "audio/x-flac",
        "audio/x-wav",
    }
)


@dataclass(frozen=True)
class ContentClassification:
    """A bounded, non-sensitive result from classifying one completed file."""

    status: DetectionStatus
    label: str | None = None
    format: str | None = None
    mime_type: str | None = None
    group: str | None = None
    reason: str | None = None

    @property
    def allowed(self) -> bool:
        return self.status is DetectionStatus.ALLOWED_AUDIO

    @property
    def is_allowed(self) -> bool:
        """Compatibility alias for callers that prefer predicate wording."""
        return self.allowed


class MagikaDetector:
    """Reuse one initialized Magika engine for the lifetime of a watcher."""

    def __init__(self, engine: Any | None = None) -> None:
        if engine is None:
            try:
                from magika import Magika

                engine = Magika()
            except Exception:
                engine = None
        self._engine = engine

    @property
    def available(self) -> bool:
        return self._engine is not None

    def classify(self, path: Path) -> ContentClassification:
        """Classify a completed file without consulting its filename suffix."""
        if self._engine is None:
            return ContentClassification(
                DetectionStatus.UNKNOWN,
                reason="detector_unavailable",
            )

        try:
            result = self._engine.identify_path(str(path))
        except Exception as exc:
            return ContentClassification(
                DetectionStatus.UNKNOWN,
                reason=f"detector_error:{type(exc).__name__}",
            )
        return classify_magika_result(result)


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _prediction_output(result: Any) -> tuple[Any, Any]:
    """Return Magika's final output and raw model output, if available."""
    prediction = _field(result, "prediction")
    output = _field(result, "output") or _field(prediction, "output")
    raw = _field(result, "dl") or _field(prediction, "dl")
    return output, raw


def _normalized(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().casefold()
    return value or None


def classify_magika_result(result: Any) -> ContentClassification:
    """Map a Magika result to Penny's explicit transcription allowlist."""
    output, raw = _prediction_output(result)
    label = _normalized(_field(output, "label"))
    raw_label = _normalized(_field(raw, "label"))
    mime_type = _normalized(_field(output, "mime_type"))
    group = _normalized(_field(output, "group"))

    if label is None:
        return ContentClassification(
            DetectionStatus.UNKNOWN,
            mime_type=mime_type,
            group=group,
            reason="missing_label",
        )
    if raw_label is not None and raw_label != label:
        return ContentClassification(
            DetectionStatus.CONFLICT,
            label=label,
            mime_type=mime_type,
            group=group,
            reason="model_and_output_labels_disagree",
        )

    if label == "unknown":
        return ContentClassification(
            DetectionStatus.UNKNOWN,
            label=label,
            mime_type=mime_type,
            group=group,
            reason="unrecognized_content_label",
        )

    audio_mime = mime_type in _AUDIO_MIME_TYPES or (
        mime_type is not None and mime_type.startswith("audio/")
    )
    known_audio = label in MAGIKA_AUDIO_FORMATS
    if known_audio and (
        (mime_type is not None and mime_type.startswith("video/"))
        or group in {"video", "image", "document", "text"}
    ):
        return ContentClassification(
            DetectionStatus.CONFLICT,
            label=label,
            mime_type=mime_type,
            group=group,
            reason="audio_label_conflicts_with_metadata",
        )
    if group == "audio" and not known_audio:
        return ContentClassification(
            DetectionStatus.UNSUPPORTED_AUDIO,
            label=label,
            mime_type=mime_type,
            group=group,
            reason="audio_format_not_allowlisted",
        )
    if audio_mime and not known_audio:
        return ContentClassification(
            DetectionStatus.UNSUPPORTED_AUDIO,
            label=label,
            mime_type=mime_type,
            group=group,
            reason="audio_format_not_allowlisted",
        )
    if known_audio:
        return ContentClassification(
            DetectionStatus.ALLOWED_AUDIO,
            label=label,
            format=MAGIKA_AUDIO_FORMATS[label],
            mime_type=mime_type,
            group=group,
        )
    if group is None:
        return ContentClassification(
            DetectionStatus.UNKNOWN,
            label=label,
            mime_type=mime_type,
            group=group,
            reason="missing_group",
        )
    return ContentClassification(
        DetectionStatus.NON_AUDIO,
        label=label,
        mime_type=mime_type,
        group=group,
        reason="content_group_not_audio",
    )
