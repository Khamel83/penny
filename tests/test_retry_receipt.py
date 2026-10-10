"""Retry-receipt placement and retention boundaries."""

from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path

import pytest

from config import WHISPER_MODEL_ID, WHISPER_MODEL_REVISION
from shared_whisper import retry_receipt
from shared_whisper.backends import PARAKEET_ID, PARAKEET_REVISION
from shared_whisper.protocol import WhisperResult
from shared_whisper.server import create_app


def _receipt(
    root: Path,
    name: str,
    state: str,
    *,
    audio: bool = True,
    age_days: float = 0.0,
) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    if audio:
        (directory / "audio.wav").write_bytes(b"audio")
    receipt = directory / "receipt.json"
    receipt.write_text(json.dumps({"state": state}), encoding="utf-8")
    if age_days:
        stamp = time.time() - age_days * 86400
        os.utime(receipt, (stamp, stamp))
        os.utime(directory, (stamp, stamp))
    return receipt


def test_receipts_use_the_ssd_root_when_the_volume_is_available(monkeypatch, tmp_path):
    ssd_root = tmp_path / "penny-asr-runtime" / "asr-retries"
    monkeypatch.delenv("PENNY_ASR_RETRY_DIR", raising=False)
    monkeypatch.setattr(retry_receipt, "SSD_VOLUME", Path("/"))
    monkeypatch.setattr(retry_receipt, "SSD_RETRY_ROOT", ssd_root)
    audio = tmp_path / "excerpt.mp3"
    audio.write_bytes(b"audio")

    receipt, payload = retry_receipt.begin(audio, None, "penny")

    assert receipt.parent.parent == ssd_root
    assert payload["state"] == "retry_pending"
    assert (receipt.parent / "audio.mp3").read_bytes() == b"audio"


def test_configured_retry_dir_wins_over_the_ssd_default(monkeypatch, tmp_path):
    configured = tmp_path / "configured"
    monkeypatch.setenv("PENNY_ASR_RETRY_DIR", str(configured))
    monkeypatch.setattr(retry_receipt, "SSD_VOLUME", Path("/"))
    monkeypatch.setattr(retry_receipt, "SSD_RETRY_ROOT", tmp_path / "ssd-retries")
    audio = tmp_path / "excerpt.wav"
    audio.write_bytes(b"audio")

    receipt, _ = retry_receipt.begin(audio, None, "penny")

    assert receipt.parent.parent == configured


def test_receipts_fall_back_to_home_without_the_volume(monkeypatch, tmp_path):
    monkeypatch.delenv("PENNY_ASR_RETRY_DIR", raising=False)
    monkeypatch.setattr(retry_receipt, "SSD_VOLUME", tmp_path / "unmounted")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    audio = tmp_path / "excerpt.wav"
    audio.write_bytes(b"audio")

    receipt, _ = retry_receipt.begin(audio, None, "penny")

    assert receipt.parent.parent == tmp_path / "home" / ".penny" / "asr-retries"


def test_plain_directory_is_not_a_mounted_volume(monkeypatch, tmp_path):
    monkeypatch.setattr(retry_receipt, "SSD_VOLUME", tmp_path)

    assert retry_receipt.ssd_root_available() is False


def test_relative_retry_dir_is_rejected(monkeypatch):
    monkeypatch.setenv("PENNY_ASR_RETRY_DIR", "relative/retries")

    with pytest.raises(ValueError, match="absolute_retry_receipt_root_required"):
        retry_receipt.retry_root()


def test_terminal_receipt_releases_audio_and_keeps_receipt(tmp_path):
    root = tmp_path / "retries"
    root.mkdir()
    receipt = _receipt(root, "pending", "retry_pending")
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["state"] = "retry_completed"

    retry_receipt.save(receipt, payload)

    assert not (receipt.parent / "audio.wav").exists()
    assert json.loads(receipt.read_text(encoding="utf-8"))["state"] == "retry_completed"


def test_pending_review_receipts_are_never_pruned_or_released(tmp_path):
    root = tmp_path / "retries"
    root.mkdir()
    long_review = _receipt(
        root, "long-review", "quality_review_requires_bounded_excerpt", age_days=60
    )
    review = _receipt(root, "review", "quality_review", age_days=60)
    completed = _receipt(root, "completed", "retry_completed", audio=False, age_days=60)
    crashed = _receipt(root, "crashed", "retry_pending", age_days=60)
    orphan = root / "orphan"
    orphan.mkdir()
    (orphan / "audio.wav").write_bytes(b"audio")
    stamp = time.time() - 60 * 86400
    os.utime(orphan, (stamp, stamp))

    removed = retry_receipt.prune(root)

    assert sorted(directory.name for directory in removed) == ["completed", "crashed", "orphan"]
    assert long_review.exists()
    assert (long_review.parent / "audio.wav").exists()
    assert review.exists()
    assert not completed.exists()
    assert not crashed.exists()
    assert not orphan.exists()


def test_saving_a_receipt_prunes_expired_directories(tmp_path):
    root = tmp_path / "retries"
    root.mkdir()
    expired = _receipt(root, "expired", "retry_completed", audio=False, age_days=30)
    fresh = _receipt(root, "fresh", "retry_pending")
    review = _receipt(root, "review", "quality_review", age_days=90)
    live = root / "live" / "receipt.json"
    live.parent.mkdir()

    retry_receipt.save(live, {"state": "retry_completed"})

    assert not expired.exists()
    assert fresh.exists()
    assert review.exists()
    assert live.exists()


def test_pruning_uses_receipt_directory_age(tmp_path):
    root = tmp_path / "retries"
    receipt = _receipt(root, "expired", "retry_completed", audio=False)
    now = time.time()
    os.utime(receipt, (now, now))
    os.utime(receipt.parent, (now - 30 * 86400, now - 30 * 86400))

    retry_receipt.prune(root, now=now)

    assert not receipt.parent.exists()


def test_completed_server_retry_releases_the_copied_audio(monkeypatch, tmp_path):
    monkeypatch.setenv("PENNY_ASR_RETRY_DIR", str(tmp_path / "retries"))

    class Supervisor:
        def expire_idle(self):
            pass

        def handle_request(self, client, *, audio_path, options):
            if options.get("_backend") == "whisper":
                return WhisperResult(
                    "Correct words.",
                    [{"start": 0, "end": 1, "text": "Correct words."}],
                    WHISPER_MODEL_ID,
                    WHISPER_MODEL_REVISION,
                    "fallback",
                )
            return WhisperResult(
                "loop " * 8,
                [{"start": 0, "end": 1, "text": "loop " * 8}],
                PARAKEET_ID,
                PARAKEET_REVISION,
                "primary",
            )

    monkeypatch.setattr("shared_whisper.retry.audio_duration", lambda path: 300)
    app = create_app(
        Supervisor(),
        auth_token="secret",
        model_id=PARAKEET_ID,
        model_revision=PARAKEET_REVISION,
        allow_whisper_fallback=True,
    )

    response = app.test_client().post(
        "/v1/audio/transcriptions",
        headers={"Authorization": "Bearer secret", "X-Whisper-Client": "penny"},
        data={"model": PARAKEET_ID, "file": (io.BytesIO(b"audio"), "excerpt.wav")},
    )

    assert response.status_code == 200
    receipts = list((tmp_path / "retries").glob("*/receipt.json"))
    assert len(receipts) == 1
    assert json.loads(receipts[0].read_text(encoding="utf-8"))["state"] == "retry_completed"
    assert list(receipts[0].parent.glob("audio.*")) == []
