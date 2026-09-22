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
