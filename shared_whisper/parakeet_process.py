"""Killable Parakeet child using a separately pinned Python environment."""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import threading

from .backends import PARAKEET_ID, PARAKEET_REVISION
from .protocol import WhisperUnavailable, WhisperProtocolError
from .worker import build_result


class ParakeetWorker:
    def __init__(self, *, model_path: Path, python_path: str):
        self._results = queue.Queue()
        self._request_id = None
        self._process = subprocess.Popen(
            [python_path, "-m", "shared_whisper.parakeet_worker", str(model_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "HF_HUB_OFFLINE": "1"},
        )
        threading.Thread(target=self._read, daemon=True).start()

    @property
    def pid(self):
        return self._process.pid

    def submit(self, request):
        if not self.is_alive():
            raise RuntimeError("parakeet_worker_not_alive")
        self._request_id = request["request_id"]
        self._process.stdin.write(json.dumps(request) + "\n")
        self._process.stdin.flush()

    def _read(self):
        for line in self._process.stdout:
            try:
                payload = json.loads(line)
                if "ok" not in payload:
                    reason = payload.get("error")
                    if reason not in {
                        "invalid_parakeet_token_time",
                        "backwards_parakeet_token_time",
                        "empty_parakeet_output",
                        "parakeet_translation_not_supported",
                        "audio_duration_out_of_bounds",
                    }:
                        reason = "parakeet_output_invalid"
                    raise WhisperProtocolError(
                        reason,
                        code="quality_review",
                        timing_context=payload.get("timing_context"),
                        model_id=PARAKEET_ID,
                    )
                self._results.put(
                    build_result(
                        request_id=self._request_id,
                        response=payload["ok"],
                        model_id=PARAKEET_ID,
                        model_revision=PARAKEET_REVISION,
                    )
                )
            except WhisperProtocolError as exc:
                self._results.put(exc)
            except Exception:
                self._results.put(
                    WhisperProtocolError(
                        "Parakeet output needs retry",
                        code="quality_review",
                        model_id=PARAKEET_ID,
                    )
                )

    def poll(self, timeout):
        try:
            return self._results.get(timeout=timeout)
        except queue.Empty:
            if not self.is_alive():
                return WhisperUnavailable("Parakeet worker exited")
            return None

    def terminate(self):
        if self.is_alive():
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)
        for stream in (self._process.stdin, self._process.stdout):
            stream.close()

    def is_alive(self):
        return self._process.poll() is None
