"""Private second-model receipts, independent of canonical captures/deliveries."""

from __future__ import annotations
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid

SSD_VOLUME = Path("/Volumes/2TB_SSD")
SSD_RETRY_ROOT = SSD_VOLUME / "penny-asr-runtime" / "asr-retries"
TERMINAL_STATES = frozenset({"retry_completed", "retry_failed"})
RETENTION_DAYS = 14
SECONDS_PER_DAY = 86400


def ssd_root_available() -> bool:
    """True only while the external SSD volume is mounted."""
    try:
        return SSD_VOLUME.is_mount()
    except OSError:
        return False


def default_root() -> Path:
    if not ssd_root_available():
        raise RuntimeError("ssd_retry_volume_unavailable")
    return SSD_RETRY_ROOT


def retry_root() -> Path:
    configured = os.environ.get("PENNY_ASR_RETRY_DIR")
    root = Path(configured).expanduser() if configured else default_root()
    if not root.is_absolute():
        raise ValueError("absolute_retry_receipt_root_required")
    if root.is_relative_to(SSD_VOLUME) and not ssd_root_available():
        raise RuntimeError("ssd_retry_volume_unavailable")
    return root


def release_audio(receipt: Path) -> list[Path]:
    """Delete a terminal receipt's copied audio; `receipt.json` is retained."""
    removed = []
    if (receipt.parent.parent.is_symlink() or receipt.parent.is_symlink()
            or receipt.is_symlink()):
        return removed
    for audio in sorted(receipt.parent.glob("audio.*")):
        if audio.is_file() and not audio.is_symlink():
            audio.unlink(missing_ok=True)
            removed.append(audio)
    return removed


def prune(
    root: Path,
    *,
    retention_days: int = RETENTION_DAYS,
    now: float | None = None,
) -> list[Path]:
    """Delete terminal receipt directories older than `retention_days`.

    Pending, unknown and unreadable receipts stay regardless of age. A fresh
    receipt keeps its directory even when the directory itself is old.
    """
    if retention_days < 1:
        raise ValueError("retention_days must be positive")
    removed: list[Path] = []
    if (
        root.is_relative_to(SSD_VOLUME) and not ssd_root_available()
        or root.is_symlink()
        or not root.is_dir()
    ):
        return removed
    cutoff = (time.time() if now is None else now) - retention_days * SECONDS_PER_DAY
    try:
        directories = sorted(root.iterdir())
    except OSError:
        return removed
    for directory in directories:
        if directory.is_symlink() or not directory.is_dir():
            continue
        receipt = directory / "receipt.json"
        if receipt.is_symlink() or not receipt.is_file():
            continue
        try:
            state = json.loads(receipt.read_text(encoding="utf-8")).get("state")
        except (OSError, ValueError, AttributeError):
            continue
        if not isinstance(state, str) or state not in TERMINAL_STATES:
            continue
        try:
            stamp = receipt.stat().st_mtime
        except OSError:
            continue
        if stamp >= cutoff:
            continue
        try:
            shutil.rmtree(directory)
        except OSError:
            continue
        if not directory.exists():
            removed.append(directory)
    return removed


def save(path: Path, payload: dict):
    """Durably write a receipt, then enforce retry retention.

    A terminal receipt loses its copied audio, and directories past the
    retention window are pruned. Pending-review receipts keep both.
    """
    if path.is_relative_to(SSD_VOLUME) and not ssd_root_available():
        raise RuntimeError("ssd_retry_volume_unavailable")
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        os.chmod(temporary, 0o600)
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    if payload.get("state") in TERMINAL_STATES:
        release_audio(path)
    prune(path.parent.parent)


def begin(audio: Path, primary, client: str) -> tuple[Path, dict]:
    root = retry_root()
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
