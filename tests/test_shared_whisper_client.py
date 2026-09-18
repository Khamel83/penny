from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from shared_whisper.client import SharedWhisperClient
from shared_whisper.protocol import WhisperPreempted, WhisperUnavailable


MODEL_ID = "mlx-community/whisper-large-v3-turbo"
REVISION = "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb"


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _success():
    return {
        "text": "hello",
        "segments": [{"start": 0.0, "end": 1.0, "text": "hello"}],
        "model_id": MODEL_ID,
        "model_revision": REVISION,
        "request_id": "request-1",
    }


def test_client_posts_audio_with_caller_identity_and_model_contract(tmp_path: Path):
    audio = tmp_path / "note.m4a"
    audio.write_bytes(b"audio")
    post = Mock(return_value=FakeResponse(200, _success()))
    client = SharedWhisperClient(
        base_url="http://127.0.0.1:10311/v1",
        auth_token="shared-secret",
        model_id=MODEL_ID,
        model_revision=REVISION,
        post=post,
    )

    result = client.transcribe(audio, language="en", task="transcribe")

    assert result.text == "hello"
    request = post.call_args.kwargs
    assert request["headers"]["Authorization"] == "Bearer shared-secret"
    assert request["headers"]["X-Whisper-Client"] == "penny"
    assert request["data"]["model"] == MODEL_ID
    assert request["data"]["language"] == "en"
    assert request["data"]["task"] == "transcribe"
    assert request["timeout"] == 90.0


def test_client_maps_preemption_without_retrying_inside_client(tmp_path: Path):
    audio = tmp_path / "note.m4a"
    audio.write_bytes(b"audio")
    post = Mock(
        return_value=FakeResponse(
            409,
            {"error": {"code": "preempted", "retryable": True}},
        )
    )
    client = SharedWhisperClient(
        base_url="http://127.0.0.1:10311/v1",
        auth_token="shared-secret",
        model_id=MODEL_ID,
        model_revision=REVISION,
        post=post,
    )

    with pytest.raises(WhisperPreempted):
        client.transcribe(audio)

    post.assert_called_once()


def test_client_maps_transport_failure_to_retryable_unavailable(tmp_path: Path):
    audio = tmp_path / "note.m4a"
    audio.write_bytes(b"audio")
    post = Mock(side_effect=requests.Timeout("timed out"))
    client = SharedWhisperClient(
        base_url="http://127.0.0.1:10311/v1",
        auth_token="shared-secret",
        model_id=MODEL_ID,
        model_revision=REVISION,
        post=post,
    )

    with pytest.raises(WhisperUnavailable) as raised:
        client.transcribe(audio)

    assert raised.value.retryable is True
    assert raised.value.code == "unavailable"
