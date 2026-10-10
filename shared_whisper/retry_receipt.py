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
HOME_RETRY_ROOT = Path("~/.penny/asr-retries")
TERMINAL_STATES = frozenset({"retry_completed", "retry_failed"})
PENDING_REVIEW_STATES = frozenset(
    {"quality_review", "quality_review_requires_bounded_excerpt"}
)
RETENTION_DAYS = 14
SECONDS_PER_DAY = 86400


def ssd_root_available() -> bool:
    """True only while the external SSD volume is mounted.

    Copying retry audio onto the internal disk is never a valid fallback for
    bulk media, so an unmounted volume selects the home compatibility path.
    """
    try:
        return SSD_VOLUME.is_mount()
    except OSError:
        return False


def default_root() -> Path:
    if ssd_root_available():
        return SSD_RETRY_ROOT
    return HOME_RETRY_ROOT.expanduser()


def retry_root() -> Path:
    configured = os.environ.get("PENNY_ASR_RETRY_DIR")
    root = Path(configured).expanduser() if configured else default_root()
    if not root.is_absolute():
        raise ValueError("absolute_retry_receipt_root_required")
    return root


def release_audio(receipt: Path) -> list[Path]:
    """Delete a terminal receipt's copied audio; `receipt.json` is retained."""
    removed = []
    for audio in sorted(receipt.parent.glob("audio.*")):
        if audio.is_file():
            audio.unlink(missing_ok=True)
            removed.append(audio)
    return removed


def prune(
    root: Path,
    *,
    retention_days: int = RETENTION_DAYS,
    now: float | None = None,
) -> list[Path]:
    """Delete receipt directories older than `retention_days`.

    Pending operator review is preserved regardless of age; its audio copy is
    also never released. Returns the removed directories.
    """
    if retention_days < 1:
        raise ValueError("retention_days must be positive")
    removed: list[Path] = []
    if not root.is_dir():
        return removed
    cutoff = (time.time() if now is None else now) - retention_days * SECONDS_PER_DAY
    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        receipt = directory / "receipt.json"
        state = None
        try:
            state = json.loads(receipt.read_text(encoding="utf-8")).get("state")
        except (OSError, ValueError, AttributeError):
            state = None
        if state in PENDING_REVIEW_STATES:
            continue
        try:
            stamp = directory.stat().st_mtime
        except OSError:
            continue
        if stamp >= cutoff:
            continue
        shutil.rmtree(directory, ignore_errors=True)
        removed.append(directory)
    return removed


def save(path: Path, payload: dict):
    """Durably write a receipt, then enforce retry retention.

    A terminal receipt loses its copied audio, and directories past the
    retention window are pruned. Pending-review receipts keep both.
    """
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
