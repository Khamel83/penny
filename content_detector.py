"""Local content validation for files entering Penny's audio pipeline."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import stat
from typing import Any

try:
    from magika import Magika
except ImportError:  # pragma: no cover - exercised by dependency/readiness checks
    Magika = None  # type: ignore[assignment,misc]


SUPPORTED_AUDIO_LABELS = frozenset(
    {
        "3gp",
        "flac",
        "mkv",
        "mp3",
        "mp4",
        "ogg",
        "qt",
        "wav",
        "webm",
    }
)


@dataclass(frozen=True)
class ContentClassification:
    """Bounded result used by the watcher without retaining file content."""

    status: str
    label: str | None = None
    mime_type: str | None = None
    reason: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status == "supported_audio"

    @property
    def retryable(self) -> bool:
        return self.status == "retryable"


class ContentDetector:
    """One reusable Magika model owner for the watcher process."""

    def __init__(self, engine: Any | None = None) -> None:
        self._engine = engine if engine is not None else (Magika() if Magika else None)

    def classify(self, path: Path) -> ContentClassification:
        """Classify stable file bytes, never trusting the filename extension."""
        try:
            before = self._signature(path)
            if before[0] <= 0:
                return ContentClassification("retryable", reason="file_unavailable")
            if self._engine is None:
                return ContentClassification("retryable", reason="detector_unavailable")
            with path.open("rb") as stream:
                result = self._engine.identify_stream(stream)
            after = self._signature(path)
        except (FileNotFoundError, PermissionError, OSError):
            return ContentClassification("retryable", reason="file_unavailable")
        except Exception:
            return ContentClassification("retryable", reason="classification_failed")

        if before != after:
            return ContentClassification("retryable", reason="source_changed")
        if not getattr(result, "ok", False):
            return ContentClassification("retryable", reason="classification_failed")

        output = getattr(result, "output", None)
        label = str(getattr(output, "label", "") or "").strip().casefold()
        mime_type = str(getattr(output, "mime_type", "") or "").strip().casefold() or None
        group = str(getattr(output, "group", "") or "").strip().casefold()
        if not label or label == "unknown":
            return ContentClassification(
                "unknown", label=label or None, mime_type=mime_type, reason="unknown_type"
            )
        if label in SUPPORTED_AUDIO_LABELS:
            return ContentClassification("supported_audio", label=label, mime_type=mime_type)
        if group == "audio" or (mime_type is not None and mime_type.startswith("audio/")):
            return ContentClassification(
                "unsupported_audio", label=label, mime_type=mime_type, reason="unsupported_audio"
            )
        return ContentClassification(
            "non_audio", label=label, mime_type=mime_type, reason="non_audio"
        )

    @staticmethod
    def _signature(path: Path) -> tuple[int, int, int, int]:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise OSError("not a regular file")
        return info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino
