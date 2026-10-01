from types import SimpleNamespace
import io

import pytest

from config import WHISPER_MODEL_ID, WHISPER_MODEL_REVISION
from shared_whisper.backends import PARAKEET_ID, PARAKEET_REVISION
from shared_whisper.parakeet_worker import verbose_result
from shared_whisper.protocol import ClientKind, WhisperResult
from shared_whisper.server import create_app
from shared_whisper.supervisor import SharedWhisperSupervisor


def token(text, start, end):
    return SimpleNamespace(text=text, start=start, end=end)


def test_wordpieces_retain_word_timing_and_punctuation():
    result = SimpleNamespace(
        text="Hello transcriber.",
        sentences=[
            SimpleNamespace(
                text="Hello transcriber.",
                tokens=[
                    token(" Hello", 0, 0.2),
                    token(" trans", 0.3, 0.4),
                    token("criber", 0.4, 0.6),
                    token(".", 0.6, 0.7),
                ],
            )
        ],
    )
    output = verbose_result(result, 1)
    assert output["segments"][0]["words"] == [
        {"word": "Hello", "start": 0, "end": 0.2},
        {"word": "transcriber.", "start": 0.3, "end": 0.7},
    ]


@pytest.mark.parametrize(
    "start,end", [(float("nan"), 1), (0, float("inf")), (1, 0.5), (0, 2)]
)
def test_bad_token_timestamps_fail_visibly(start, end):
    result = SimpleNamespace(
        text="hello",
        sentences=[SimpleNamespace(text="hello", tokens=[token(" hello", start, end)])],
    )
    with pytest.raises(ValueError):
        verbose_result(result, 1)


class Guard:
    def has_existing_large_owner(self):
        return False

    def pressure_high(self):
        return False


class Worker:
    pid = 999

    def __init__(self, identity):
        self.identity = identity
        self.alive = True

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.alive = False

    def submit(self, request):
        self.request = request

    def poll(self, timeout):
        return WhisperResult(
            "hello",
            [{"start": 0, "end": 1, "text": "hello"}],
            self.identity,
            "revision",
            self.request["request_id"],
        )


def test_backend_switch_requires_previous_process_exit():
    primary = Worker(PARAKEET_ID)
    fallback = Worker(WHISPER_MODEL_ID)

    def create_fallback():
        assert not primary.is_alive()
        return fallback

    supervisor = SharedWhisperSupervisor(
        worker_factory=lambda: primary,
        fallback_worker_factory=create_fallback,
        memory_guard=Guard(),
        model_id=PARAKEET_ID,
        model_revision=PARAKEET_REVISION,
    )
    supervisor.handle_request(ClientKind.PENNY, audio_path="audio", options={})
    assert (
        supervisor.handle_request(
            ClientKind.BACKFILL, audio_path="excerpt", options={"_backend": "whisper"}
        ).model_id
        == WHISPER_MODEL_ID
    )
    assert not primary.is_alive()
    assert supervisor.status()["worker_count"] == 1


def test_stubborn_worker_blocks_second_model():
    primary = Worker(PARAKEET_ID)
    primary.terminate = lambda: None
    supervisor = SharedWhisperSupervisor(
        worker_factory=lambda: primary,
        fallback_worker_factory=lambda: pytest.fail("second model loaded"),
        memory_guard=Guard(),
        model_id=PARAKEET_ID,
        model_revision=PARAKEET_REVISION,
    )
    supervisor.handle_request(ClientKind.PENNY, audio_path="audio", options={})
    with pytest.raises(Exception, match="did not exit"):
        supervisor.handle_request(
            ClientKind.BACKFILL, audio_path="excerpt", options={"_backend": "whisper"}
        )


def test_quality_retry_returns_actual_whisper_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("PENNY_ASR_RETRY_DIR", str(tmp_path / "retries"))
    calls = []

    class Supervisor:
        def expire_idle(self):
            pass

        def handle_request(self, client, *, audio_path, options):
            calls.append(options)
            if options.get("_backend") == "whisper":
                return WhisperResult(
                    "Correct words.",
                    [{"start": 0, "end": 1, "text": "Correct words."}],
                    WHISPER_MODEL_ID,
                    WHISPER_MODEL_REVISION,
                    "fallback",
                )
            return WhisperResult(
                "loop loop loop loop",
                [{"start": 0, "end": 1, "text": "loop loop loop loop"}],
                PARAKEET_ID,
                PARAKEET_REVISION,
                "primary",
            )

    monkeypatch.setattr("shared_whisper.retry.audio_duration", lambda path: 300)
    app = create_app(
        Supervisor(),
        auth_token="secret",
        model_id=PARAKEET_ID,
        model_revision=PARAKEET_REVISION,
        allow_whisper_fallback=True,
    )
    response = app.test_client().post(
        "/v1/audio/transcriptions",
        headers={"Authorization": "Bearer secret", "X-Whisper-Client": "penny"},
        data={"model": PARAKEET_ID, "file": (io.BytesIO(b"audio"), "excerpt.wav")},
    )
    assert response.status_code == 200
    assert response.json["model_id"] == WHISPER_MODEL_ID
    assert len(calls) == 2
    assert calls[1]["_backend"] == "whisper"
