"""Shared Whisper client and supervisor primitives."""

from .protocol import (
    ClientKind,
    WhisperBusy,
    WhisperPreempted,
    WhisperProtocolError,
    WhisperUnavailable,
    WhisperResult,
    decode_response,
    request_headers,
)

__all__ = [
    "ClientKind",
    "WhisperBusy",
    "WhisperPreempted",
    "WhisperProtocolError",
    "WhisperUnavailable",
    "WhisperResult",
    "decode_response",
    "request_headers",
]
