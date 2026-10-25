import logging
import queue
import threading
import time

import pytest

from shared_whisper.protocol import (
    ClientKind,
    WhisperBusy,
    WhisperPreempted,
    WhisperResult,
    WhisperUnavailable,
)
from shared_whisper.supervisor import SharedWhisperSupervisor, SupervisorState


MODEL_ID = "mlx-community/whisper-large-v3-turbo"
REVISION = "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb"


def _result(request_id: str) -> WhisperResult:
    return WhisperResult(
        text=request_id,
        segments=[{"start": 0.0, "end": 1.0, "text": request_id}],
        model_id=MODEL_ID,
        model_revision=REVISION,
        request_id=request_id,
    )


class FakeWorker:
    _next_pid = 5000

    def __init__(self):
        self.pid = FakeWorker._next_pid
        FakeWorker._next_pid += 1
        self.alive = True
        self.submitted: list[dict] = []
        self.results: queue.Queue = queue.Queue()
        self.terminated = threading.Event()

    def submit(self, request: dict) -> None:
        self.submitted.append(request)

    def poll(self, timeout: float):
        try:
            return self.results.get(timeout=timeout)
        except queue.Empty:
            return None

    def complete(self, result: WhisperResult) -> None:
        self.results.put(result)

    def terminate(self) -> None:
        self.alive = False
        self.terminated.set()

    def is_alive(self) -> bool:
        return self.alive


class FakeFactory:
    def __init__(self):
        self.workers: list[FakeWorker] = []

    def __call__(self) -> FakeWorker:
        worker = FakeWorker()
        self.workers.append(worker)
        return worker


class StaticMemoryGuard:
    def __init__(self, *, existing=False, pressure=False):
        self.existing = existing
        self.pressure = pressure

    def has_existing_large_owner(self) -> bool:
        return self.existing

    def pressure_high(self) -> bool:
        return self.pressure


def _supervisor(factory, *, grace_seconds=0.2, guard=None, clock=None):
    return SharedWhisperSupervisor(
        worker_factory=factory,
        memory_guard=guard or StaticMemoryGuard(),
        grace_seconds=grace_seconds,
        idle_ttl_seconds=300.0,
        model_id=MODEL_ID,
        model_revision=REVISION,
        clock=clock or time.monotonic,
    )


def _run_request(supervisor, client, outcomes, **kwargs):
    def run():
        try:
            outcomes.append(("ok", supervisor.handle_request(client, **kwargs)))
        except Exception as exc:  # test the typed boundary
            outcomes.append(("error", exc))

    thread = threading.Thread(target=run)
    thread.start()
    return thread


def test_atlas_completing_within_grace_runs_penny_on_same_worker():
    factory = FakeFactory()
    supervisor = _supervisor(factory)
    atlas_outcomes = []
    penny_outcomes = []

    atlas_thread = _run_request(
        supervisor,
        ClientKind.ATLAS,
        atlas_outcomes,
        audio_path="atlas.wav",
        options={},
    )
    while not factory.workers or not factory.workers[0].submitted:
        time.sleep(0.005)
    penny_thread = _run_request(
        supervisor,
        ClientKind.PENNY,
        penny_outcomes,
        audio_path="penny.wav",
        options={},
    )

    while supervisor.status()["state"] != SupervisorState.ATLAS_GRACE.value:
        time.sleep(0.005)
    factory.workers[0].complete(_result("atlas"))
    while len(factory.workers[0].submitted) < 2:
        time.sleep(0.005)
    factory.workers[0].complete(_result("penny"))

    atlas_thread.join(timeout=1)
    penny_thread.join(timeout=1)
    assert atlas_outcomes == [("ok", _result("atlas"))]
    assert penny_outcomes == [("ok", _result("penny"))]
    assert len(factory.workers) == 1
    assert factory.workers[0].terminated.is_set() is False


@pytest.mark.parametrize('background_client', [ClientKind.ATLAS, ClientKind.BACKFILL])
def test_atlas_is_preempted_after_grace_and_penny_uses_replacement_worker(background_client):
    factory = FakeFactory()
    supervisor = _supervisor(factory, grace_seconds=0.03)
    atlas_outcomes = []
    penny_outcomes = []

    atlas_thread = _run_request(
        supervisor,
        background_client,
        atlas_outcomes,
        audio_path="atlas.wav",
        options={},
    )
    while not factory.workers or not factory.workers[0].submitted:
        time.sleep(0.005)
    penny_thread = _run_request(
        supervisor,
        ClientKind.PENNY,
        penny_outcomes,
        audio_path="penny.wav",
        options={},
    )

    penny_thread.join(timeout=1)
    assert not penny_outcomes
    while len(factory.workers) < 2:
        time.sleep(0.005)
    assert factory.workers[0].terminated.is_set()
    factory.workers[1].complete(_result("penny"))
    penny_thread.join(timeout=1)
    atlas_thread.join(timeout=1)

    assert penny_outcomes == [("ok", _result("penny"))]
    assert len(atlas_outcomes) == 1
    assert isinstance(atlas_outcomes[0][1], WhisperPreempted)


def test_second_atlas_request_is_rejected_instead_of_queued_behind_model():
    factory = FakeFactory()
    supervisor = _supervisor(factory)
    outcomes = []
    first = _run_request(
        supervisor,
        ClientKind.ATLAS,
        outcomes,
        audio_path="first.wav",
        options={},
    )
    while not factory.workers or not factory.workers[0].submitted:
        time.sleep(0.005)

    with pytest.raises(WhisperBusy):
        supervisor.handle_request(ClientKind.ATLAS, audio_path="second.wav", options={})

    factory.workers[0].complete(_result("first"))
    first.join(timeout=1)


def test_penny_takes_over_when_atlas_fails_during_grace():
    factory = FakeFactory()
    supervisor = _supervisor(factory)
    atlas_outcomes = []
    penny_outcomes = []

    atlas_thread = _run_request(
        supervisor,
        ClientKind.ATLAS,
        atlas_outcomes,
        audio_path="atlas.wav",
        options={},
    )
    while not factory.workers or not factory.workers[0].submitted:
        time.sleep(0.005)
    penny_thread = _run_request(
        supervisor,
        ClientKind.PENNY,
        penny_outcomes,
        audio_path="penny.wav",
        options={},
    )

    while supervisor.status()["state"] != SupervisorState.ATLAS_GRACE.value:
        time.sleep(0.005)
    factory.workers[0].complete(WhisperUnavailable("atlas worker error"))

    while len(factory.workers[0].submitted) < 2:
        time.sleep(0.005)
    factory.workers[0].complete(_result("penny"))
    atlas_thread.join(timeout=1)
    penny_thread.join(timeout=1)

    assert isinstance(atlas_outcomes[0][1], WhisperUnavailable)
    assert penny_outcomes == [("ok", _result("penny"))]


def test_memory_guard_refuses_spawn_under_high_pressure():
    factory = FakeFactory()
    supervisor = _supervisor(factory, guard=StaticMemoryGuard(pressure=True))

    with pytest.raises(WhisperUnavailable):
        supervisor.handle_request(ClientKind.PENNY, audio_path="penny.wav", options={})

    assert factory.workers == []


def test_idle_worker_is_terminated_after_ttl():
    now = [0.0]
    factory = FakeFactory()
    supervisor = _supervisor(factory, clock=lambda: now[0])
    outcome = []
    thread = _run_request(
        supervisor,
        ClientKind.PENNY,
        outcome,
        audio_path="penny.wav",
        options={},
    )
    while not factory.workers or not factory.workers[0].submitted:
        time.sleep(0.005)
    factory.workers[0].complete(_result("penny"))
    thread.join(timeout=1)
    now[0] = 301.0

    assert supervisor.expire_idle() is True
    assert factory.workers[0].terminated.is_set()
    assert supervisor.status()["worker_pid"] is None


def test_hung_worker_fails_after_deadline_and_next_request_gets_new_worker():
    """penny#138: an alive worker that never answers must not block forever."""
    factory = FakeFactory()
    supervisor = SharedWhisperSupervisor(
        worker_factory=factory,
        memory_guard=StaticMemoryGuard(),
        grace_seconds=0.2,
        idle_ttl_seconds=300.0,
        job_deadline_seconds=1.0,
        model_id=MODEL_ID,
        model_revision=REVISION,
    )
    outcomes = []
    thread = _run_request(supervisor, ClientKind.ATLAS, outcomes,
                          audio_path="/tmp/a.wav", options={})
    thread.join(timeout=5)
    assert not thread.is_alive()
    kind, exc = outcomes[0]
    assert kind == "error" and "worker_deadline_exceeded" in str(exc)
    assert factory.workers[0].terminated.is_set()
    assert supervisor.status()["state"] == "idle"

    outcomes.clear()
    thread = _run_request(supervisor, ClientKind.ATLAS, outcomes,
                          audio_path="/tmp/b.wav", options={})
    deadline = time.monotonic() + 2
    while len(factory.workers) < 2 or not factory.workers[1].submitted:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    factory.workers[1].complete(_result(factory.workers[1].submitted[0]["request_id"]))
    thread.join(timeout=5)
    assert outcomes[0][0] == "ok"


def test_job_deadline_scales_with_audio_length():
    clock = [0.0]
    factory = FakeFactory()
    supervisor = SharedWhisperSupervisor(
        worker_factory=factory,
        memory_guard=StaticMemoryGuard(),
        job_deadline_seconds=900.0,
        model_id=MODEL_ID,
        model_revision=REVISION,
        clock=lambda: clock[0],
    )
    job = supervisor._start_job(ClientKind.PENNY, audio_path="/tmp/long.wav",
                                options={"_audio_seconds": 7200.0})
    assert job.deadline_seconds == 14400.0
    assert "_audio_seconds" not in factory.workers[0].submitted[0]["options"]

def test_hung_worker_deadline_terminates_and_next_request_succeeds(caplog):
    caplog.set_level(logging.WARNING, logger="shared_whisper.supervisor")
    now = [100.0]
    factory = FakeFactory()
    supervisor = _supervisor(factory, clock=lambda: now[0])
    outcomes = []
    thread = _run_request(
        supervisor, ClientKind.ATLAS, outcomes, audio_path="hang.wav", options={}
    )
    try:
        while not factory.workers or not factory.workers[0].submitted:
            time.sleep(0.005)
        status = supervisor.status()
        assert status["active_job_started_at"] is not None
        assert status["active_job_age_seconds"] == 0
        now[0] += 901
        thread.join(timeout=1)
        assert not thread.is_alive()
        assert isinstance(outcomes[0][1], WhisperUnavailable)
        assert str(outcomes[0][1]) == "worker_deadline_exceeded"
        assert factory.workers[0].terminated.is_set()
        assert "worker_deadline_exceeded" in caplog.text
        assert supervisor.status()["active_job_started_at"] is None
        assert supervisor.status()["active_job_age_seconds"] is None
    finally:
        now[0] += 1000
        thread.join(timeout=1)

    recovered = []
    thread = _run_request(
        supervisor, ClientKind.ATLAS, recovered, audio_path="next.wav", options={}
    )
    try:
        limit = time.monotonic() + 1
        while len(factory.workers) < 2 and time.monotonic() < limit:
            time.sleep(0.005)
        assert len(factory.workers) == 2
        factory.workers[1].complete(_result("recovered"))
        thread.join(timeout=1)
        assert recovered == [("ok", _result("recovered"))]
    finally:
        now[0] += 1000
        thread.join(timeout=1)
