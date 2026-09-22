"""Single-owner Whisper supervisor with Penny preemption semantics.

This module intentionally does not import MLX. The worker factory supplies the
only model-bearing child process, which can be terminated without risking the
Penny webhook or the supervisor itself.
"""

from __future__ import annotations

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


class WorkerHandle(Protocol):
    """Minimal process boundary used by the supervisor."""

    pid: int

    def submit(self, request: dict[str, Any]) -> None: ...

    def poll(self, timeout: float) -> WhisperResult | BaseException | None: ...

    def terminate(self) -> None: ...

    def is_alive(self) -> bool: ...


WorkerFactory = Callable[[], WorkerHandle]


@dataclass
class _Job:
    client: ClientKind
    request_id: str
    worker: WorkerHandle
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
        memory_guard: MemoryGuard,
        grace_seconds: float = 30.0,
        idle_ttl_seconds: float = 300.0,
        model_id: str,
        model_revision: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._worker_factory = worker_factory
        self._memory_guard = memory_guard
        self._grace_seconds = max(0.0, grace_seconds)
        self._idle_ttl_seconds = max(0.0, idle_ttl_seconds)
        self._model_id = model_id
        self._model_revision = model_revision
        self._clock = clock
        self._condition = threading.Condition()
        self._worker: WorkerHandle | None = None
        self._job: _Job | None = None
        self._state = SupervisorState.IDLE
        self._last_used_at: float | None = None
        self._preemption_count = 0

    def status(self) -> dict[str, Any]:
        """Return an allowlisted, secret-free operational snapshot."""

        with self._condition:
            worker = self._worker if self._worker and self._worker.is_alive() else None
            return {
                "state": self._state.value,
                "model_id": self._model_id,
                "model_revision": self._model_revision,
                "worker_pid": worker.pid if worker else None,
                "worker_count": 1 if worker else 0,
                "active_client": self._job.client.value if self._job else None,
                "preemption_count": self._preemption_count,
            }

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

    def _handle_atlas(self, *, audio_path: str, options: dict[str, Any], client=ClientKind.ATLAS) -> WhisperResult:
        job = self._start_job(
            client,
            audio_path=audio_path,
            options=options,
        )
        return self._wait_for_job(job)

    def _handle_penny(self, *, audio_path: str, options: dict[str, Any]) -> WhisperResult:
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
                while self._job is active and not active.completed and not active.preempted:
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
            return self._start_job_locked(client, audio_path=audio_path, options=options)

    def _start_job_locked(
        self,
        client: ClientKind,
        *,
        audio_path: str,
        options: dict[str, Any],
    ) -> _Job:
        if self._job is not None:
            raise WhisperBusy("Whisper worker already has an active request")
        worker = self._ensure_worker_locked()
        request_id = str(uuid.uuid4())
        job = _Job(client=client, request_id=request_id, worker=worker)
        self._job = job
        self._state = (
            SupervisorState.PENNY_RUNNING
            if client is ClientKind.PENNY
            else (SupervisorState.BACKFILL_RUNNING if client is ClientKind.BACKFILL
                  else SupervisorState.ATLAS_RUNNING)
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
            raise WhisperUnavailable("Whisper worker rejected the request") from exc
        self._condition.notify_all()
        return job

    def _ensure_worker_locked(self) -> WorkerHandle:
        if self._worker is not None:
            if self._worker.is_alive():
                return self._worker
            self._worker = None
        if self._memory_guard.has_existing_large_owner():
            raise WhisperUnavailable("another large Whisper owner is present")
        if self._memory_guard.pressure_high():
            raise WhisperUnavailable("macOS memory pressure is too high")
        worker = self._worker_factory()
        if not worker.is_alive():
            raise WhisperUnavailable("Whisper worker failed to start")
        self._worker = worker
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
                        raise WhisperProtocolError("Whisper worker completed without a result")
                    return job.result
                worker = job.worker

            result = worker.poll(timeout=0.05)
            if result is None:
                if not worker.is_alive():
                    with self._condition:
                        if not job.preempted and not job.completed:
                            job.error = WhisperUnavailable("Whisper worker exited")
                            job.completed = True
                            if self._job is job:
                                self._job = None
                                self._state = SupervisorState.IDLE
                            self._condition.notify_all()
                continue

            with self._condition:
                if job.preempted:
                    continue
                if isinstance(result, BaseException):
                    job.error = result
                else:
                    job.result = result
                job.completed = True
                self._last_used_at = self._clock()
                if self._job is job:
                    self._job = None
                    self._state = SupervisorState.IDLE
                self._condition.notify_all()

    def _preempt_locked(self, job: _Job) -> None:
        job.preempted = True
        self._preemption_count += 1
        if self._worker is job.worker:
            self._stop_worker_locked()
            self._worker = None
        if self._job is job:
            self._job = None
        self._state = SupervisorState.IDLE
        self._condition.notify_all()

    def _stop_worker_locked(self) -> None:
        worker = self._worker
        if worker is None:
            return
        worker.terminate()
        if worker.is_alive():
            raise WhisperUnavailable("Whisper worker did not exit")

    def _expire_idle_locked(self) -> None:
        if self._job is None and self._worker is not None:
            if (
                self._last_used_at is not None
                and self._clock() - self._last_used_at >= self._idle_ttl_seconds
            ):
                self._stop_worker_locked()
                self._worker = None
                self._last_used_at = None
