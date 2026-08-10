from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from config import (
    WHISPER_MODEL_ID,
    WHISPER_MODEL_REPOSITORY,
    WHISPER_MODEL_REVISION,
)
from transcript_quality import (
    clear_model_verification_cache,
    ModelUnavailableError,
    resolve_whisper_model,
    transcribe_with_quality,
    verify_pinned_model,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pin_whisper_model import ModelProvisionError, provision_pinned_model  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(model: Path) -> None:
    files = []
    for path in sorted(model.rglob("*")):
        if not path.is_file() or path.name in {"manifest.json", ".penny-committed"}:
            continue
        os.chmod(path, 0o400)
        relative = path.relative_to(model).as_posix()
        files.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    manifest = {
        "schema_version": 1,
        "repository": WHISPER_MODEL_REPOSITORY,
        "revision": WHISPER_MODEL_REVISION,
        "config_path": "config.json",
        "weights_path": "weights.npz",
        "files": files,
    }
    (model / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.chmod(model / "manifest.json", 0o400)
    os.chmod(model, 0o700)
    marker = {
        "schema_version": 1,
        "repository": WHISPER_MODEL_REPOSITORY,
        "revision": WHISPER_MODEL_REVISION,
        "manifest_sha256": _sha256(model / "manifest.json"),
    }
    (model / ".penny-committed").write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.chmod(model / ".penny-committed", 0o400)


def _fake_model(tmp_path: Path) -> Path:
    model = tmp_path / "models" / WHISPER_MODEL_REVISION
    model.mkdir(parents=True)
    (model / "config.json").write_text(
        json.dumps({"model_type": "whisper", "n_mels": 80}), encoding="utf-8"
    )
    (model / "weights.npz").write_bytes(b"fake model weights")
    _write_manifest(model)
    return model


def _tamper_weights(model: Path) -> None:
    path = model / "weights.npz"
    os.chmod(path, 0o600)
    path.write_bytes(b"tampered")
    os.chmod(path, 0o400)


def _tamper_config(model: Path) -> None:
    path = model / "config.json"
    os.chmod(path, 0o600)
    path.write_text(json.dumps({"model_type": "not-whisper"}), encoding="utf-8")
    os.chmod(path, 0o400)


def test_verify_pinned_model_returns_stable_receipt(tmp_path: Path):
    model = _fake_model(tmp_path)

    receipt = verify_pinned_model(model, WHISPER_MODEL_REVISION)

    assert receipt.path == model
    assert receipt.repository == WHISPER_MODEL_REPOSITORY
    assert receipt.revision == WHISPER_MODEL_REVISION
    assert receipt.model_identity == WHISPER_MODEL_ID
    assert receipt.weights_path == model / "weights.npz"
    assert receipt.weights_size == len(b"fake model weights")
    assert receipt.weights_sha256 == _sha256(model / "weights.npz")
    assert receipt.manifest_sha256 == _sha256(model / "manifest.json")


@pytest.mark.parametrize(
    "mutator",
    [
        _tamper_weights,
        _tamper_config,
        lambda model: (model / "manifest.json").unlink(),
    ],
)
def test_verify_pinned_model_rejects_invalid_assets(tmp_path: Path, mutator):
    model = _fake_model(tmp_path)
    mutator(model)

    with pytest.raises(ModelUnavailableError):
        verify_pinned_model(model, WHISPER_MODEL_REVISION)


def test_verify_pinned_model_rejects_symlinked_asset(tmp_path: Path):
    model = _fake_model(tmp_path)
    outside = tmp_path / "outside.npz"
    outside.write_bytes(b"outside")
    (model / "weights.npz").unlink()
    (model / "weights.npz").symlink_to(outside)

    with pytest.raises(ModelUnavailableError):
        verify_pinned_model(model, WHISPER_MODEL_REVISION)


def test_verify_pinned_model_requires_private_read_only_single_link_assets(tmp_path: Path):
    model = _fake_model(tmp_path)
    os.chmod(model / "weights.npz", 0o600)
    with pytest.raises(ModelUnavailableError):
        verify_pinned_model(model, WHISPER_MODEL_REVISION)

    os.chmod(model / "weights.npz", 0o400)
    hardlink = model / "weights-hardlink.npz"
    os.link(model / "weights.npz", hardlink)
    with pytest.raises(ModelUnavailableError):
        verify_pinned_model(model, WHISPER_MODEL_REVISION)


def test_verify_pinned_model_rejects_special_files_and_non_private_dirs(tmp_path: Path):
    model = _fake_model(tmp_path)
    os.chmod(model, 0o755)
    with pytest.raises(ModelUnavailableError):
        verify_pinned_model(model, WHISPER_MODEL_REVISION)

    os.chmod(model, 0o700)
    fifo = model / "unexpected.fifo"
    os.mkfifo(fifo)
    with pytest.raises(ModelUnavailableError):
        verify_pinned_model(model, WHISPER_MODEL_REVISION)


def test_resolve_whisper_model_rejects_repository_ids_and_relative_paths(tmp_path: Path):
    with pytest.raises(ModelUnavailableError):
        resolve_whisper_model(WHISPER_MODEL_REPOSITORY, tmp_path)
    with pytest.raises(ModelUnavailableError):
        resolve_whisper_model("models/whisper", tmp_path)


def test_transcribe_passes_verified_local_path_and_never_repository_id(
    monkeypatch, tmp_path: Path
):
    model = _fake_model(tmp_path)
    call = Mock(return_value={"text": "buy milk"})
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setitem(sys.modules, "mlx_whisper", SimpleNamespace(transcribe=call))

    result = transcribe_with_quality(
        tmp_path / "audio.m4a", model=str(model)
    )

    assert result.text == "buy milk"
    assert call.call_args.kwargs["path_or_hf_repo"] == str(model)
    assert "/" in call.call_args.kwargs["path_or_hf_repo"]


def test_transcribe_requires_offline_runtime(monkeypatch, tmp_path: Path):
    model = _fake_model(tmp_path)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)

    with pytest.raises(ModelUnavailableError):
        transcribe_with_quality(tmp_path / "audio.m4a", model=str(model))


def _fake_snapshot(tmp_path: Path) -> Path:
    source = tmp_path / "hf-snapshot"
    source.mkdir()
    (source / "config.json").write_text(
        json.dumps({"model_type": "whisper", "n_mels": 80}), encoding="utf-8"
    )
    blob = tmp_path / "weights.blob"
    blob.write_bytes(b"weights from cache")
    (source / "weights.npz").symlink_to(blob)
    return source


def test_provision_is_atomic_dereferenced_and_idempotent(tmp_path: Path):
    source = _fake_snapshot(tmp_path)
    destination = tmp_path / "owned" / WHISPER_MODEL_REVISION
    downloader = Mock(return_value=source)

    first = provision_pinned_model(destination=destination, downloader=downloader)

    assert first.path == destination
    assert (destination / "weights.npz").is_file()
    assert not (destination / "weights.npz").is_symlink()
    assert (destination / "manifest.json").is_file()
    assert list(destination.parent.glob("*.staging-*")) == []

    second = provision_pinned_model(destination=destination, downloader=downloader)
    assert second.manifest_sha256 == first.manifest_sha256
    downloader.assert_called_once()


def test_provision_never_overwrites_mismatched_final(tmp_path: Path):
    source = _fake_snapshot(tmp_path)
    destination = tmp_path / "owned" / WHISPER_MODEL_REVISION
    destination.mkdir(parents=True)
    (destination / "config.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ModelProvisionError, match="existing_destination_invalid"):
        provision_pinned_model(destination=destination, snapshot_path=source)


def test_provision_rejects_wrong_revision_before_network(tmp_path: Path):
    downloader = Mock()

    with pytest.raises(ModelProvisionError, match="model_pin_mismatch"):
        provision_pinned_model(
            revision="wrong-revision",
            destination=tmp_path / "wrong-revision",
            downloader=downloader,
        )
    downloader.assert_not_called()


def test_provision_detects_source_mutation_between_hashes(tmp_path: Path, monkeypatch):
    source = _fake_snapshot(tmp_path)
    blob = tmp_path / "weights.blob"
    destination = tmp_path / "owned" / WHISPER_MODEL_REVISION
    import pin_whisper_model as pin

    original_hash = pin._sha256
    calls = 0

    def mutate_after_first_hash(path: Path) -> str:
        nonlocal calls
        digest = original_hash(path)
        if path == blob:
            calls += 1
            if calls == 1:
                path.write_bytes(b"changed while copying")
        return digest

    monkeypatch.setattr(pin, "_sha256", mutate_after_first_hash)
    with pytest.raises(ModelProvisionError, match="source_changed"):
        provision_pinned_model(destination=destination, snapshot_path=source)
    assert not destination.exists()


def test_post_publish_verification_failure_quarantines_target(tmp_path: Path, monkeypatch):
    source = _fake_snapshot(tmp_path)
    destination = tmp_path / "owned" / WHISPER_MODEL_REVISION
    import pin_whisper_model as pin

    real_verify = pin.verify_pinned_model

    def fail_only_after_publish(path, *args, **kwargs):
        if Path(path).name == WHISPER_MODEL_REVISION:
            raise ModelUnavailableError("synthetic_post_publish_failure")
        return real_verify(path, *args, **kwargs)

    monkeypatch.setattr(pin, "verify_pinned_model", fail_only_after_publish)
    with pytest.raises(ModelProvisionError, match="published_model_verification_failed"):
        provision_pinned_model(destination=destination, snapshot_path=source)
    assert not destination.exists()
    assert list(destination.parent.glob(f".{WHISPER_MODEL_REVISION}.invalid-*"))


def test_runtime_resolution_reuses_verified_receipt_until_assets_change(tmp_path: Path, monkeypatch):
    model = _fake_model(tmp_path)
    clear_model_verification_cache()
    import transcript_quality as quality

    real_hash = quality._sha256_file
    hash_calls = 0

    def counted_hash(path: Path) -> str:
        nonlocal hash_calls
        hash_calls += 1
        return real_hash(path)

    monkeypatch.setattr(quality, "_sha256_file", counted_hash)
    resolve_whisper_model(str(model))
    first_count = hash_calls
    resolve_whisper_model(str(model))
    assert first_count > 0
    assert hash_calls == first_count
    weights = model / "weights.npz"
    os.chmod(weights, 0o600)
    weights.write_bytes(b"tampered")
    os.chmod(weights, 0o400)
    with pytest.raises(ModelUnavailableError):
        resolve_whisper_model(str(model))


def test_runtime_cache_rejects_same_length_tamper_with_restored_mtime(
    tmp_path: Path,
):
    model = _fake_model(tmp_path)
    clear_model_verification_cache()
    resolve_whisper_model(str(model))
    weights = model / "weights.npz"
    before = weights.stat()
    os.chmod(weights, 0o600)
    weights.write_bytes(b"tampered model weights")
    os.utime(weights, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.chmod(weights, 0o400)

    with pytest.raises(ModelUnavailableError):
        resolve_whisper_model(str(model))


def test_provision_rejects_symlink_ancestor_before_mkdir(tmp_path: Path):
    source = _fake_snapshot(tmp_path)
    outside = tmp_path / "outside"
    link = tmp_path / "owned"
    link.symlink_to(outside, target_is_directory=True)
    destination = link / "missing" / WHISPER_MODEL_REVISION

    with pytest.raises(ModelProvisionError, match="destination_parent_symlink"):
        provision_pinned_model(destination=destination, snapshot_path=source)
    assert not outside.exists()


def test_post_publish_failure_without_quarantine_stays_unaccepted(
    tmp_path: Path, monkeypatch
):
    source = _fake_snapshot(tmp_path)
    destination = tmp_path / "owned" / WHISPER_MODEL_REVISION
    import pin_whisper_model as pin

    real_verify = pin.verify_pinned_model
    real_replace = pin.os.replace

    def fail_only_after_publish(path, *args, **kwargs):
        if Path(path).name == WHISPER_MODEL_REVISION:
            raise ModelUnavailableError("synthetic_post_publish_failure")
        return real_verify(path, *args, **kwargs)

    def fail_quarantine(src, dst):
        if Path(dst).name.startswith(f".{WHISPER_MODEL_REVISION}.invalid-"):
            raise OSError("synthetic quarantine failure")
        return real_replace(src, dst)

    monkeypatch.setattr(pin, "verify_pinned_model", fail_only_after_publish)
    monkeypatch.setattr(pin.os, "replace", fail_quarantine)
    with pytest.raises(ModelProvisionError, match="published_model_verification_failed"):
        provision_pinned_model(destination=destination, snapshot_path=source)
    assert destination.exists()
    assert not (destination / ".penny-committed").exists()
    with pytest.raises(ModelUnavailableError):
        verify_pinned_model(destination, WHISPER_MODEL_REVISION)


def test_package_and_runtime_contract_are_exact():
    requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(
        encoding="utf-8"
    )
    assert 'mlx-whisper==0.4.3; sys_platform == "darwin"' in requirements
    assert 'snapshot_download' not in (
        Path(__file__).resolve().parents[1] / "transcript_quality.py"
    ).read_text(encoding="utf-8")
