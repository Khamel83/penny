"""Single-owner Whisper supervisor with Penny preemption semantics.

This module intentionally does not import MLX. The worker factory supplies the
only model-bearing child process, which can be terminated without risking the
Penny webhook or the supervisor itself.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Protocol

from .protocol import (
    ClientKind,
    WhisperBusy,
    WhisperPreempted,
    WhisperProtocolError,
    WhisperResult,
    WhisperUnavailable,
)

logger = logging.getLogger(__name__)

# /health turns unhealthy after this many back-to-back failures that a restart
# can fix (penny#186, penny#192). One success clears the count.
UNHEALTHY_AFTER_CONSECUTIVE_FAILURES = 3
# A waiter thread fails a hung job at its deadline. If the job is still there
# this long after, the waiter itself is stuck, so /health reports it.
_STUCK_JOB_SLACK_SECONDS = 120.0
# status() must answer even if a request thread holds the supervisor lock.
_STATUS_LOCK_TIMEOUT_SECONDS = 3.0
# macOS memory pressure is transient and a restart cannot clear it; doctor
# alarms on it separately, so it does not count toward an unhealthy /health.
_MEMORY_PRESSURE_REASON = "macOS memory pressure is too high"
# Another process holds a Whisper/Parakeet model: a stuck worker that outlived
# the previous service process, or a retired owner. A restart cannot clear it,
# so it does not count as a restart-fixable failure; /health reports it as its
# own reason, which the keeper leaves alone and Kuma and doctor still show.
_LARGE_OWNER_REASON = "another large Whisper owner is present"
# The process list could not be read, so nobody knows whether another owner
# is there. Loading stays refused (fail closed), but /health names this as its
# own reason: it is not proof of an owner, and the keeper treats it as a normal
# strike, since a restart may clear a fault in this process (penny#196).
_OWNER_CHECK_FAILED_REASON = "could not read the process list to check for another Whisper owner"
_OWNER_PRESENT = "present"
_OWNER_ABSENT = "absent"
_OWNER_UNKNOWN = "unknown"
# status() re-checks for another owner only while idle. It skips the check
# rather than wait behind a busy request.
_OWNER_PROBE_LOCK_TIMEOUT_SECONDS = 0.2


class SupervisorState(StrEnum):
    IDLE = "idle"
    ATLAS_RUNNING = "atlas_running"
    ATLAS_GRACE = "atlas_grace"
    STOPPING_ATLAS = "stopping_atlas"
    PENNY_RUNNING = "penny_running"
    BACKFILL_RUNNING = "backfill_running"


class MemoryGuard(Protocol):
    """Safety probes used before creating a model-bearing worker."""

    def has_existing_large_owner(self) -> bool: ...

    def pressure_high(self) -> bool: ...

    # Optional: ``present``, ``absent`` or ``unknown``. A guard without it is
    # read through has_existing_large_owner (see _check_large_owner).


class WorkerHandle(Protocol):
    """Minimal process boundary used by the supervisor."""

    pid: int

    def submit(self, request: dict[str, Any]) -> None: ...

    def poll(self, timeout: float) -> WhisperResult | BaseException | None: ...

    def terminate(self) -> None: ...

    def is_alive(self) -> bool: ...

    # Optional: ``is_ready()`` returns True once the model process has started
    # and can take a request. Workers without it count as ready.


WorkerFactory = Callable[[], WorkerHandle]


@dataclass
class _Job:
    client: ClientKind
    request_id: str
    worker: WorkerHandle
    started_at: float = 0.0
    started_at_epoch: float = 0.0
    deadline_seconds: float = 900.0
    worker_started_at: float = 0.0
    completed: bool = False
    preempted: bool = False
    result: WhisperResult | None = None
    error: BaseException | None = None


class SharedWhisperSupervisor:
    """Own one worker and interrupt only replaceable Atlas work for Penny."""

    def __init__(
        self,
        *,
        worker_factory: WorkerFactory,
        fallback_worker_factory: WorkerFactory | None = None,
        memory_guard: MemoryGuard,
        grace_seconds: float = 30.0,
        idle_ttl_seconds: float = 300.0,
        job_deadline_seconds: float = 900.0,
        worker_start_timeout_seconds: float = 180.0,
        model_id: str,
        model_revision: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._worker_factory = worker_factory
        self._fallback_worker_factory = fallback_worker_factory
        self._worker_backend = "primary"
        self._memory_guard = memory_guard
        self._grace_seconds = max(0.0, grace_seconds)
        self._idle_ttl_seconds = max(0.0, idle_ttl_seconds)
        # A worker can stay alive without making progress (penny#138: 12 h with
        # /health green). Past this deadline the job fails and the worker is
        # replaced on the next request instead of blocking every client.
        self._job_deadline_seconds = max(1.0, job_deadline_seconds)
        # A new worker that never finishes starting (penny#192: each Parakeet
        # child hung at Python start) fails its job after this, instead of
        # holding every client until the much longer job deadline.
        self._worker_start_timeout_seconds = max(1.0, worker_start_timeout_seconds)
        self._model_id = model_id
        self._model_revision = model_revision
        self._clock = clock
        self._condition = threading.Condition()
        self._worker: WorkerHandle | None = None
        self._job: _Job | None = None
        self._state = SupervisorState.IDLE
        self._last_used_at: float | None = None
        self._preemption_count = 0
        self._worker_started_at = 0.0
        # Workers that survived terminate and kill. Never load another model
        # while one of these is alive; /health reports it so launchd restarts
        # once. The new process sees the survivor as a large owner instead.
        self._abandoned_workers: list[WorkerHandle] = []
        self._consecutive_failures = 0
        self._last_failure_reason: str | None = None
        self._last_success_at_epoch: float | None = None
        self._owner_check = _OWNER_ABSENT
        # Counts worker starts, so an idle owner probe is discarded when our
        # own worker started while the probe ran.
        self._worker_generation = 0

    def status(self) -> dict[str, Any]:
        """Return an allowlisted, secret-free operational snapshot.

        ``healthy`` is False when no request can be expected to complete. The
        HTTP layer turns that into a 503 so the launchd keeper restarts the
        service and Uptime Kuma alerts.
        """

        self._refresh_large_owner()
        if not self._condition.acquire(timeout=_STATUS_LOCK_TIMEOUT_SECONDS):
            return {
                "state": "unresponsive",
                "model_id": self._model_id,
                "model_revision": self._model_revision,
                "healthy": False,
                "unhealthy_reason": "supervisor_unresponsive",
            }
        try:
            worker = self._worker if self._worker and self._worker.is_alive() else None
            job = self._job
            now = self._clock()
            unhealthy_reason = self._unhealthy_reason_locked(now)
            return {
                "state": self._state.value,
                "model_id": self._model_id,
                "model_revision": self._model_revision,
                "worker_pid": worker.pid if worker else None,
                "worker_count": 1 if worker else 0,
                "resident_backend": self._worker_backend if worker else None,
                "worker_ready": self._worker_ready(worker) if worker else None,
                "active_client": job.client.value if job else None,
                "active_job_started_at": job.started_at_epoch if job else None,
                "active_job_age_seconds": (
                    max(0.0, now - job.started_at) if job else None
                ),
                "preemption_count": self._preemption_count,
                "healthy": unhealthy_reason is None,
                "unhealthy_reason": unhealthy_reason,
                "consecutive_failures": self._consecutive_failures,
                "last_failure_reason": self._last_failure_reason,
                "last_success_at": self._last_success_at_epoch,
            }
        finally:
            self._condition.release()

    def _refresh_large_owner(self) -> None:
        """Re-check for another model owner while idle, without the lock.

        A stuck worker left by the previous service process is invisible to
        this one until it looks. Checking while idle makes /health report it
        right after a restart, and clear once it exits. While our own worker
        runs, the check would find that worker, so it is skipped.
        """

        if not self._condition.acquire(timeout=_OWNER_PROBE_LOCK_TIMEOUT_SECONDS):
            return
        try:
            if self._job is not None or _safe_is_alive(self._worker):
                return
            generation = self._worker_generation
        finally:
            self._condition.release()
        owner_check = _check_large_owner(self._memory_guard)
        if not self._condition.acquire(timeout=_OWNER_PROBE_LOCK_TIMEOUT_SECONDS):
            return
        try:
            if (
                generation == self._worker_generation
                and self._job is None
                and not _safe_is_alive(self._worker)
            ):
                self._set_owner_check_locked(owner_check)
        finally:
            self._condition.release()

    def _set_owner_check_locked(self, owner_check: str) -> None:
        self._owner_check = owner_check
        if owner_check == _OWNER_PRESENT:
            self._last_failure_reason = _LARGE_OWNER_REASON
        elif owner_check == _OWNER_UNKNOWN:
            self._last_failure_reason = _OWNER_CHECK_FAILED_REASON

    def _unhealthy_reason_locked(self, now: float) -> str | None:
        if any(_safe_is_alive(worker) for worker in self._abandoned_workers):
            return "worker_did_not_exit"
        self._abandoned_workers = []
        if self._owner_check == _OWNER_PRESENT:
            return "large_owner_present"
        if self._owner_check == _OWNER_UNKNOWN:
            return "owner_check_failed"
        job = self._job
        if job is not None:
            if now - job.started_at > job.deadline_seconds + _STUCK_JOB_SLACK_SECONDS:
                return "job_past_deadline"
            if (
                not self._worker_ready(job.worker)
                and now - job.worker_started_at
                > self._worker_start_timeout_seconds + _STUCK_JOB_SLACK_SECONDS
            ):
                return "worker_start_timeout"
        if self._consecutive_failures >= UNHEALTHY_AFTER_CONSECUTIVE_FAILURES:
            return "consecutive_failures"
        return None

    def handle_request(
        self,
        client: ClientKind,
        *,
        audio_path: str,
        options: dict[str, Any],
    ) -> WhisperResult:
        """Run one request, giving an incoming Penny request the interrupt."""

        client = ClientKind(client)
        if client is ClientKind.PENNY:
            return self._handle_penny(audio_path=audio_path, options=options)
        return self._handle_atlas(audio_path=audio_path, options=options, client=client)

    def expire_idle(self) -> bool:
        """Unload an idle model worker when the configured TTL has elapsed."""

        with self._condition:
            if self._job is not None or self._worker is None:
                return False
            if self._last_used_at is None:
                return False
            if self._clock() - self._last_used_at < self._idle_ttl_seconds:
                return False
            self._stop_worker_locked()
            self._last_used_at = None
            self._condition.notify_all()
            return True

    def _handle_atlas(
        self, *, audio_path: str, options: dict[str, Any], client=ClientKind.ATLAS
    ) -> WhisperResult:
        job = self._start_job(
            client,
            audio_path=audio_path,
            options=options,
        )
        return self._wait_for_job(job)

    def _handle_penny(
        self, *, audio_path: str, options: dict[str, Any]
    ) -> WhisperResult:
        with self._condition:
            self._expire_idle_locked()
            active = self._job
            if active is None:
                job = self._start_job_locked(
                    ClientKind.PENNY,
                    audio_path=audio_path,
                    options=options,
                )
            elif active.client is ClientKind.PENNY:
                raise WhisperBusy("Penny already owns the shared Whisper worker")
            else:
                deadline = self._clock() + self._grace_seconds
                self._state = SupervisorState.ATLAS_GRACE
                while (
                    self._job is active
                    and not active.completed
                    and not active.preempted
                ):
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        self._state = SupervisorState.STOPPING_ATLAS
                        self._preempt_locked(active)
                        break
                    self._condition.wait(timeout=min(remaining, 0.05))

                # The Atlas waiter normally clears this job. If Atlas failed
                # before Penny acquired the lock, clear the completed record
                # here and let Penny proceed. An Atlas error must not block the
                # higher-priority request.
                if active.completed and self._job is active:
                    self._job = None
                    self._state = SupervisorState.IDLE
                    self._condition.notify_all()
                job = self._start_job_locked(
                    ClientKind.PENNY,
                    audio_path=audio_path,
                    options=options,
                )
        return self._wait_for_job(job)

    def _start_job(
        self,
        client: ClientKind,
        *,
        audio_path: str,
        options: dict[str, Any],
    ) -> _Job:
        with self._condition:
            return self._start_job_locked(
                client, audio_path=audio_path, options=options
            )

    def _start_job_locked(
        self,
        client: ClientKind,
        *,
        audio_path: str,
        options: dict[str, Any],
    ) -> _Job:
        if self._job is not None:
            raise WhisperBusy("Whisper worker already has an active request")
        backend = options.pop("_backend", "primary")
        audio_seconds = options.pop("_audio_seconds", None)
        # Scale with the recording: a long voice memo on the slower Whisper
        # fallback can legitimately take longer than the base deadline.
        deadline = self._job_deadline_seconds
        if isinstance(audio_seconds, (int, float)) and audio_seconds > 0:
            deadline = max(deadline, 2.0 * float(audio_seconds))
        if backend not in {"primary", "whisper"}:
            raise WhisperProtocolError("unsupported_backend")
        worker = self._ensure_worker_locked(backend)
        request_id = str(uuid.uuid4())
        job = _Job(client=client, request_id=request_id, worker=worker,
                   started_at=self._clock(), started_at_epoch=time.time(),
                   deadline_seconds=deadline,
                   worker_started_at=self._worker_started_at)
        self._job = job
        self._state = (
            SupervisorState.PENNY_RUNNING
            if client is ClientKind.PENNY
            else (
                SupervisorState.BACKFILL_RUNNING
                if client is ClientKind.BACKFILL
                else SupervisorState.ATLAS_RUNNING
            )
        )
        self._last_used_at = self._clock()
        try:
            worker.submit(
                {
                    "request_id": request_id,
                    "client": client.value,
                    "audio_path": audio_path,
                    "options": dict(options),
                }
            )
        except Exception as exc:
            self._job = None
            self._state = SupervisorState.IDLE
            self._record_failure_locked("Whisper worker rejected the request")
            raise WhisperUnavailable("Whisper worker rejected the request") from exc
        self._condition.notify_all()
        return job

    def _ensure_worker_locked(self, backend="primary") -> WorkerHandle:
        if backend != self._worker_backend and self._worker is not None:
            self._stop_worker_locked()
        if self._worker is not None:
            if self._worker.is_alive():
                return self._worker
            self._worker = None
        if any(_safe_is_alive(worker) for worker in self._abandoned_workers):
            self._record_failure_locked("Whisper worker did not exit")
            raise WhisperUnavailable("Whisper worker did not exit")
        self._abandoned_workers = []
        owner_check = _check_large_owner(self._memory_guard)
        self._set_owner_check_locked(owner_check)
        if owner_check == _OWNER_PRESENT:
            raise WhisperUnavailable(_LARGE_OWNER_REASON)
        if owner_check != _OWNER_ABSENT:
            raise WhisperUnavailable(_OWNER_CHECK_FAILED_REASON)
        if self._memory_guard.pressure_high():
            self._last_failure_reason = _MEMORY_PRESSURE_REASON
            raise WhisperUnavailable(_MEMORY_PRESSURE_REASON)
        factory = (
            self._worker_factory
            if backend == "primary"
            else self._fallback_worker_factory
        )
        if factory is None:
            raise WhisperProtocolError("fallback_not_configured")
        try:
            worker = factory()
        except Exception as exc:
            self._record_failure_locked("Whisper worker failed to start")
            raise WhisperUnavailable("Whisper worker failed to start") from exc
        self._worker_backend = backend
        if not worker.is_alive():
            self._record_failure_locked("Whisper worker failed to start")
            raise WhisperUnavailable("Whisper worker failed to start")
        self._worker = worker
        self._worker_generation += 1
        self._worker_started_at = self._clock()
        self._last_used_at = self._clock()
        return worker

    def _wait_for_job(self, job: _Job) -> WhisperResult:
        while True:
            with self._condition:
                if job.preempted:
                    raise WhisperPreempted(request_id=job.request_id)
                if job.completed:
                    if job.error is not None:
                        raise job.error
                    if job.result is None:
                        raise WhisperProtocolError(
                            "Whisper worker completed without a result"
                        )
                    return job.result
                worker = job.worker

            try:
                result = worker.poll(timeout=0.05)
            except Exception:  # a broken pipe must not strand the job
                result = None
            if result is None:
                now = self._clock()
                if (
                    not self._worker_ready(worker)
                    and now - job.worker_started_at > self._worker_start_timeout_seconds
                ):
                    self._fail_hung_job(job, "worker_start_timeout")
                    continue
                if now - job.started_at > job.deadline_seconds:
                    self._fail_hung_job(job, "worker_deadline_exceeded")
                    continue
                if not _safe_is_alive(worker):
                    with self._condition:
                        if not job.preempted and not job.completed:
                            job.error = WhisperUnavailable("Whisper worker exited")
                            job.completed = True
                            if self._worker is job.worker:
                                self._stop_worker_locked()
                            if self._job is job:
                                self._job = None
                                self._state = SupervisorState.IDLE
                            self._record_failure_locked("Whisper worker exited")
                            self._condition.notify_all()
                continue

            with self._condition:
                if job.preempted:
                    continue
                if isinstance(result, BaseException):
                    job.error = result
                    # An error the worker reports while started and alive is
                    # about this audio; the model is still answering. One it
                    # reports before starting or while exiting is not.
                    if self._worker_ready(worker) and _safe_is_alive(worker):
                        self._record_progress_locked()
                    else:
                        self._record_failure_locked(
                            str(result) or type(result).__name__
                        )
                else:
                    job.result = result
                    self._record_progress_locked()
                    self._last_success_at_epoch = time.time()
                job.completed = True
                self._last_used_at = self._clock()
                if self._job is job:
                    self._job = None
                    self._state = SupervisorState.IDLE
                self._condition.notify_all()

    def _fail_hung_job(self, job: _Job, reason: str) -> None:
        """Fail a job whose worker stopped making progress and drop the worker."""

        with self._condition:
            if job.preempted or job.completed:
                return
            logger.warning(
                "%s client=%s age_seconds=%.1f deadline_seconds=%.1f "
                "worker_age_seconds=%.1f",
                reason,
                job.client.value,
                self._clock() - job.started_at,
                job.deadline_seconds,
                self._clock() - job.worker_started_at,
            )
            job.error = WhisperUnavailable(reason)
            job.completed = True
            if self._worker is job.worker:
                self._stop_worker_locked()
            if self._job is job:
                self._job = None
                self._state = SupervisorState.IDLE
            self._record_failure_locked(reason)
            self._condition.notify_all()

    def _preempt_locked(self, job: _Job) -> None:
        job.preempted = True
        self._preemption_count += 1
        if self._worker is job.worker:
            self._stop_worker_locked()
        if self._job is job:
            self._job = None
        self._state = SupervisorState.IDLE
        self._condition.notify_all()

    def _stop_worker_locked(self) -> None:
        """Stop the resident worker. Never raises and never leaves it resident.

        A worker that survives terminate and kill is kept in the abandoned
        list: no new model loads while it lives, and /health reports it.
        """

        worker = self._worker
        self._worker = None
        if worker is None:
            return
        try:
            worker.terminate()
        except Exception as exc:  # noqa: BLE001 - a stuck child must not wedge the job
            logger.warning(
                "worker_terminate_failed pid=%s error=%s",
                getattr(worker, "pid", None),
                type(exc).__name__,
            )
        if _safe_is_alive(worker):
            logger.error("worker_did_not_exit pid=%s", getattr(worker, "pid", None))
            self._abandoned_workers.append(worker)

    def _record_failure_locked(self, reason: str) -> None:
        self._consecutive_failures += 1
        self._last_failure_reason = reason[:200]

    def _record_progress_locked(self) -> None:
        self._consecutive_failures = 0

    @staticmethod
    def _worker_ready(worker: WorkerHandle | None) -> bool:
        probe = getattr(worker, "is_ready", None)
        if probe is None:
            return True
        try:
            return bool(probe())
        except Exception:  # noqa: BLE001 - an unreadable worker is not ready
            return False

    def _expire_idle_locked(self) -> None:
        if self._job is None and self._worker is not None:
            if (
                self._last_used_at is not None
                and self._clock() - self._last_used_at >= self._idle_ttl_seconds
            ):
                self._stop_worker_locked()
                self._last_used_at = None


def _check_large_owner(guard: MemoryGuard) -> str:
    """Return ``present``, ``absent`` or ``unknown`` for another model owner.

    Uses the guard's ``large_owner_state`` when it has one, so a failed
    process-list read is reported as unknown rather than as an owner.
    """

    probe = getattr(guard, "large_owner_state", None)
    try:
        if probe is not None:
            state = probe()
            if state in (_OWNER_PRESENT, _OWNER_ABSENT, _OWNER_UNKNOWN):
                return state
            return _OWNER_UNKNOWN
        return _OWNER_PRESENT if guard.has_existing_large_owner() else _OWNER_ABSENT
    except Exception:  # noqa: BLE001 - a probe that fails cannot rule an owner out
        return _OWNER_UNKNOWN


def _safe_is_alive(worker: WorkerHandle | None) -> bool:
    if worker is None:
        return False
    try:
        return bool(worker.is_alive())
    except Exception:  # noqa: BLE001 - treat an unreadable process as alive
        return True
