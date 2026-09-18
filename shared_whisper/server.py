"""HTTP adapter and launch entry point for Penny Shared Whisper."""

from __future__ import annotations

import hmac
import os
import tempfile
import threading
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
from .supervisor import SharedWhisperSupervisor
from .worker import MacMemoryGuard, SubprocessWorker


def create_app(
    supervisor: SharedWhisperSupervisor,
    *,
    auth_token: str,
    model_id: str = WHISPER_MODEL_ID,
    model_revision: str = WHISPER_MODEL_REVISION,
    temp_dir: Path | None = None,
) -> Flask:
    """Create the authenticated OpenAI-compatible shared service."""

    app = Flask("penny-shared-whisper")
    app.config["SHARED_WHISPER_TEMP_DIR"] = temp_dir

    @app.before_request
    def _expire_idle_worker() -> None:
        supervisor.expire_idle()

    @app.get("/health")
    def health():
        payload = {"service": "penny-shared-whisper", **supervisor.status()}
        return jsonify(payload)

    @app.get("/ready")
    def ready():
        payload = {"service": "penny-shared-whisper", **supervisor.status()}
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
        if incoming_model and incoming_model != model_id:
            return jsonify({"error": {"code": "model_mismatch"}}), 400
        upload = request.files.get("file")
        if upload is None:
            return jsonify({"error": {"code": "file_required"}}), 400

        path = _save_upload(upload.filename, upload.stream, temp_dir)
        try:
            result = supervisor.handle_request(
                client,
                audio_path=str(path),
                options=_form_options(),
            )
        except WhisperPreempted as exc:
            return _error_response(exc, 409)
        except (WhisperBusy, WhisperUnavailable) as exc:
            return _error_response(exc, 503)
        except WhisperProtocolError as exc:
            return _error_response(exc, 502)
        finally:
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
        if key in {"model", "response_format"}:
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
                    **(
                        {"request_id": error.request_id}
                        if error.request_id
                        else {}
                    ),
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
    guard = MacMemoryGuard(min_free_percent=min_free_percent)

    def worker_factory():
        return SubprocessWorker(
            model_path=model_path,
            model_id=WHISPER_MODEL_ID,
            model_revision=WHISPER_MODEL_REVISION,
        )

    return SharedWhisperSupervisor(
        worker_factory=worker_factory,
        memory_guard=guard,
        grace_seconds=30.0,
        idle_ttl_seconds=idle_ttl,
        model_id=WHISPER_MODEL_ID,
        model_revision=WHISPER_MODEL_REVISION,
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
    except Exception:
        pass
    supervisor = build_supervisor_from_environment()
    app = create_app(
        supervisor,
        auth_token=os.environ.get("PENNY_SHARED_WHISPER_TOKEN", ""),
    )
    stop = threading.Event()

    def reap_idle() -> None:
        while not stop.wait(1.0):
            supervisor.expire_idle()

    threading.Thread(target=reap_idle, name="shared-whisper-idle-reaper", daemon=True).start()
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
