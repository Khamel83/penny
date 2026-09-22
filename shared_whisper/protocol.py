"""Wire contract shared by the Penny Whisper supervisor and its clients."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class ClientKind(StrEnum):
    """Known callers of the single shared Whisper worker."""

    PENNY = "penny"
    ATLAS = "atlas"
    BACKFILL = "backfill"


@dataclass(frozen=True)
class WhisperResult:
    """Validated successful response from the shared worker."""

    text: str
    segments: list[dict[str, Any]]
    model_id: str
    model_revision: str
    request_id: str


class WhisperProtocolError(RuntimeError):
    """A malformed or unsuccessful shared-Whisper response."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "protocol_error",
        retryable: bool = False,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.request_id = request_id


class WhisperPreempted(WhisperProtocolError):
    """Atlas work was discarded so Penny could use the shared worker."""

    def __init__(self, message: str = "Whisper request preempted", **kwargs: Any):
        super().__init__(message, code="preempted", retryable=True, **kwargs)


class WhisperBusy(WhisperProtocolError):
    """The single shared worker cannot accept another request yet."""

    def __init__(self, message: str = "Whisper worker busy", **kwargs: Any):
        super().__init__(message, code="busy", retryable=True, **kwargs)


class WhisperUnavailable(WhisperProtocolError):
    """The shared worker is unavailable or failed its safety gate."""

    def __init__(self, message: str = "Whisper worker unavailable", **kwargs: Any):
        super().__init__(message, code="unavailable", retryable=True, **kwargs)


def request_headers(client: ClientKind) -> dict[str, str]:
    """Return non-secret headers identifying a request's caller."""

    kind = ClientKind(client)
    return {
        "Accept": "application/json",
        "X-Whisper-Client": kind.value,
    }


def _string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WhisperProtocolError(f"success response missing {key}")
    return value


def _error_from_response(status: int, payload: Any) -> WhisperProtocolError:
    error = payload.get("error") if isinstance(payload, Mapping) else None
    if not isinstance(error, Mapping):
        return WhisperProtocolError(
            f"Whisper returned HTTP {status} without an error object",
            code="http_error",
            retryable=status >= 500,
        )
    code = str(error.get("code") or "http_error")
    retryable = bool(error.get("retryable", status >= 500))
    request_id = error.get("request_id")
    request_id = request_id if isinstance(request_id, str) else None
    message = str(error.get("message") or code)
    error_type = {
        "preempted": WhisperPreempted,
        "busy": WhisperBusy,
        "unavailable": WhisperUnavailable,
    }.get(code)
    if error_type is not None:
        return error_type(message, request_id=request_id)
    return WhisperProtocolError(
        message,
        code=code,
        retryable=retryable,
        request_id=request_id,
    )


def decode_response(
    status: int,
    payload: Any,
    *,
    expected_model_id: str | None = None,
    expected_revision: str | None = None,
) -> WhisperResult:
    """Validate one JSON response and raise typed errors for non-success."""

    if status != 200:
        raise _error_from_response(status, payload)
    if not isinstance(payload, Mapping):
        raise WhisperProtocolError("success response must be an object")

    text = _string(payload, "text")
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise WhisperProtocolError("success response missing segments")
    segments = [segment for segment in raw_segments if isinstance(segment, dict)]
    if len(segments) != len(raw_segments):
        raise WhisperProtocolError("success response contains invalid segments")

    model_id = _string(payload, "model_id")
    model_revision = _string(payload, "model_revision")
    request_id = _string(payload, "request_id")
    if expected_model_id is not None and model_id != expected_model_id:
        raise WhisperProtocolError("Whisper model identity mismatch")
    if expected_revision is not None and model_revision != expected_revision:
        raise WhisperProtocolError("Whisper model revision mismatch")

    return WhisperResult(
        text=text,
        segments=segments,
        model_id=model_id,
        model_revision=model_revision,
        request_id=request_id,
    )
