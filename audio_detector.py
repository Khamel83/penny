"""Local content-based audio detection for Penny capture ingress."""

from __future__ import annotations

from dataclasses import dataclass
import mimetypes
from pathlib import Path
from typing import Any

try:
    from magika import Magika
except ImportError:  # pragma: no cover - production installs Magika from requirements
    Magika = None  # type: ignore[assignment,misc]


SUPPORTED_AUDIO_MIME_TYPES = frozenset(
    {
        "audio/aac",
        "audio/amr",
        "audio/caf",
        "audio/m4a",
        "audio/mpeg",
        "audio/mp4",
        "audio/mp4a-latm",
        "audio/ogg",
        "audio/wav",
        "audio/x-caf",
        "audio/x-m4a",
        "audio/x-wav",
    }
)


@dataclass(frozen=True)
class AudioDetection:
    """Bounded content detector evidence suitable for the canonical ledger."""

    status: str
    label: str
    mime_type: str | None
    reason: str | None = None
    engine: str = "magika"

    @property
    def accepted(self) -> bool:
        return self.status in {"accepted", "unrecognized"}

    def as_dict(self) -> dict[str, str | None]:
        return {
            "status": self.status,
            "label": self.label,
            "mime_type": self.mime_type,
            "reason": self.reason,
            "engine": self.engine,
        }


_MAGIKA = None
if Magika is not None:
    try:
        _MAGIKA = Magika()
    except Exception:  # pragma: no cover - depends on local model/runtime setup
        _MAGIKA = None


def _normalized_mime(value: object) -> str | None:
    candidate = str(value or "").split(";", 1)[0].strip().lower()
    return candidate or None


def _safe_exception_class(exc: BaseException) -> str:
    name = type(exc).__name__
    if name and len(name) <= 48 and name[0].isalpha() and all(
        character.isalnum() or character == "_" for character in name
    ):
        return name
    return "Exception"


def _result_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().lower()


def _classify(label: str, mime_type: str | None, *, engine: str) -> AudioDetection:
    normalized_label = label or "unknown"
    if mime_type in SUPPORTED_AUDIO_MIME_TYPES:
        return AudioDetection("accepted", normalized_label, mime_type, engine=engine)
    if mime_type and mime_type.startswith("audio/"):
        return AudioDetection(
            "rejected",
            normalized_label,
            mime_type,
            reason="unsupported_audio_type",
            engine=engine,
        )
    return AudioDetection(
        "rejected",
        normalized_label,
        mime_type,
        reason="non_audio_content",
        engine=engine,
    )


def _from_magika(path: Path) -> AudioDetection:
    if _MAGIKA is None:
        raise RuntimeError("magika_unavailable")
    result = _MAGIKA.identify_path(path)
    status = _result_value(getattr(result, "status", "ok"))
    if status not in {"", "ok", "success"}:
        return AudioDetection(
            "read_error" if "read" in status or "error" in status else "rejected",
            "unknown",
            None,
            reason=f"detector_{status or 'failed'}",
        )
    output = getattr(result, "output", result)
    label = _result_value(
        getattr(output, "ct_label", getattr(output, "label", "unknown"))
    )
    mime_type = _normalized_mime(getattr(output, "mime_type", None))
    return _classify(label, mime_type, engine="magika")


def _fallback_signature(path: Path, declared_mime: str | None) -> AudioDetection:
    """Keep local tests and degraded installs deterministic without trusting names."""
    with path.open("rb") as handle:
        prefix = handle.read(8192)
    if not prefix:
        return AudioDetection("rejected", "empty", None, reason="empty_input", engine="signature")

    mime_type: str | None = None
    label = "unknown"
    if prefix.startswith(b"RIFF") and prefix[8:12] == b"WAVE":
        label, mime_type = "wav", "audio/wav"
    elif prefix.startswith(b"FORM") and prefix[8:12] in {b"AIFF", b"AIFC"}:
        label, mime_type = "aiff", "audio/aiff"
    elif prefix.startswith(b"fLaC"):
        label, mime_type = "flac", "audio/flac"
    elif prefix.startswith(b"OggS"):
        label, mime_type = "ogg", "audio/ogg"
    elif prefix.startswith(b"#!AMR"):
        label, mime_type = "amr", "audio/amr"
    elif prefix.startswith(b"caff"):
        label, mime_type = "caf", "audio/caf"
    elif prefix.startswith(b"ID3") or (
        len(prefix) >= 2 and prefix[0] == 0xFF and prefix[1] & 0xE0 == 0xE0
    ):
        label, mime_type = "mp3", "audio/mpeg"
    elif len(prefix) >= 2 and prefix[0] == 0xFF and prefix[1] & 0xF6 == 0xF0:
        label, mime_type = "aac", "audio/aac"
    elif len(prefix) >= 12 and prefix[4:8] == b"ftyp":
        label, mime_type = "mp4", "audio/mp4"
    else:
        try:
            text = prefix.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        if text and text.startswith(("not audio", "plain text", "text:")):
            label, mime_type = "text", "text/plain"
    if mime_type is not None:
        return _classify(label, mime_type, engine="signature")
    declared = _normalized_mime(declared_mime)
    if declared in SUPPORTED_AUDIO_MIME_TYPES:
        return AudioDetection(
            "unrecognized",
            "unknown",
            declared,
            reason="signature_unrecognized",
            engine="signature",
        )
    return AudioDetection(
        "rejected",
        "unknown",
        declared,
        reason="content_type_unrecognized",
        engine="signature",
    )


def detect_audio_content(path: Path, *, declared_mime: str | None = None) -> AudioDetection:
    """Detect bytes before staging/transcription, returning only bounded metadata."""
    try:
        if _MAGIKA is not None:
            return _from_magika(Path(path))
        return _fallback_signature(Path(path), declared_mime)
    except (OSError, ValueError) as exc:
        return AudioDetection(
            "read_error",
            "unreadable",
            None,
            reason=f"read_error:{_safe_exception_class(exc)}",
            engine="magika" if _MAGIKA is not None else "signature",
        )
    except Exception as exc:
        return AudioDetection(
            "read_error",
            "unreadable",
            None,
            reason=f"detector_error:{_safe_exception_class(exc)}",
            engine="magika" if _MAGIKA is not None else "signature",
        )


def declared_audio_mime(path: Path) -> str | None:
    return _normalized_mime(mimetypes.guess_type(Path(path).name)[0])
