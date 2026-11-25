"""Simulated hangs: Shared Whisper must fail loudly, not stay green (penny#186, #192)."""

import io
import queue
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

import shared_whisper.supervisor as supervisor_module
from shared_whisper.parakeet_process import ParakeetWorker
from shared_whisper.protocol import ClientKind, WhisperResult, WhisperUnavailable
from shared_whisper.supervisor import SharedWhisperSupervisor
from shared_whisper.worker import MacMemoryGuard, SubprocessWorker


MODEL_ID = "mlx-community/whisper-large-v3-turbo"
REVISION = "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb"


def _result(request_id):
    return WhisperResult(
        text=request_id,
        segments=[{"start": 0.0, "end": 1.0, "text": request_id}],
        model_id=MODEL_ID,
        model_revision=REVISION,
        request_id=request_id,
    )


class Worker:
    """Fake model process. ``ready=False`` is a child stuck at start."""

    _next_pid = 7000

    def __init__(self, *, ready=True, dies_on_terminate=True):
        self.pid = Worker._next_pid
        Worker._next_pid += 1
        self.alive = True
        self.ready = ready
        self.dies_on_terminate = dies_on_terminate
        self.submitted = []
        self.results = queue.Queue()
        self.terminated = threading.Event()

    def submit(self, request):
        self.submitted.append(request)

    def poll(self, timeout):
        try:
            return self.results.get(timeout=timeout)
        except queue.Empty:
            return None

    def terminate(self):
        self.terminated.set()
        if self.dies_on_terminate:
            self.alive = False

    def is_alive(self):
        return self.alive

    def is_ready(self):
        return self.ready


class Factory:
    def __init__(self, *kinds):
        self.kinds = list(kinds)
        self.workers = []

    def __call__(self):
        worker = self.kinds.pop(0)() if self.kinds else Worker()
        self.workers.append(worker)
        return worker


class Guard:
    def __init__(self, *, pressure=False):
        self.pressure = pressure

    def has_existing_large_owner(self):
        return False

    def pressure_high(self):
        return self.pressure


def _supervisor(factory, now, guard=None):
    return SharedWhisperSupervisor(
        worker_factory=factory,
        memory_guard=guard or Guard(),
        job_deadline_seconds=900.0,
        worker_start_timeout_seconds=180.0,
        model_id=MODEL_ID,
        model_revision=REVISION,
        clock=lambda: now[0],
    )


def _request(supervisor, client=ClientKind.ATLAS):
    outcome = []

    def run():
        try:
            outcome.append(supervisor.handle_request(client, audio_path="a.wav", options={}))
        except Exception as exc:  # the typed boundary is under test
            outcome.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, outcome


def _wait_for(predicate, seconds=2.0):
    limit = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < limit, "condition not reached"
        time.sleep(0.005)


def _fail_one_stuck_start(supervisor, factory, now):
    thread, outcome = _request(supervisor)
    _wait_for(lambda: factory.workers and factory.workers[-1].submitted)
    now[0] += 181
    thread.join(timeout=2)
    assert not thread.is_alive()
    return outcome[0]


def test_child_stuck_at_start_fails_at_start_timeout_not_job_deadline():
    now = [1000.0]
    factory = Factory(lambda: Worker(ready=False))
    supervisor = _supervisor(factory, now)

    error = _fail_one_stuck_start(supervisor, factory, now)

    assert isinstance(error, WhisperUnavailable)
    assert str(error) == "worker_start_timeout"
    assert factory.workers[0].terminated.is_set()
    status = supervisor.status()
    assert status["active_client"] is None
    assert status["consecutive_failures"] == 1
    assert status["last_failure_reason"] == "worker_start_timeout"
    assert status["healthy"] is True  # one failure is not yet an outage


def test_repeated_stuck_starts_turn_health_red_and_a_success_clears_it():
    """penny#192: every new child hung at start while /health stayed green."""
    now = [1000.0]
    factory = Factory(*[lambda: Worker(ready=False)] * 3)
    supervisor = _supervisor(factory, now)

    for _ in range(3):
        _fail_one_stuck_start(supervisor, factory, now)

    status = supervisor.status()
    assert status["healthy"] is False
    assert status["unhealthy_reason"] == "consecutive_failures"
    assert status["consecutive_failures"] == 3

    thread, outcome = _request(supervisor)
    _wait_for(lambda: len(factory.workers) == 4 and factory.workers[3].submitted)
    factory.workers[3].results.put(_result("ok"))
    thread.join(timeout=2)
    assert outcome == [_result("ok")]
    status = supervisor.status()
    assert status["healthy"] is True
    assert status["consecutive_failures"] == 0
    assert status["last_success_at"] is not None


def test_ready_worker_is_held_to_the_job_deadline_not_the_start_timeout():
    now = [1000.0]
    factory = Factory(lambda: Worker(ready=True))
    supervisor = _supervisor(factory, now)
    thread, outcome = _request(supervisor)
    _wait_for(lambda: factory.workers and factory.workers[0].submitted)

    now[0] += 600  # long audio still transcribing: past start timeout, inside deadline
    time.sleep(0.1)
    assert thread.is_alive()
    assert supervisor.status()["healthy"] is True

    factory.workers[0].results.put(_result("long"))
    thread.join(timeout=2)
    assert outcome == [_result("long")]


def test_stuck_waiter_past_deadline_reports_unhealthy():
    """A job nobody fails (stuck waiter) must not look idle and green."""
    now = [1000.0]
    factory = Factory(lambda: Worker(ready=True))
    supervisor = _supervisor(factory, now)
    supervisor._start_job(ClientKind.ATLAS, audio_path="a.wav", options={})

    now[0] += 900 + 60
    assert supervisor.status()["healthy"] is True
    now[0] += 61 + 60
    status = supervisor.status()
    assert status["healthy"] is False
    assert status["unhealthy_reason"] == "job_past_deadline"


def test_stuck_waiter_on_a_never_started_worker_reports_unhealthy():
    now = [1000.0]
    factory = Factory(lambda: Worker(ready=False))
    supervisor = _supervisor(factory, now)
    supervisor._start_job(ClientKind.ATLAS, audio_path="a.wav", options={})

    now[0] += 180 + 121
    status = supervisor.status()
    assert status["healthy"] is False
    assert status["unhealthy_reason"] == "worker_start_timeout"


def test_worker_that_survives_kill_blocks_a_second_model_and_reports_unhealthy():
    now = [1000.0]
    factory = Factory(lambda: Worker(ready=True, dies_on_terminate=False))
    supervisor = _supervisor(factory, now)
    thread, outcome = _request(supervisor)
    _wait_for(lambda: factory.workers and factory.workers[0].submitted)
    now[0] += 901
    thread.join(timeout=2)
    assert str(outcome[0]) == "worker_deadline_exceeded"

    status = supervisor.status()
    assert status["active_client"] is None  # the job is not left behind
    assert status["healthy"] is False
    assert status["unhealthy_reason"] == "worker_did_not_exit"
    with pytest.raises(WhisperUnavailable, match="did not exit"):
        supervisor.handle_request(ClientKind.PENNY, audio_path="p.wav", options={})
    assert len(factory.workers) == 1  # no second model loaded

    factory.workers[0].alive = False  # the stuck child finally exits
    thread, outcome = _request(supervisor, ClientKind.PENNY)
    _wait_for(lambda: len(factory.workers) == 2 and factory.workers[1].submitted)
    factory.workers[1].results.put(_result("penny"))
    thread.join(timeout=2)
    assert outcome == [_result("penny")]
    assert supervisor.status()["healthy"] is True


def test_terminate_that_raises_does_not_leave_every_request_busy():
    """penny#186 path: an uncaught stop error kept the job, so all were busy."""
    now = [1000.0]

    def raising_worker():
        worker = Worker(ready=True)

        def terminate():
            worker.alive = False
            raise subprocess.TimeoutExpired("parakeet", 2)

        worker.terminate = terminate
        return worker

    factory = Factory(raising_worker)
    supervisor = _supervisor(factory, now)
    thread, outcome = _request(supervisor)
    _wait_for(lambda: factory.workers and factory.workers[0].submitted)
    now[0] += 901
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert str(outcome[0]) == "worker_deadline_exceeded"

    thread, outcome = _request(supervisor)
    _wait_for(lambda: len(factory.workers) == 2 and factory.workers[1].submitted)
    factory.workers[1].results.put(_result("next"))
    thread.join(timeout=2)
    assert outcome == [_result("next")]


def test_status_answers_unhealthy_when_the_supervisor_lock_is_stuck(monkeypatch):
    monkeypatch.setattr(supervisor_module, "_STATUS_LOCK_TIMEOUT_SECONDS", 0.05)
    supervisor = _supervisor(Factory(), [0.0])
    held = threading.Event()
    release = threading.Event()

    def hold():
        with supervisor._condition:
            held.set()
            release.wait(2)

    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    held.wait(1)
    try:
        status = supervisor.status()
    finally:
        release.set()
        thread.join(timeout=2)
    assert status["healthy"] is False
    assert status["unhealthy_reason"] == "supervisor_unresponsive"
    assert supervisor.status()["healthy"] is True


def test_memory_pressure_refusals_do_not_turn_health_red():
    supervisor = _supervisor(Factory(), [0.0], guard=Guard(pressure=True))
    for _ in range(5):
        with pytest.raises(WhisperUnavailable):
            supervisor.handle_request(ClientKind.ATLAS, audio_path="a.wav", options={})

    status = supervisor.status()
    assert status["healthy"] is True
    assert status["consecutive_failures"] == 0
    assert status["last_failure_reason"] == "macOS memory pressure is too high"


class OwnerGuard:
    """Process-list probe: ``present`` is another process holding a model."""

    def __init__(self, *, present=False, error=False):
        self.present = present
        self.error = error
        self.calls = 0
        self.during_probe = None

    def has_existing_large_owner(self):
        self.calls += 1
        hook, self.during_probe = self.during_probe, None
        if hook is not None:
            hook()
        if self.error:
            raise OSError("ps failed")
        return self.present

    def pressure_high(self):
        return False


def test_stuck_worker_left_by_a_previous_process_is_reported_without_a_restart_loop():
    """After a restart the old stuck child is a foreign owner. /health must say
    so at once, and must not count it as a failure a restart can fix."""
    now = [1000.0]
    factory = Factory()
    guard = OwnerGuard(present=True)
    supervisor = _supervisor(factory, now, guard=guard)

    status = supervisor.status()  # no request has arrived yet
    assert status["healthy"] is False
    assert status["unhealthy_reason"] == "large_owner_present"
    assert status["consecutive_failures"] == 0

    for _ in range(5):
        with pytest.raises(WhisperUnavailable, match="another large Whisper owner"):
            supervisor.handle_request(ClientKind.ATLAS, audio_path="a.wav", options={})
    status = supervisor.status()
    assert status["unhealthy_reason"] == "large_owner_present"
    assert status["consecutive_failures"] == 0
    assert factory.workers == []  # no second model loaded

    guard.present = False  # the old child finally exits
    assert supervisor.status()["healthy"] is True
    thread, outcome = _request(supervisor)
    _wait_for(lambda: factory.workers and factory.workers[0].submitted)
    factory.workers[0].results.put(_result("after"))
    thread.join(timeout=2)
    assert outcome == [_result("after")]


def test_owner_probe_does_not_count_our_own_running_worker():
    now = [1000.0]
    factory = Factory()
    guard = OwnerGuard()
    supervisor = _supervisor(factory, now, guard=guard)
    thread, outcome = _request(supervisor)
    _wait_for(lambda: factory.workers and factory.workers[0].submitted)

    guard.present = True  # the process list now shows our own worker
    calls = guard.calls
    status = supervisor.status()
    assert guard.calls == calls  # not probed while our worker runs
    assert status["healthy"] is True

    factory.workers[0].results.put(_result("ok"))
    thread.join(timeout=2)
    assert supervisor.status()["healthy"] is True  # resident idle worker


def test_owner_probe_is_discarded_when_our_worker_starts_during_it():
    now = [1000.0]
    factory = Factory()
    guard = OwnerGuard()
    supervisor = _supervisor(factory, now, guard=guard)

    def start_our_worker():
        supervisor._start_job(ClientKind.ATLAS, audio_path="a.wav", options={})
        guard.present = True  # the probe then sees the worker we just started

    guard.during_probe = start_our_worker
    status = supervisor.status()
    assert status["active_client"] == "atlas"
    assert status["healthy"] is True


def test_unreadable_process_list_is_reported_as_a_failed_check_not_an_owner():
    """penny#196 review: ps failing is not proof of another owner. Loading
    stays refused, but /health names the failed check, which the keeper
    counts as a normal strike, and it clears once ps reads again."""
    factory = Factory()
    guard = OwnerGuard(error=True)
    supervisor = _supervisor(factory, [0.0], guard=guard)

    status = supervisor.status()
    assert status["healthy"] is False
    assert status["unhealthy_reason"] == "owner_check_failed"
    assert "process list" in status["last_failure_reason"]
    assert status["consecutive_failures"] == 0

    with pytest.raises(WhisperUnavailable, match="could not read the process list"):
        supervisor.handle_request(ClientKind.ATLAS, audio_path="a.wav", options={})
    assert factory.workers == []  # still fails closed: no model loaded
    assert supervisor.status()["unhealthy_reason"] == "owner_check_failed"

    guard.error = False
    assert supervisor.status()["healthy"] is True


@pytest.mark.parametrize(
    ("reader", "reason"),
    [
        (lambda: None, "owner_check_failed"),  # ps exited nonzero or timed out
        (lambda: "", None),
        (lambda: "4242 Penny Shared Whisper Worker (large-v3-turbo)\n", "large_owner_present"),
    ],
)
def test_mac_guard_tells_a_failed_check_from_an_owner(reader, reason):
    guard = MacMemoryGuard(process_reader=reader, pressure_reader=lambda: "free percentage: 50%")
    supervisor = _supervisor(Factory(), [0.0], guard=guard)

    assert supervisor.status()["unhealthy_reason"] == reason


def test_errors_from_a_running_model_are_not_counted_as_an_outage():
    """Bad audio gets an error back from a live model; that is not a hang."""
    now = [1000.0]
    factory = Factory()
    supervisor = _supervisor(factory, now)
    for attempt in range(1, 5):
        thread, outcome = _request(supervisor)
        _wait_for(lambda: factory.workers and len(factory.workers[0].submitted) == attempt)
        factory.workers[0].results.put(WhisperUnavailable("Whisper worker failed while transcribing"))
        thread.join(timeout=2)
        assert isinstance(outcome[0], WhisperUnavailable)

    status = supervisor.status()
    assert status["healthy"] is True
    assert status["consecutive_failures"] == 0


def test_parakeet_start_signal_marks_ready_without_a_result():
    worker = object.__new__(ParakeetWorker)
    worker._results = queue.Queue()
    worker._ready = threading.Event()
    worker._request_id = "r1"
    worker._process = SimpleNamespace(stdout=io.StringIO('{"ready": true}\n'))

    assert worker.is_ready() is False
    worker._read()

    assert worker.is_ready() is True
    assert worker._results.empty()


def test_parakeet_terminate_returns_when_the_child_survives_kill():
    class StuckProcess:
        def __init__(self):
            self.signals = []
            self.stdout = SimpleNamespace(close=lambda: pytest.fail("closed a live pipe"))
            self.stdin = self.stdout

        def poll(self):
            return None

        def terminate(self):
            self.signals.append("term")

        def kill(self):
            self.signals.append("kill")

        def wait(self, timeout):
            raise subprocess.TimeoutExpired("parakeet", timeout)

    worker = object.__new__(ParakeetWorker)
    worker._process = StuckProcess()

    worker.terminate()  # must not raise

    assert worker._process.signals == ["term", "kill"]
    assert worker.is_alive() is True


def test_mlx_worker_start_signal_and_startup_failure():
    worker = object.__new__(SubprocessWorker)
    worker._results = queue.Queue()
    worker._ready = False

    worker._results.put(("ready", None))
    assert worker.poll(timeout=0.01) is None
    assert worker.is_ready() is True

    worker._ready = False
    worker._results.put(("error", "mlx_import_failed"))
    error = worker.poll(timeout=0.01)
    assert isinstance(error, WhisperUnavailable)
    assert str(error) == "Whisper worker failed to start"
    assert worker.is_ready() is False
