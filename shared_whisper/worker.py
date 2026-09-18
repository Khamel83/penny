"""The only model-bearing process and macOS memory safety probes."""

from __future__ import annotations

import multiprocessing
import os
import queue
import re
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .protocol import WhisperResult, WhisperUnavailable


_FREE_PERCENT_RE = re.compile(r"System-wide memory free percentage:\s*(\d+)%")
_LARGE_OWNER_MARKERS = (
    "agent-cli-server-whisper",
    "agent-cli-whisper-mlx",
    "mlx_whisper",
    "Penny Shared Whisper Worker",
)


def build_result(
    *,
    request_id: str,
    response: Mapping[str, Any],
    model_id: str,
    model_revision: str,
) -> WhisperResult:
    """Convert one MLX response into the shared protocol result."""

    text = response.get("text")
    segments = response.get("segments")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("MLX response missing text")
    if not isinstance(segments, list) or not segments:
        raise ValueError("MLX response missing segments")
    if not all(isinstance(segment, dict) for segment in segments):
        raise ValueError("MLX response contains invalid segments")
    return WhisperResult(
        text=text,
        segments=list(segments),
        model_id=model_id,
        model_revision=model_revision,
        request_id=request_id,
    )


def parse_free_percent(output: str) -> int | None:
    """Parse the stable metadata line emitted by `memory_pressure -Q`."""

    match = _FREE_PERCENT_RE.search(output)
    return int(match.group(1)) if match else None


class MacMemoryGuard:
    """Fail-closed checks that prevent a second large model from loading."""

    def __init__(
        self,
        *,
        process_reader: Callable[[], str] | None = None,
        pressure_reader: Callable[[], str] | None = None,
        min_free_percent: int = 12,
    ) -> None:
        self._process_reader = process_reader or _read_processes
        self._pressure_reader = pressure_reader or _read_memory_pressure
        self._min_free_percent = max(1, min(50, int(min_free_percent)))

    def has_existing_large_owner(self) -> bool:
        try:
            output = self._process_reader()
        except Exception:
            return True
        if output is None:
            return True
        return any(marker in output for marker in _LARGE_OWNER_MARKERS)

    def pressure_high(self) -> bool:
        try:
            output = self._pressure_reader()
        except Exception:
            return True
        if output is None:
            return True
        free_percent = parse_free_percent(output)
        return free_percent is None or free_percent < self._min_free_percent


class SubprocessWorker:
    """Persistent one-request-at-a-time worker with a killable MLX boundary."""

    def __init__(
        self,
        *,
        model_path: Path,
        model_id: str,
        model_revision: str,
        context: multiprocessing.context.BaseContext | None = None,
    ) -> None:
        self._context = context or multiprocessing.get_context("spawn")
        self._requests = self._context.Queue()
        self._results = self._context.Queue()
        self._model_path = str(model_path)
        self._model_id = model_id
        self._model_revision = model_revision
        self._process = self._context.Process(
            target=_worker_main,
            args=(
                self._requests,
                self._results,
                self._model_path,
                self._model_id,
                self._model_revision,
            ),
            name="Penny Shared Whisper Worker",
            daemon=True,
        )
        self._process.start()

    @property
    def pid(self) -> int:
        if self._process.pid is None:
            raise RuntimeError("Whisper worker has no PID")
        return self._process.pid

    def submit(self, request: dict[str, Any]) -> None:
        if not self.is_alive():
            raise RuntimeError("Whisper worker is not alive")
        self._requests.put(dict(request))

    def poll(self, timeout: float) -> WhisperResult | BaseException | None:
        try:
            kind, value = self._results.get(timeout=timeout)
        except queue.Empty:
            return None
        if kind == "ok":
            return value
        return WhisperUnavailable("Whisper worker failed while transcribing")

    def terminate(self) -> None:
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=2.0)
        if self._process.is_alive():
            self._process.kill()
            self._process.join(timeout=2.0)

    def is_alive(self) -> bool:
        return self._process.is_alive()


def _worker_main(
    requests: Any,
    results: Any,
    model_path: str,
    model_id: str,
    model_revision: str,
) -> None:
    try:
        from setproctitle import setproctitle

        setproctitle("Penny Shared Whisper Worker (large-v3-turbo)")
    except Exception:
        pass

    if os.environ.get("HF_HUB_OFFLINE") != "1":
        results.put(("error", "offline_mode_required"))
        return

    try:
        import mlx_whisper
    except Exception:
        results.put(("error", "mlx_import_failed"))
        return

    while True:
        request = requests.get()
        if request is None:
            return
        try:
            response = mlx_whisper.transcribe(
                str(request["audio_path"]),
                path_or_hf_repo=model_path,
                **dict(request.get("options") or {}),
            )
            result = build_result(
                request_id=str(request["request_id"]),
                response=response,
                model_id=model_id,
                model_revision=model_revision,
            )
        except Exception:
            results.put(("error", "transcription_failed"))
            continue
        results.put(("ok", result))


def _read_processes() -> str | None:
    try:
        completed = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except OSError:
        return None
    return completed.stdout if completed.returncode == 0 else None


def _read_memory_pressure() -> str | None:
    try:
        completed = subprocess.run(
            ["memory_pressure", "-Q"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except OSError:
        return None
    return completed.stdout if completed.returncode == 0 else None
