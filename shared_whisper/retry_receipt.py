"""Private second-model receipts, independent of canonical captures/deliveries."""

from __future__ import annotations
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid


def save(path: Path, payload: dict):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        os.chmod(temporary, 0o600)
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def begin(audio: Path, primary, client: str) -> tuple[Path, dict]:
    root = Path(
        os.environ.get("PENNY_ASR_RETRY_DIR", str(Path.home() / ".penny/asr-retries"))
    ).expanduser()
    if not root.is_absolute():
        raise ValueError("absolute_retry_receipt_root_required")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = root / str(uuid.uuid4())
    directory.mkdir(mode=0o700)
    destination = directory / ("audio" + audio.suffix)
    shutil.copyfile(audio, destination)
    destination.chmod(0o600)
    payload = {
        "client": client,
        "audio_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "primary": asdict(primary) if primary else None,
        "fallback": None,
        "state": "retry_pending",
    }
    path = directory / "receipt.json"
    save(path, payload)
    return path, payload
