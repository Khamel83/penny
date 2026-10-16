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


def test_piece_alignment_can_overlap_while_word_starts_remain_ordered():
    result = SimpleNamespace(text="Hello there.", sentences=[SimpleNamespace(
        text="Hello there.", tokens=[
            token(" Hel", 0.0, 0.3), token("lo", 0.2, 0.7),
            token(" there", 0.5, 0.8), token(".", 0.4, 0.9),
        ],
    )])
    words = verbose_result(result, 1.0)["segments"][0]["words"]
    assert words == [
        {"word": "Hello", "start": 0.0, "end": 0.7},
        {"word": "there.", "start": 0.5, "end": 0.9},
    ]


def test_genuinely_backwards_word_starts_still_require_review():
    result = SimpleNamespace(text="Hello there.", sentences=[SimpleNamespace(
        text="Hello there.", tokens=[token(" Hello", 5.5, 5.7), token(" there.", 0.4, 0.9)],
    )])
    with pytest.raises(ValueError, match="backwards_parakeet_token_time"):
        verbose_result(result, 10.0)


@pytest.mark.parametrize("start,previous_start", [(2437.2, 2437.76), (365.52, 365.6)])
def test_sentence_boundary_overlap_is_clamped_not_rejected(start, previous_start):
    """Atlas holds of 2026-10-09: 0.08-0.56 s overlaps between sentences."""
    result = SimpleNamespace(
        text="First sentence. Second sentence.",
        sentences=[
            SimpleNamespace(
                text="First sentence.",
                tokens=[token(" First", previous_start, previous_start + 0.4)],
            ),
            SimpleNamespace(
                text="Second sentence.",
                tokens=[token(" Second", start, start + 0.48)],
            ),
        ],
    )
    output = verbose_result(result, previous_start + 1.0)
    starts = [segment["start"] for segment in output["segments"]]
    assert starts == [previous_start, previous_start]
    second = output["segments"][1]["words"][0]
    assert second["word"] == "Second"
    assert second["start"] == previous_start
    assert second["end"] == max(start + 0.48, previous_start)
    assert second["end"] >= second["start"]


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
                "loop loop loop loop loop loop loop loop",
                [
                    {
                        "start": 0,
                        "end": 1,
                        "text": "loop loop loop loop loop loop loop loop",
                    }
                ],
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


def test_explicit_whisper_cannot_bypass_excerpt_bound(monkeypatch):
    class Supervisor:
        def expire_idle(self):
            pass

        def handle_request(self, *args, **kwargs):
            pytest.fail("long recording admitted")

    monkeypatch.setattr("shared_whisper.retry.audio_duration", lambda path: 14400)
    app = create_app(
        Supervisor(),
        auth_token="secret",
        model_id=PARAKEET_ID,
        model_revision=PARAKEET_REVISION,
        allow_whisper_fallback=True,
    )
    response = app.test_client().post(
        "/v1/audio/transcriptions",
        headers={"Authorization": "Bearer secret", "X-Whisper-Client": "backfill"},
        data={
            "model": WHISPER_MODEL_ID,
            "file": (io.BytesIO(b"audio"), "full-podcast.mp3"),
        },
    )
    assert response.status_code == 502
    assert (
        response.json["error"]["message"] == "quality_review_requires_bounded_excerpt"
    )


def test_parakeet_accepts_restart_but_still_flags_long_loop():
    from transcript_quality import evaluate_transcript

    assert evaluate_transcript(
        "I I I think this is useful.", tolerant_restarts=True
    ).passed
    assert not evaluate_transcript("I I I think this is useful.").passed
    assert not evaluate_transcript("loop " * 8, tolerant_restarts=True).passed


@pytest.mark.parametrize("worker_failure", [None, "backwards_parakeet_token_time", "private /audio transcript"])
def test_long_quality_review_preserves_primary_without_loading_whisper(monkeypatch, tmp_path, worker_failure):
    import json
    from shared_whisper.protocol import WhisperProtocolError
    monkeypatch.setenv("PENNY_ASR_RETRY_DIR", str(tmp_path / "retries"))
    calls = []
    primary = WhisperResult("loop " * 8, [{"start": 300, "end": 305, "text": "loop " * 8}], PARAKEET_ID, PARAKEET_REVISION, "primary")
    class Supervisor:
        def expire_idle(self):
            pass
        def handle_request(self, client, *, audio_path, options):
            calls.append(options)
            assert options.get("_backend") != "whisper"
            if worker_failure is not None:
                raise WhisperProtocolError(worker_failure, code="quality_review")
            return primary
    monkeypatch.setattr("shared_whisper.retry.audio_duration", lambda path: 2001.92)
    app = create_app(Supervisor(), auth_token="secret", model_id=PARAKEET_ID, model_revision=PARAKEET_REVISION, allow_whisper_fallback=True)
    response = app.test_client().post("/v1/audio/transcriptions", headers={"Authorization": "Bearer secret", "X-Whisper-Client": "atlas"}, data={"model": PARAKEET_ID, "file": (io.BytesIO(b"audio"), "episode.mp3")})
    assert response.status_code == 502
    receipts = list((tmp_path / "retries").glob("*/receipt.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt["state"] == "quality_review_requires_bounded_excerpt"
    if worker_failure is None:
        assert receipt["quality_reason"] == "consecutive_token_repetition"
        assert receipt["primary"]["segments"] == primary.segments
    else:
        assert receipt["quality_reason"] == (worker_failure if worker_failure == "backwards_parakeet_token_time" else "parakeet_output_invalid")
        assert receipt["primary"] is None
    assert receipt["fallback"] is None
    assert len(calls) == 1
    assert (receipts[0].parent / "audio.mp3").read_bytes() == b"audio"


def test_long_unbounded_parakeet_repeats_with_word_timing_are_not_held(
    monkeypatch, tmp_path
):
    """A spoken "kayak" run in a 2-hour episode must not hold the episode."""
    monkeypatch.setenv("PENNY_ASR_RETRY_DIR", str(tmp_path / "retries"))
    text = (
        "Kayak asked me to say kayak as many times as possible "
        + "kayak " * 8
        + "search and compare travel"
    )
    words = []
    start = 0.0
    for word in text.split():
        words.append({"word": word, "start": start, "end": start + 0.2})
        start += 0.4
    primary = WhisperResult(
        text,
        [
            {
                "start": words[0]["start"],
                "end": words[-1]["end"],
                "text": text,
                "words": words,
            }
        ],
        PARAKEET_ID,
        PARAKEET_REVISION,
        "primary",
    )

    class Supervisor:
        def expire_idle(self):
            pass

        def handle_request(self, client, *, audio_path, options):
            assert options.get("_backend") != "whisper"
            return primary

    monkeypatch.setattr("shared_whisper.retry.audio_duration", lambda path: 7200.0)
    app = create_app(
        Supervisor(),
        auth_token="secret",
        model_id=PARAKEET_ID,
        model_revision=PARAKEET_REVISION,
        allow_whisper_fallback=True,
    )
    response = app.test_client().post(
        "/v1/audio/transcriptions",
        headers={"Authorization": "Bearer secret", "X-Whisper-Client": "atlas"},
        data={"model": PARAKEET_ID, "file": (io.BytesIO(b"audio"), "episode.mp3")},
    )

    assert response.status_code == 200
    assert response.get_json()["text"] == text
    assert list((tmp_path / "retries").glob("*/receipt.json")) == []


@pytest.mark.parametrize("reason,expected", [
    ("backwards_parakeet_token_time", "backwards_parakeet_token_time"),
    ("invalid_parakeet_token_time", "invalid_parakeet_token_time"),
    ("private transcript /private/audio", "parakeet_output_invalid"),
    ({"private": "payload"}, "Parakeet output needs retry"),
])
def test_worker_pipe_keeps_only_safe_failure_reason(reason, expected):
    import json
    import queue
    from shared_whisper.parakeet_process import ParakeetWorker
    worker = object.__new__(ParakeetWorker)
    worker._results = queue.Queue()
    worker._process = SimpleNamespace(stdout=io.StringIO(json.dumps({"error": reason}) + "\n"))
    worker._read()
    error = worker._results.get_nowait()
    assert error.code == "quality_review"
    assert str(error) == expected
