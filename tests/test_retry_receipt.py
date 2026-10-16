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
    monkeypatch.setattr(retry_receipt, "SSD_VOLUME", tmp_path / "unmounted")
    monkeypatch.setattr(retry_receipt, "SSD_RETRY_ROOT", tmp_path / "ssd-retries")
    audio = tmp_path / "excerpt.wav"
    audio.write_bytes(b"audio")

    receipt, _ = retry_receipt.begin(audio, None, "penny")

    assert receipt.parent.parent == configured


def test_receipts_fail_closed_without_the_volume(monkeypatch, tmp_path):
    monkeypatch.delenv("PENNY_ASR_RETRY_DIR", raising=False)
    monkeypatch.setattr(retry_receipt, "SSD_VOLUME", tmp_path / "unmounted")
    audio = tmp_path / "excerpt.wav"
    audio.write_bytes(b"audio")

    with pytest.raises(RuntimeError, match="ssd_retry_volume_unavailable"):
        retry_receipt.begin(audio, None, "penny")


def test_plain_directory_is_not_a_mounted_volume(monkeypatch, tmp_path):
    monkeypatch.setattr(retry_receipt, "SSD_VOLUME", tmp_path)

    assert retry_receipt.ssd_root_available() is False


def test_explicit_ssd_path_fails_closed_when_mount_is_absent(monkeypatch, tmp_path):
    volume = tmp_path / "unmounted"
    monkeypatch.setattr(retry_receipt, "SSD_VOLUME", volume)
    monkeypatch.setenv("PENNY_ASR_RETRY_DIR", str(volume / "retries"))

    with pytest.raises(RuntimeError, match="ssd_retry_volume_unavailable"):
        retry_receipt.retry_root()
    assert not volume.exists()


def test_lost_mount_does_not_write_or_prune_an_existing_receipt(monkeypatch, tmp_path):
    receipt = _receipt(tmp_path, "terminal", "retry_completed", age_days=60)
    monkeypatch.setattr(retry_receipt, "SSD_VOLUME", tmp_path)
    before = receipt.read_bytes()

    with pytest.raises(RuntimeError, match="ssd_retry_volume_unavailable"):
        retry_receipt.save(receipt, {"state": "retry_failed"})
    assert retry_receipt.prune(tmp_path) == []
    assert receipt.read_bytes() == before
    assert (receipt.parent / "audio.wav").read_bytes() == b"audio"


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


def test_failed_terminal_receipt_releases_audio_and_keeps_receipt(tmp_path):
    root = tmp_path / "retries"
    root.mkdir()
    receipt = _receipt(root, "failed", "retry_pending")
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["state"] = "retry_failed"

    retry_receipt.save(receipt, payload)

    assert not (receipt.parent / "audio.wav").exists()
    assert json.loads(receipt.read_text(encoding="utf-8"))["state"] == "retry_failed"


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

    assert sorted(directory.name for directory in removed) == ["completed"]
    assert long_review.exists()
    assert (long_review.parent / "audio.wav").exists()
    assert review.exists()
    assert not completed.exists()
    assert crashed.exists()
    assert (crashed.parent / "audio.wav").exists()
    assert orphan.exists()


@pytest.mark.parametrize("payload", [{"state": "future_state"}, {"state": []}, {}, []])
def test_unknown_or_invalid_state_keeps_all_bytes(tmp_path, payload):
    receipt = _receipt(tmp_path, "unknown", "retry_completed", age_days=60)
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    old = time.time() - 60 * 86400
    os.utime(receipt, (old, old))
    before = {p.name: p.read_bytes() for p in receipt.parent.iterdir()}

    assert retry_receipt.prune(tmp_path) == []
    assert {p.name: p.read_bytes() for p in receipt.parent.iterdir()} == before


def test_malformed_receipt_keeps_audio(tmp_path):
    receipt = _receipt(tmp_path, "invalid", "retry_completed", age_days=60)
    receipt.write_bytes(b"incomplete-json{")

    assert retry_receipt.prune(tmp_path) == []
    assert (receipt.parent / "audio.wav").read_bytes() == b"audio"


@pytest.mark.parametrize("boundary", ["root", "directory", "receipt"])
def test_pruning_does_not_follow_symlinks(tmp_path, boundary):
    outside = tmp_path / "outside"
    receipt = _receipt(outside, "terminal", "retry_completed", age_days=60)
    root = tmp_path / "retries"
    if boundary == "root":
        root.symlink_to(outside, target_is_directory=True)
    else:
        root.mkdir()
        if boundary == "directory":
            (root / "linked").symlink_to(receipt.parent, target_is_directory=True)
        else:
            directory = root / "linked"
            directory.mkdir()
            (directory / "receipt.json").symlink_to(receipt)

    assert retry_receipt.prune(root) == []
    assert receipt.exists()
    assert (receipt.parent / "audio.wav").read_bytes() == b"audio"


def test_terminal_save_preserves_symlink_audio_and_target(tmp_path):
    receipt = _receipt(tmp_path, "terminal", "retry_pending", audio=False)
    target = tmp_path / "original.wav"
    target.write_bytes(b"original")
    link = receipt.parent / "audio.wav"
    link.symlink_to(target)

    retry_receipt.save(receipt, {"state": "retry_completed"})

    assert link.is_symlink()
    assert target.read_bytes() == b"original"


def test_failed_prune_does_not_report_removal(monkeypatch, tmp_path):
    receipt = _receipt(tmp_path, "terminal", "retry_completed", age_days=60)

    def denied(*args, **kwargs):
        raise PermissionError("retained")

    monkeypatch.setattr(retry_receipt.shutil, "rmtree", denied)
    assert retry_receipt.prune(tmp_path) == []
    assert receipt.exists()


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


def test_fresh_receipt_in_old_directory_is_retained(tmp_path):
    root = tmp_path / "retries"
    receipt = _receipt(root, "expired", "retry_completed", audio=False)
    now = time.time()
    os.utime(receipt, (now, now))
    os.utime(receipt.parent, (now - 30 * 86400, now - 30 * 86400))

    retry_receipt.prune(root, now=now)

    assert receipt.exists()


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
