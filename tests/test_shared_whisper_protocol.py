import pytest

from shared_whisper.protocol import (
    ClientKind,
    WhisperBusy,
    WhisperPreempted,
    WhisperProtocolError,
    WhisperUnavailable,
    decode_response,
    request_headers,
)


MODEL_ID = "mlx-community/whisper-large-v3-turbo"
REVISION = "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb"


def _success_payload() -> dict:
    return {
        "text": "hello world",
        "segments": [{"start": 0.0, "end": 1.0, "text": "hello world"}],
        "model_id": MODEL_ID,
        "model_revision": REVISION,
        "request_id": "request-1",
    }


def test_decode_success_preserves_transcript_and_model_identity():
    result = decode_response(200, _success_payload())

    assert result.text == "hello world"
    assert result.segments[0]["text"] == "hello world"
    assert result.model_id == MODEL_ID
    assert result.model_revision == REVISION
    assert result.request_id == "request-1"


def test_request_headers_identify_client_without_exposing_model_or_secret():
    assert request_headers(ClientKind.PENNY) == {
        "Accept": "application/json",
        "X-Whisper-Client": "penny",
    }


def test_decode_preempted_raises_retryable_typed_error():
    with pytest.raises(WhisperPreempted) as caught:
        decode_response(
            409,
            {
                "error": {
                    "code": "preempted",
                    "retryable": True,
                    "request_id": "atlas-1",
                }
            },
        )

    assert caught.value.request_id == "atlas-1"
    assert caught.value.retryable is True


@pytest.mark.parametrize(
    ("status", "code", "error_type"),
    [
        (503, "busy", WhisperBusy),
        (503, "unavailable", WhisperUnavailable),
    ],
)
def test_decode_retryable_service_errors(status, code, error_type):
    with pytest.raises(error_type) as caught:
        decode_response(status, {"error": {"code": code, "retryable": True}})

    assert caught.value.retryable is True


def test_decode_rejects_malformed_success_response():
    with pytest.raises(WhisperProtocolError, match="segments"):
        decode_response(200, {"text": "missing metadata"})


def test_decode_rejects_model_identity_mismatch():
    payload = _success_payload()
    payload["model_revision"] = "wrong-revision"

    with pytest.raises(WhisperProtocolError, match="model revision"):
        decode_response(200, payload, expected_revision=REVISION)
