"""Wire contract shared by the Penny Whisper supervisor and its clients."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Any, Mapping


# Parakeet emits small word-start overlaps at sentence boundaries (observed
# 0.08-0.56 s). A start inside this window of the previous word start is
# clamped instead of rejected; a larger backward jump is a real timing failure.
WORD_START_OVERLAP_TOLERANCE_SECONDS = 1.0


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
        timing_context: Mapping[str, Any] | None = None,
        model_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.request_id = request_id
        self.timing_context = safe_timing_context(timing_context)
        self.model_id = (
            model_id if isinstance(model_id, str) and 0 < len(model_id) <= 256 else None
        )


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


_TIMING_FIELDS = frozenset(
    {
        "segment_index",
        "word_index",
        "sentence_index",
        "token_index",
        "start",
        "end",
        "previous_start",
    }
)


def safe_timing_context(value: Any) -> dict[str, int | float]:
    """Allow only bounded numeric failure locality, never text or paths."""
    if not isinstance(value, Mapping):
        return {}
    return {
        key: number
        for key, number in value.items()
        if key in _TIMING_FIELDS
        and isinstance(number, (int, float))
        and not isinstance(number, bool)
        and abs(number) <= 1_000_000_000
        and math.isfinite(number)
    }


def validate_segments(segments: list[Any]) -> None:
    """Match the native consumer contract before declaring a response usable."""

    def reject(reason, context):
        raise WhisperProtocolError(
            reason, code="quality_review", timing_context=context
        )

    def time_range(item, context):
        start, end = item.get("start"), item.get("end")
        context = {**context, "start": start, "end": end}
        try:
            valid = all(
                isinstance(v, (int, float))
                and not isinstance(v, bool)
                and math.isfinite(v)
                for v in (start, end)
            )
        except OverflowError:
            valid = False
        if not valid or start < 0 or end < start:
            reject("success response has invalid time range", context)
        return start

    previous = -1.0
    has_text = False
    for index, segment in enumerate(segments):
        context = {"segment_index": index}
        if not isinstance(segment, Mapping) or not isinstance(segment.get("text"), str):
            reject("success response has invalid segment", context)
        start = time_range(segment, context)
        if start < previous - WORD_START_OVERLAP_TOLERANCE_SECONDS:
            reject(
                "success response has backwards segment timestamps",
                {**context, "start": start, "previous_start": previous},
            )
        previous = max(previous, start)
        has_text = has_text or bool(segment["text"].strip())
        words = segment.get("words")
        if words is None:
            words = []
        if not isinstance(words, list):
            reject("success response has invalid words", context)
        previous_word = -1.0
        for word_index, word in enumerate(words):
            word_context = {**context, "word_index": word_index}
            if (
                not isinstance(word, Mapping)
                or not isinstance(word.get("word"), str)
                or not word["word"].strip()
            ):
                reject("success response has invalid word", word_context)
            word_start = time_range(word, word_context)
            if word_start < previous_word - WORD_START_OVERLAP_TOLERANCE_SECONDS:
                reject(
                    "success response has backwards word timestamps",
                    {
                        **word_context,
                        "start": word_start,
                        "previous_start": previous_word,
                    },
                )
            previous_word = max(previous_word, word_start)
    if not has_text:
        reject("success response missing segment text", {})


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
        timing_context=error.get("timing_context"),
        model_id=error.get("model_id"),
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

    try:
        validate_segments(segments)
    except WhisperProtocolError as exc:
        exc.model_id = model_id
        raise

    return WhisperResult(
        text=text,
        segments=segments,
        model_id=model_id,
        model_revision=model_revision,
        request_id=request_id,
    )
