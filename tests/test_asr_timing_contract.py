"""Real failure shape, with synthetic text and no model loading."""

from types import SimpleNamespace

import pytest

from shared_whisper.protocol import WhisperProtocolError, decode_response
from shared_whisper.worker import build_result
from shared_whisper.parakeet_worker import verbose_result


def payload():
    return dict(
        text="Synthetic text.",
        segments=[
            dict(start=361.88, end=361.82000000000005, text="Synthetic text.", words=[])
        ],
        model_id="fixture",
        model_revision="revision",
        request_id="request",
    )


def test_penny_rejects_saved_whisper_failure_shape_before_acceptance():
    with pytest.raises(WhisperProtocolError) as caught:
        decode_response(200, payload())
    assert caught.value.code == "quality_review"
    assert caught.value.retryable is False
    assert caught.value.timing_context == {
        "segment_index": 0,
        "start": 361.88,
        "end": 361.82000000000005,
    }


def test_worker_cannot_declare_invalid_fallback_success():
    with pytest.raises(WhisperProtocolError) as caught:
        build_result(
            request_id="request",
            response=payload(),
            model_id="fixture",
            model_revision="revision",
        )
    assert caught.value.code == "quality_review"
    assert caught.value.retryable is False


def test_backward_parakeet_failure_retains_numeric_locality_without_text():
    tokens = [
        SimpleNamespace(text=" First", start=120.0, end=120.2),
        SimpleNamespace(text=" second", start=119.8, end=120.4),
    ]
    result = SimpleNamespace(
        text="First second",
        sentences=[SimpleNamespace(text="First second", tokens=tokens)],
    )
    with pytest.raises(ValueError) as caught:
        verbose_result(result, 180.0)
    assert caught.value.timing_context == {
        "sentence_index": 0,
        "token_index": 1,
        "start": 119.8,
        "end": 120.4,
        "previous_start": 120.0,
    }
    assert "First" not in str(caught.value.timing_context)


def test_quality_error_becomes_review_without_retry_or_invented_text(tmp_path):
    from transcript_quality import transcribe_with_quality
    from config import WHISPER_MODEL_ID

    class Client:
        calls = 0
        model_id = WHISPER_MODEL_ID

        def transcribe(self, path, **options):
            self.calls += 1
            raise WhisperProtocolError(
                "invalid time range",
                code="quality_review",
                model_id=WHISPER_MODEL_ID,
                timing_context={"start": 361.88, "end": 361.82},
            )

    client = Client()
    result = transcribe_with_quality(tmp_path / "unused.wav", client=client)
    assert client.calls == 1
    assert result.text == ""
    assert not result.quality.passed
    assert result.model_id == WHISPER_MODEL_ID
    assert "361.88" in result.quality_detail


def test_http_producer_returns_nonretryable_review_for_malformed_result(tmp_path):
    import io
    from shared_whisper.protocol import WhisperResult
    from shared_whisper.server import create_app

    class Supervisor:
        def expire_idle(self):
            return False

        def handle_request(self, *args, **kwargs):
            return WhisperResult(**payload())

    app = create_app(
        Supervisor(), auth_token="fixture-secret", model_id="fixture", temp_dir=tmp_path
    )
    response = app.test_client().post(
        "/v1/audio/transcriptions",
        headers={"Authorization": "Bearer fixture-secret", "X-Whisper-Client": "atlas"},
        data={"file": (io.BytesIO(b"fixture"), "fixture.wav")},
    )
    assert response.status_code == 502
    assert response.json["error"]["code"] == "quality_review"
    assert response.json["error"]["retryable"] is False
    assert response.json["error"]["timing_context"]["start"] == 361.88


def test_error_context_excludes_non_numeric_private_fields():
    error = WhisperProtocolError(
        "quality",
        timing_context={
            "start": 1.0,
            "text": "private",
            "path": "/private",
            "end": float("nan"),
            "token_index": True,
        },
    )
    assert error.timing_context == {"start": 1.0}


def test_quality_wire_preserves_actual_failed_model():
    with pytest.raises(WhisperProtocolError) as caught:
        decode_response(
            502,
            {
                "error": {
                    "code": "quality_review",
                    "retryable": False,
                    "model_id": "actual-fallback",
                    "timing_context": {"start": 42.0},
                }
            },
        )
    assert caught.value.model_id == "actual-fallback"
    assert caught.value.timing_context == {"start": 42.0}


def test_transport_failure_stays_retryable_not_quality_hold(tmp_path):
    from transcript_quality import transcribe_with_quality
    from shared_whisper.protocol import WhisperUnavailable

    class Client:
        def transcribe(self, path, **options):
            raise WhisperUnavailable()

    with pytest.raises(WhisperUnavailable):
        transcribe_with_quality(tmp_path / "unused.wav", client=Client())
