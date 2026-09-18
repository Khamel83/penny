import pytest

from shared_whisper.protocol import (
    ClientKind,
    WhisperBusy,
    WhisperPreempted,
    WhisperResult,
)
from shared_whisper.supervisor import SupervisorState
from shared_whisper.server import create_app


MODEL_ID = "mlx-community/whisper-large-v3-turbo"
REVISION = "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb"


class FakeSupervisor:
    def __init__(self, result=None, error=None):
        self.result = result or WhisperResult(
            text="hello",
            segments=[{"start": 0.0, "end": 1.0, "text": "hello"}],
            model_id=MODEL_ID,
            model_revision=REVISION,
            request_id="request-1",
        )
        self.error = error
        self.calls = []

    def expire_idle(self):
        return False

    def status(self):
        return {
            "state": SupervisorState.IDLE.value,
            "model_id": MODEL_ID,
            "model_revision": REVISION,
            "worker_pid": None,
            "worker_count": 0,
            "active_client": None,
            "preemption_count": 0,
        }

    def handle_request(self, client, *, audio_path, options):
        self.calls.append((client, audio_path, options))
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def app():
    supervisor = FakeSupervisor()
    app = create_app(supervisor, auth_token="shared-secret")
    app.config["TESTING"] = True
    return app, supervisor


def test_health_exposes_sanitized_model_and_worker_status(app):
    flask_app, _ = app

    response = flask_app.test_client().get("/health")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["model_revision"] == REVISION
    assert payload["worker_count"] == 0
    assert "shared-secret" not in str(payload)


def test_transcription_requires_shared_service_authentication(app):
    flask_app, _ = app

    response = flask_app.test_client().post(
        "/v1/audio/transcriptions",
        data={"file": (  # no token on purpose
            __import__("io").BytesIO(b"audio"),
            "note.m4a",
        )},
        content_type="multipart/form-data",
    )

    assert response.status_code == 401


def test_transcription_passes_penny_identity_and_returns_verbose_json(app):
    flask_app, supervisor = app

    response = flask_app.test_client().post(
        "/v1/audio/transcriptions",
        headers={
            "Authorization": "Bearer shared-secret",
            "X-Whisper-Client": "penny",
        },
        data={
            "file": (__import__("io").BytesIO(b"audio"), "note.m4a"),
            "language": "en",
            "condition_on_previous_text": "False",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.get_json()["text"] == "hello"
    assert supervisor.calls[0][0] is ClientKind.PENNY
    assert supervisor.calls[0][2]["language"] == "en"
    assert supervisor.calls[0][2]["condition_on_previous_text"] is False


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (WhisperPreempted(request_id="atlas-1"), 409, "preempted"),
        (WhisperBusy(), 503, "busy"),
    ],
)
def test_transcription_maps_shared_worker_errors(error, status, code):
    supervisor = FakeSupervisor(error=error)
    flask_app = create_app(supervisor, auth_token="shared-secret")
    flask_app.config["TESTING"] = True

    response = flask_app.test_client().post(
        "/v1/audio/transcriptions",
        headers={
            "Authorization": "Bearer shared-secret",
            "X-Whisper-Client": "atlas",
        },
        data={"file": (__import__("io").BytesIO(b"audio"), "note.wav")},
        content_type="multipart/form-data",
    )

    assert response.status_code == status
    assert response.get_json()["error"]["code"] == code
