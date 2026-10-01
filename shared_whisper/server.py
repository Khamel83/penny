"""HTTP adapter and launch entry point for Penny Shared Whisper."""

from __future__ import annotations

import hmac
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

from config import (
    DEFAULT_WHISPER_MODEL_PATH,
    WHISPER_MODEL_ID,
    WHISPER_MODEL_REVISION,
)

from .protocol import (
    ClientKind,
    WhisperBusy,
    WhisperPreempted,
    WhisperProtocolError,
    WhisperUnavailable,
)
from .backends import PARAKEET_ID, primary_identity, parakeet_path
from .supervisor import SharedWhisperSupervisor
from .worker import MacMemoryGuard, SubprocessWorker


def create_app(
    supervisor: SharedWhisperSupervisor,
    *,
    auth_token: str,
    model_id: str = WHISPER_MODEL_ID,
    model_revision: str = WHISPER_MODEL_REVISION,
    temp_dir: Path | None = None,
    pilot_store: Any = None,
    allow_whisper_fallback: bool = False,
) -> Flask:
    """Create the authenticated OpenAI-compatible shared service."""

    app = Flask("penny-shared-whisper")
    app.config["SHARED_WHISPER_TEMP_DIR"] = temp_dir

    @app.before_request
    def _expire_idle_worker() -> None:
        supervisor.expire_idle()

    @app.get("/health")
    def health():
        payload = {
            "service": "penny-shared-whisper",
            "apple_pilot_enabled": pilot_store is not None,
            **supervisor.status(),
        }
        return jsonify(payload)

    @app.get("/ready")
    def ready():
        payload = {
            "service": "penny-shared-whisper",
            "apple_pilot_enabled": pilot_store is not None,
            **supervisor.status(),
        }
        return jsonify(payload)

    @app.post("/v1/audio/transcriptions")
    def transcribe():
        if not _authorized(auth_token):
            return jsonify({"error": {"code": "unauthorized"}}), 401
        client_header = request.headers.get("X-Whisper-Client", "")
        try:
            client = ClientKind(client_header)
        except ValueError:
            return jsonify({"error": {"code": "invalid_client"}}), 400
        incoming_model = request.form.get("model")
        allowed_models = {model_id}
        if allow_whisper_fallback:
            allowed_models.add(WHISPER_MODEL_ID)
        if incoming_model and incoming_model not in allowed_models:
            return jsonify({"error": {"code": "model_mismatch"}}), 400
        upload = request.files.get("file")
        if upload is None:
            return jsonify({"error": {"code": "file_required"}}), 400

        path = _save_upload(upload.filename, upload.stream, temp_dir)
        result = None
        started = time.monotonic()
        try:

            def whisper_retry():
                from .retry import audio_duration

                try:
                    bounded = audio_duration(path) <= 660
                except Exception as exc:
                    raise WhisperProtocolError("retry_duration_unverified") from exc
                if not bounded:
                    raise WhisperProtocolError(
                        "quality_review_requires_bounded_excerpt"
                    )
                from .retry_receipt import begin, save
                from dataclasses import asdict

                try:
                    receipt_path, retry_receipt = begin(path, result, client.value)
                except Exception as exc:
                    raise WhisperProtocolError("retry_receipt_failed") from exc
                try:
                    retried = supervisor.handle_request(
                        client,
                        audio_path=str(path),
                        options={**_form_options(), "_backend": "whisper"},
                    )
                except Exception:
                    retry_receipt["state"] = "retry_failed"
                    save(receipt_path, retry_receipt)
                    raise
                retry_receipt.update(fallback=asdict(retried), state="retry_completed")
                save(receipt_path, retry_receipt)
                return retried

            explicit_fallback = (
                allow_whisper_fallback and incoming_model == WHISPER_MODEL_ID
            )
            try:
                if explicit_fallback:
                    result = whisper_retry()
                else:
                    result = supervisor.handle_request(
                        client, audio_path=str(path), options=_form_options()
                    )
            except WhisperProtocolError as exc:
                if (
                    allow_whisper_fallback
                    and not explicit_fallback
                    and exc.code == "quality_review"
                ):
                    result = whisper_retry()
                else:
                    raise
            if allow_whisper_fallback and result.model_id == PARAKEET_ID:
                from transcript_quality import evaluate_transcript

                if not evaluate_transcript(result.text, tolerant_restarts=True).passed:
                    result = whisper_retry()
        except WhisperPreempted as exc:
            return _error_response(exc, 409)
        except (WhisperBusy, WhisperUnavailable) as exc:
            return _error_response(exc, 503)
        except WhisperProtocolError as exc:
            return _error_response(exc, 502)
        finally:
            if pilot_store is not None:
                try:
                    baseline = (
                        None
                        if result is None
                        else {
                            "text": result.text,
                            "segments": result.segments,
                            "model_id": result.model_id,
                            "model_revision": result.model_revision,
                            "elapsed_seconds": time.monotonic() - started,
                        }
                    )
                    pilot_store.capture(path, client.value, baseline)
                except Exception as exc:  # noqa: BLE001 - optional shadow cannot break primary ASR
                    # Shadow admission never changes the production response.
                    app.logger.warning(
                        "apple_pilot_admission_failed:%s", type(exc).__name__
                    )
            path.unlink(missing_ok=True)

        return jsonify(
            {
                "text": result.text,
                "segments": result.segments,
                "model_id": result.model_id,
                "model_revision": result.model_revision,
                "request_id": result.request_id,
            }
        )

    return app


def _authorized(expected: str) -> bool:
    supplied = request.headers.get("Authorization", "")
    actual = supplied.removeprefix("Bearer ").strip()
    return bool(expected) and hmac.compare_digest(actual, expected)


def _save_upload(filename: str | None, stream: Any, temp_dir: Path | None) -> Path:
    suffix = Path(filename or "audio.wav").suffix[:12] or ".wav"
    with tempfile.NamedTemporaryFile(
        mode="wb",
        suffix=suffix,
        dir=str(temp_dir) if temp_dir else None,
        delete=False,
    ) as destination:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            destination.write(chunk)
        return Path(destination.name)


def _form_options() -> dict[str, Any]:
    options: dict[str, Any] = {}
    for key in request.form:
        if key in {"model", "response_format"} or key.startswith("_"):
            continue
        values = request.form.getlist(key)
        value: Any = values if len(values) > 1 else values[0]
        if isinstance(value, str):
            lowered = value.lower()
            if lowered in {"true", "false"}:
                value = lowered == "true"
            else:
                try:
                    value = float(value) if "." in value else int(value)
                except ValueError:
                    pass
        options[key.removesuffix("[]")] = value
    return options


def _error_response(error: WhisperProtocolError, status: int):
    return (
        jsonify(
            {
                "error": {
                    "code": error.code,
                    "message": str(error),
                    "retryable": error.retryable,
                    **({"request_id": error.request_id} if error.request_id else {}),
                }
            }
        ),
        status,
    )


def build_supervisor_from_environment() -> SharedWhisperSupervisor:
    """Build the supervisor without importing MLX in this process."""

    model_path = Path(
        os.environ.get("PENNY_WHISPER_MODEL_PATH", str(DEFAULT_WHISPER_MODEL_PATH))
    ).expanduser()
    min_free_percent = _bounded_int(
        os.environ.get("PENNY_SHARED_WHISPER_MIN_FREE_PERCENT", "12"),
        default=12,
        lower=1,
        upper=50,
    )
    idle_ttl = _bounded_float(
        os.environ.get("PENNY_SHARED_WHISPER_IDLE_TTL_SECONDS", "300"),
        default=300.0,
        lower=0.0,
        upper=3600.0,
    )
    model_id, model_revision = primary_identity()
    guard = MacMemoryGuard(min_free_percent=min_free_percent)

    def whisper_factory():
        return SubprocessWorker(
            model_path=model_path,
            model_id=WHISPER_MODEL_ID,
            model_revision=WHISPER_MODEL_REVISION,
        )

    def worker_factory():
        if model_id == PARAKEET_ID:
            from .parakeet_process import ParakeetWorker

            python_path = os.environ.get("PENNY_PARAKEET_PYTHON", "")
            if not Path(python_path).is_absolute() or not Path(python_path).is_file():
                raise ValueError("parakeet_python_unavailable")
            return ParakeetWorker(model_path=parakeet_path(), python_path=python_path)
        return whisper_factory()

    return SharedWhisperSupervisor(
        worker_factory=worker_factory,
        fallback_worker_factory=whisper_factory if model_id == PARAKEET_ID else None,
        memory_guard=guard,
        grace_seconds=30.0,
        idle_ttl_seconds=idle_ttl,
        model_id=model_id,
        model_revision=model_revision,
    )


def _bounded_int(value: str, *, default: int, lower: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(lower, min(upper, parsed))


def _bounded_float(value: str, *, default: float, lower: float, upper: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(lower, min(upper, parsed))


def main() -> None:
    try:
        from setproctitle import setproctitle

        setproctitle("Penny Shared Whisper")
    except Exception:  # noqa: BLE001, S110 - retain optional process-title behavior
        pass
    supervisor = build_supervisor_from_environment()
    pilot_store = None
    if pilot_root := os.environ.get("PENNY_APPLE_PILOT_DIR"):
        from apple_pilot import AsyncPilotCapture, PilotStore

        try:
            pilot_store = AsyncPilotCapture(PilotStore(Path(pilot_root)))
        except Exception as exc:  # noqa: BLE001 - optional shadow cannot break primary ASR
            # Optional shadow storage cannot take the primary ASR service down.
            print(f"apple_pilot_initialization_failed:{type(exc).__name__}", flush=True)
    app = create_app(
        supervisor,
        auth_token=os.environ.get("PENNY_SHARED_WHISPER_TOKEN", ""),
        pilot_store=pilot_store,
        model_id=primary_identity()[0],
        model_revision=primary_identity()[1],
        allow_whisper_fallback=primary_identity()[0] == PARAKEET_ID,
    )
    stop = threading.Event()

    def reap_idle() -> None:
        while not stop.wait(1.0):
            supervisor.expire_idle()

    threading.Thread(
        target=reap_idle, name="shared-whisper-idle-reaper", daemon=True
    ).start()
    app.run(
        host=os.environ.get("PENNY_SHARED_WHISPER_HOST", "0.0.0.0"),
        port=_bounded_int(
            os.environ.get("PENNY_SHARED_WHISPER_PORT", "10311"),
            default=10311,
            lower=1024,
            upper=65535,
        ),
        threaded=True,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
