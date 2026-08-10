#!/usr/bin/env python3
"""Provision and verify Penny's pinned MLX Whisper model.

This is the only Phase A command that may resolve a Hugging Face repository.
Runtime services receive a Penny-owned absolute directory and run with
``HF_HUB_OFFLINE=1``.  Provisioning stages on the destination filesystem,
dereferences cache symlinks, verifies every copied byte, and atomically
publishes a complete manifest-backed directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    DEFAULT_WHISPER_MODEL_PATH,
    WHISPER_MODEL_REPOSITORY,
    WHISPER_MODEL_REVISION,
)
from transcript_quality import ModelReceipt, ModelUnavailableError, verify_pinned_model  # noqa: E402


class ModelProvisionError(RuntimeError):
    """Raised when a pinned model cannot be safely staged or published."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ModelProvisionError(f"source_unreadable:{path.name}") from exc
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    try:
        with path.open("rb") as handle:
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ModelProvisionError(f"fsync_failed:{path.name}") from exc


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ModelProvisionError("directory_fsync_failed") from exc


def _fsync_tree(root: Path) -> None:
    """Flush staged files' directory entries before the atomic publish."""
    for directory in sorted(
        (entry for entry in root.rglob("*") if entry.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        _fsync_directory(directory)
    _fsync_directory(root)


def _absolute_directory(path: Path | str, *, label: str) -> Path:
    value = Path(path).expanduser()
    if not value.is_absolute():
        raise ModelProvisionError(f"{label}_must_be_absolute")
    return value


def _copy_file_dereferenced(source: Path, destination: Path) -> None:
    try:
        resolved_source = source.resolve(strict=True)
    except OSError as exc:
        raise ModelProvisionError(f"source_missing:{source.name}") from exc
    if not resolved_source.is_file():
        raise ModelProvisionError(f"source_not_regular_file:{source.name}")
    try:
        before_signature = resolved_source.stat()
        before_hash = _sha256(resolved_source)
    except OSError as exc:
        raise ModelProvisionError(f"source_unreadable:{source.name}") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with resolved_source.open("rb") as source_handle, destination.open("wb") as destination_handle:
            while True:
                chunk = source_handle.read(1024 * 1024)
                if not chunk:
                    break
                destination_handle.write(chunk)
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
    except OSError as exc:
        raise ModelProvisionError(f"copy_failed:{source.name}") from exc
    try:
        resolved_after = source.resolve(strict=True)
        after_signature = resolved_after.stat()
        source_hash = _sha256(resolved_after)
    except OSError as exc:
        raise ModelProvisionError(f"source_changed:{source.name}") from exc
    if (
        resolved_after != resolved_source
        or before_signature.st_ino != after_signature.st_ino
        or before_signature.st_size != after_signature.st_size
        or before_signature.st_mtime_ns != after_signature.st_mtime_ns
        or before_hash != source_hash
    ):
        raise ModelProvisionError(f"source_changed:{source.name}")
    destination_hash = _sha256(destination)
    os.chmod(destination, 0o400)
    if source_hash != destination_hash or after_signature.st_size != destination.stat().st_size:
        raise ModelProvisionError(f"copy_hash_mismatch:{source.name}")


def _copy_snapshot(source: Path, staging: Path) -> list[dict[str, object]]:
    try:
        source_root = source.resolve(strict=True)
    except OSError as exc:
        raise ModelProvisionError("snapshot_missing") from exc
    if not source_root.is_dir():
        raise ModelProvisionError("snapshot_not_directory")
    files: list[dict[str, object]] = []
    try:
        entries = sorted(source_root.rglob("*"), key=lambda item: item.as_posix())
    except OSError as exc:
        raise ModelProvisionError("snapshot_unreadable") from exc
    for entry in entries:
        relative = entry.relative_to(source_root)
        target = staging / relative
        if entry.is_symlink():
            # Symlinked files are common in the HF cache.  Resolve and copy the
            # bytes into the Penny-owned tree; never publish the link itself.
            resolved = entry.resolve(strict=True)
            if resolved.is_dir():
                for nested in sorted(
                    resolved.rglob("*"), key=lambda item: item.as_posix()
                ):
                    nested_target = target / nested.relative_to(resolved)
                    if nested.is_dir():
                        nested_target.mkdir(parents=True, exist_ok=True)
                    elif nested.is_file() or nested.is_symlink():
                        _copy_file_dereferenced(nested, nested_target)
                    else:
                        raise ModelProvisionError(
                            f"snapshot_invalid_entry:{nested.name}"
                        )
                target.mkdir(parents=True, exist_ok=True)
                continue
            _copy_file_dereferenced(entry, target)
        elif entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif entry.is_file():
            _copy_file_dereferenced(entry, target)
        else:
            raise ModelProvisionError(f"snapshot_invalid_entry:{relative}")
    for path in sorted(staging.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_dir():
            try:
                os.chmod(path, 0o700)
            except OSError as exc:
                raise ModelProvisionError(f"staging_permissions_failed:{path.name}") from exc
        if path.is_file() and path.name != "manifest.json":
            files.append(
                {
                    "path": path.relative_to(staging).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    if not files:
        raise ModelProvisionError("snapshot_has_no_files")
    return files


def _validate_stage_assets(staging: Path, files: list[dict[str, object]]) -> tuple[str, str]:
    paths = {str(item["path"]) for item in files}
    if "config.json" not in paths:
        raise ModelProvisionError("snapshot_missing_config")
    try:
        config = json.loads((staging / "config.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelProvisionError("snapshot_invalid_config") from exc
    if not isinstance(config, dict) or config.get("model_type") != "whisper":
        raise ModelProvisionError("snapshot_config_not_whisper")
    candidates = [
        relative
        for relative in paths
        if Path(relative).name
        in {"weights.npz", "weights.safetensors", "model.npz", "model.safetensors", "pytorch_model.bin"}
        or Path(relative).suffix.lower() in {".npz", ".safetensors"}
    ]
    if len(candidates) != 1:
        raise ModelProvisionError("snapshot_weights_missing_or_ambiguous")
    return "config.json", sorted(candidates)[0]


def _write_manifest(
    staging: Path,
    *,
    repository: str,
    revision: str,
    files: list[dict[str, object]],
    config_path: str,
    weights_path: str,
) -> None:
    manifest = {
        "schema_version": 1,
        "repository": repository,
        "revision": revision,
        "config_path": config_path,
        "weights_path": weights_path,
        "files": sorted(files, key=lambda item: str(item["path"])),
    }
    manifest_path = staging / "manifest.json"
    try:
        with manifest_path.open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(manifest_path, 0o400)
    except OSError as exc:
        raise ModelProvisionError("manifest_write_failed") from exc


def provision_pinned_model(
    *,
    repository: str = WHISPER_MODEL_REPOSITORY,
    revision: str = WHISPER_MODEL_REVISION,
    destination: Path | str = DEFAULT_WHISPER_MODEL_PATH,
    snapshot_path: Path | str | None = None,
    downloader: Callable[..., str | Path] | None = None,
    cache_dir: Path | str | None = None,
) -> ModelReceipt:
    """Download/copy one exact revision and atomically publish its receipt.

    ``snapshot_path`` and ``downloader`` are test/offline seams.  Production
    callers omit both, which imports ``huggingface_hub`` only here and passes
    the explicit repository revision to ``snapshot_download``.
    """
    if repository != WHISPER_MODEL_REPOSITORY or revision != WHISPER_MODEL_REVISION:
        raise ModelProvisionError("model_pin_mismatch")
    target = _absolute_directory(destination, label="destination")
    if target.name != revision:
        raise ModelProvisionError("destination_must_end_with_revision")
    target_parent = target.parent
    try:
        parent_resolved = target_parent.resolve(strict=True)
    except OSError:
        parent_resolved = target_parent
    if parent_resolved != target_parent:
        raise ModelProvisionError("destination_parent_symlink")
    target_parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        try:
            return verify_pinned_model(target, revision, expected_repository=repository)
        except Exception as exc:
            raise ModelProvisionError("existing_destination_invalid") from exc

    if snapshot_path is not None:
        source = Path(snapshot_path).expanduser()
    else:
        if downloader is None:
            try:
                from huggingface_hub import snapshot_download
            except ImportError as exc:
                raise ModelProvisionError("huggingface_hub_not_installed") from exc
            downloader = snapshot_download
        kwargs: dict[str, object] = {
            "repo_id": repository,
            "revision": revision,
        }
        if cache_dir is not None:
            kwargs["cache_dir"] = str(Path(cache_dir).expanduser())
        try:
            source = Path(downloader(**kwargs))
        except Exception as exc:
            # Do not expose provider URLs, paths, or response bodies.
            raise ModelProvisionError("snapshot_download_failed") from exc

    try:
        stage = Path(
            tempfile.mkdtemp(prefix=f".{revision}.staging-", dir=str(target_parent))
        )
        os.chmod(stage, 0o700)
    except OSError as exc:
        raise ModelProvisionError("staging_create_failed") from exc
    try:
        files = _copy_snapshot(source, stage)
        config_path, weights_path = _validate_stage_assets(stage, files)
        _write_manifest(
            stage,
            repository=repository,
            revision=revision,
            files=files,
            config_path=config_path,
            weights_path=weights_path,
        )
        # Verify the complete staged inventory before it can become the
        # canonical path.  The staging basename is intentionally hidden, so
        # opt out only from that one path-name check.
        try:
            verify_pinned_model(
                stage,
                revision,
                expected_repository=repository,
                require_directory_name=False,
            )
        except (ModelUnavailableError, OSError) as exc:
            raise ModelProvisionError("staged_model_verification_failed") from exc
        _fsync_tree(stage)
        _fsync_directory(target_parent)
        try:
            os.replace(stage, target)
        except OSError as exc:
            raise ModelProvisionError("publish_failed") from exc
        _fsync_directory(target_parent)
        try:
            return verify_pinned_model(target, revision, expected_repository=repository)
        except Exception as exc:
            # Preserve the failed artifact for diagnosis without leaving an
            # invalid directory at the path future runtimes trust.
            quarantine = target_parent / f".{revision}.invalid-{uuid.uuid4().hex}"
            try:
                os.replace(target, quarantine)
                _fsync_directory(target_parent)
            except OSError:
                pass
            raise ModelProvisionError("published_model_verification_failed") from exc
    except Exception:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise


# Short wrappers make the provisioning seam easy to use from maintenance
# tools while keeping one implementation and one network boundary.  The
# positional source/destination form is useful for hermetic tests; production
# uses the explicit keyword form in ``main``.
def provision_model(
    snapshot_path: Path | str | None = None,
    destination: Path | str = DEFAULT_WHISPER_MODEL_PATH,
    **kwargs: object,
) -> ModelReceipt:
    return provision_pinned_model(
        snapshot_path=snapshot_path,
        destination=destination,
        **kwargs,
    )


pin_model = provision_model
pin_whisper_model = provision_model


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=WHISPER_MODEL_REPOSITORY)
    parser.add_argument("--revision", default=WHISPER_MODEL_REVISION)
    parser.add_argument(
        "--destination",
        type=Path,
        default=DEFAULT_WHISPER_MODEL_PATH,
        help="final Penny-owned model directory (must end with the revision)",
    )
    parser.add_argument(
        "--snapshot-path",
        "--source",
        dest="snapshot_path",
        type=Path,
        help="offline/test snapshot directory; skips Hugging Face download",
    )
    parser.add_argument("--cache-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = provision_pinned_model(
            repository=args.repository,
            revision=args.revision,
            destination=args.destination,
            snapshot_path=args.snapshot_path,
            cache_dir=args.cache_dir,
        )
    except ModelProvisionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
