"""Deterministic quality checks for Penny Whisper transcripts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata

from config import (
    WHISPER_MODEL_ID,
    WHISPER_MODEL_REPOSITORY,
    WHISPER_MODEL_REVISION,
)


CONTROL_TOKEN_RE = re.compile(r"<\|[^|>]+\|>")
TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
MAX_CONSECUTIVE_TOKEN_REPETITION = 3
SUFFIX_TOKEN_WINDOW = 20
LOW_DIVERSITY_SUFFIX_MAX_UNIQUE_TOKENS = 2
MAX_QUALITY_DETAIL_CHARACTERS = 255

_WEIGHT_FILENAMES = {
    "weights.npz",
    "weights.safetensors",
    "model.npz",
    "model.safetensors",
    "pytorch_model.bin",
}
_MODEL_VERIFICATION_CACHE: dict[
    tuple[str, str, str], tuple[tuple[tuple[str, int, int, int], ...], "ModelReceipt"]
] = {}


class ModelUnavailableError(RuntimeError):
    """Raised when Penny cannot prove that its pinned local model is usable."""


@dataclass(frozen=True)
class ModelFileReceipt:
    relative_path: str
    size: int
    sha256: str

    @property
    def path(self) -> str:
        return self.relative_path


@dataclass(frozen=True)
class ModelReceipt:
    """Stable, non-secret receipt for a verified local Whisper model."""

    path: Path
    repository: str
    revision: str
    config_sha256: str
    weights_path: Path
    weights_size: int
    weights_sha256: str
    manifest_sha256: str
    files: tuple[ModelFileReceipt, ...]

    @property
    def repo_id(self) -> str:
        return self.repository

    @property
    def repo(self) -> str:
        return self.repository

    @property
    def model_identity(self) -> str:
        return f"{self.repository}@{self.revision}"

    @property
    def model(self) -> str:
        return self.model_identity

    def as_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "repository": self.repository,
            "revision": self.revision,
            "model_identity": self.model_identity,
            "config_sha256": self.config_sha256,
            "weights_path": str(self.weights_path),
            "weights_size": self.weights_size,
            "weights_sha256": self.weights_sha256,
            "manifest_sha256": self.manifest_sha256,
            "files": [
                {
                    "path": file.relative_path,
                    "size": file.size,
                    "sha256": file.sha256,
                }
                for file in self.files
            ],
        }


@dataclass(frozen=True)
class QualityResult:
    passed: bool
    reason: str | None = None


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    quality: QualityResult
    attempts: int
    quality_detail: str | None = None


def _model_error(reason: str) -> ModelUnavailableError:
    # Keep operational errors useful without including model contents or
    # provider/network diagnostics in logs and health responses.
    return ModelUnavailableError(reason)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except (OSError, ValueError) as exc:
        raise _model_error(f"model_file_unreadable:{path.name}") from exc
    return digest.hexdigest()


def _safe_manifest_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise _model_error("model_manifest_invalid_path")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise _model_error("model_manifest_path_escape")
    normalized = candidate.as_posix()
    if normalized in {"", ".", "manifest.json"}:
        raise _model_error("model_manifest_invalid_path")
    return normalized


def _absolute_model_path(value: str | Path) -> Path:
    try:
        path = Path(value).expanduser()
    except (TypeError, ValueError) as exc:
        raise _model_error("model_path_invalid") from exc
    if not path.is_absolute():
        raise _model_error("model_path_must_be_absolute")
    # resolve(strict=True) both proves the path exists and catches a symlink in
    # any parent component.  A model provision is allowed to dereference cache
    # symlinks while copying; runtime is intentionally stricter.
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise _model_error("model_path_missing") from exc
    if resolved != path:
        raise _model_error("model_path_symlink")
    return path


def _validate_model_tree(path: Path) -> None:
    if not path.is_dir() or path.is_symlink():
        raise _model_error("model_path_not_directory")
    try:
        entries = list(path.rglob("*"))
    except OSError as exc:
        raise _model_error("model_tree_unreadable") from exc
    for entry in entries:
        if entry.is_symlink():
            raise _model_error("model_tree_symlink")
        if not entry.is_file() and not entry.is_dir():
            raise _model_error("model_tree_invalid_entry")


def _model_cache_signature(
    path: Path,
    receipt: ModelReceipt | None = None,
) -> tuple[tuple[str, int, int, int], ...]:
    """Return cheap metadata used to avoid rehashing a stable model per memo."""
    targets = [path, path / "manifest.json"]
    if receipt is not None:
        targets.extend(path / item.relative_path for item in receipt.files)
    signature: list[tuple[str, int, int, int]] = []
    for target in targets:
        try:
            stat = target.stat()
        except OSError:
            return ()
        signature.append((str(target), stat.st_ino, stat.st_size, stat.st_mtime_ns))
    return tuple(signature)


def verify_pinned_model(
    path: Path,
    expected_revision: str = WHISPER_MODEL_REVISION,
    *,
    expected_repository: str = WHISPER_MODEL_REPOSITORY,
    require_directory_name: bool = True,
) -> ModelReceipt:
    """Verify a provisioned model without importing MLX or touching the network.

    The manifest is a complete inventory of regular files in the model
    directory.  Every inventory entry is hash-checked and no unlisted files or
    symlinks are accepted, so a stale/partial cache cannot reach MLX.
    """
    model_path = _absolute_model_path(path)
    _validate_model_tree(model_path)
    manifest_path = model_path / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise _model_error("model_manifest_missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _model_error("model_manifest_invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise _model_error("model_manifest_version")

    repository = manifest.get(
        "repository", manifest.get("repo_id", manifest.get("repo"))
    )
    revision = manifest.get("revision")
    if repository != expected_repository:
        raise _model_error("model_repository_mismatch")
    if revision != expected_revision or (
        require_directory_name and model_path.name != expected_revision
    ):
        raise _model_error("model_revision_mismatch")

    raw_files = manifest.get("files")
    if isinstance(raw_files, dict):
        # Accept the compact mapping form used by older provisioning notes,
        # while normalizing it to the complete inventory representation.
        normalized_files: list[dict[str, object]] = []
        for relative_path, metadata in raw_files.items():
            if not isinstance(metadata, dict):
                raise _model_error("model_manifest_file_invalid")
            normalized_files.append({"path": relative_path, **metadata})
        raw_files = normalized_files
    if not isinstance(raw_files, list) or not raw_files:
        raise _model_error("model_manifest_files_missing")
    inventory: dict[str, ModelFileReceipt] = {}
    for raw_file in raw_files:
        if not isinstance(raw_file, dict):
            raise _model_error("model_manifest_file_invalid")
        relative_path = _safe_manifest_path(raw_file.get("path"))
        if relative_path in inventory:
            raise _model_error("model_manifest_duplicate_file")
        size = raw_file.get("size")
        digest = raw_file.get("sha256")
        if not isinstance(size, int) or size < 0:
            raise _model_error("model_manifest_size_invalid")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest.lower())
        ):
            raise _model_error("model_manifest_hash_invalid")
        target = model_path / relative_path
        try:
            target_resolved = target.resolve(strict=True)
        except OSError as exc:
            raise _model_error("model_file_missing") from exc
        if target_resolved != target or target.is_symlink() or not target.is_file():
            raise _model_error("model_file_symlink")
        try:
            actual_size = target.stat().st_size
        except OSError as exc:
            raise _model_error("model_file_unreadable") from exc
        if actual_size != size or _sha256_file(target) != digest.lower():
            raise _model_error(f"model_file_hash_mismatch:{relative_path}")
        inventory[relative_path] = ModelFileReceipt(relative_path, size, digest.lower())

    actual_files = {
        entry.relative_to(model_path).as_posix()
        for entry in model_path.rglob("*")
        if entry.is_file() and entry.name != "manifest.json"
    }
    if actual_files - set(inventory) != set():
        raise _model_error("model_manifest_unlisted_file")
    if set(inventory) - actual_files:
        raise _model_error("model_manifest_missing_file")

    config_path = _safe_manifest_path(manifest.get("config_path", "config.json"))
    if config_path != "config.json" or config_path not in inventory:
        raise _model_error("model_config_missing")
    try:
        config = json.loads((model_path / config_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _model_error("model_config_invalid") from exc
    if not isinstance(config, dict) or config.get("model_type") != "whisper":
        raise _model_error("model_config_type_mismatch")

    configured_weights = manifest.get("weights_path")
    if configured_weights is not None:
        weights_path = _safe_manifest_path(configured_weights)
        if weights_path not in inventory:
            raise _model_error("model_weights_missing")
    else:
        candidates = [
            relative
            for relative in inventory
            if Path(relative).name in _WEIGHT_FILENAMES
            or Path(relative).suffix.lower() in {".npz", ".safetensors"}
        ]
        if len(candidates) != 1:
            raise _model_error("model_weights_ambiguous")
        weights_path = candidates[0]
    if Path(weights_path).name not in _WEIGHT_FILENAMES and Path(weights_path).suffix.lower() not in {
        ".npz",
        ".safetensors",
    }:
        raise _model_error("model_weights_invalid")
    weights = inventory[weights_path]
    manifest_sha256 = _sha256_file(manifest_path)
    return ModelReceipt(
        path=model_path,
        repository=repository,
        revision=revision,
        config_sha256=inventory[config_path].sha256,
        weights_path=model_path / weights_path,
        weights_size=weights.size,
        weights_sha256=weights.sha256,
        manifest_sha256=manifest_sha256,
        files=tuple(inventory[key] for key in sorted(inventory)),
    )


def resolve_whisper_model(
    model: str | Path,
    model_root: Path | None = None,
    *,
    expected_revision: str = WHISPER_MODEL_REVISION,
    expected_repository: str = WHISPER_MODEL_REPOSITORY,
) -> Path:
    """Resolve only a verified absolute local model directory.

    ``model_root`` is accepted for compatibility with provisioning callers but
    is deliberately not used to resolve a repository ID.  Runtime code must
    receive the explicit path produced by configuration/provisioning.
    """
    del model_root
    if not isinstance(model, (str, Path)):
        raise _model_error("model_path_required")
    value = str(model)
    if not value or not Path(value).expanduser().is_absolute():
        raise _model_error("model_path_must_be_absolute")
    model_path = _absolute_model_path(Path(value))
    cache_key = (str(model_path), expected_repository, expected_revision)
    for key, (signature, receipt) in tuple(_MODEL_VERIFICATION_CACHE.items()):
        if key == cache_key and signature == _model_cache_signature(model_path, receipt):
            return receipt.path
    receipt = verify_pinned_model(
        model_path,
        expected_revision,
        expected_repository=expected_repository,
    )
    _MODEL_VERIFICATION_CACHE[cache_key] = (
        _model_cache_signature(model_path, receipt),
        receipt,
    )
    return receipt.path


def clear_model_verification_cache() -> None:
    """Clear the process-local runtime receipt cache (primarily for tests)."""
    _MODEL_VERIFICATION_CACHE.clear()


PRIMARY_TRANSCRIBE_OPTIONS = {
    "language": "en",
    "task": "transcribe",
    "condition_on_previous_text": False,
}
FALLBACK_TRANSCRIBE_OPTIONS = {
    **PRIMARY_TRANSCRIBE_OPTIONS,
    "temperature": 0.0,
}


def _normalized_tokens(text: str) -> list[str]:
    """Return a normalized inspection view without changing the source text."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return TOKEN_RE.findall(normalized)


def evaluate_transcript(text: str) -> QualityResult:
    """Evaluate transcript quality without modifying its content."""
    if not text or not text.strip():
        return QualityResult(False, "empty_output")
    if CONTROL_TOKEN_RE.search(text):
        return QualityResult(False, "control_token")

    tokens = _normalized_tokens(text)
    if not tokens:
        return QualityResult(False, "empty_output")

    consecutive = 1
    for previous, current in zip(tokens, tokens[1:]):
        consecutive = consecutive + 1 if current == previous else 1
        if consecutive >= MAX_CONSECUTIVE_TOKEN_REPETITION:
            return QualityResult(False, "consecutive_token_repetition")

    suffix = tokens[-SUFFIX_TOKEN_WINDOW:]
    if (
        len(suffix) == SUFFIX_TOKEN_WINDOW
        and len(set(suffix)) <= LOW_DIVERSITY_SUFFIX_MAX_UNIQUE_TOKENS
    ):
        return QualityResult(False, "low_diversity_suffix")

    return QualityResult(True)


def transcribe_with_quality(
    path: Path,
    *,
    model: str | Path | None = None,
) -> TranscriptionResult:
    """Transcribe at most twice using a verified local model.

    Validation and the offline guard deliberately run before importing MLX so
    a missing or invalid asset cannot trigger Hugging Face repository lookup.
    """
    if model is None:
        from config import get_config

        model = get_config().voice_memos.whisper_model_path

    if os.environ.get("HF_HUB_OFFLINE") != "1":
        raise _model_error("HF_HUB_OFFLINE_must_equal_1")
    model_path = resolve_whisper_model(model)

    import mlx_whisper

    selected_text = ""
    failure_reasons: list[str] = []
    for attempts, options in enumerate(
        (PRIMARY_TRANSCRIBE_OPTIONS, FALLBACK_TRANSCRIBE_OPTIONS), start=1
    ):
        response = mlx_whisper.transcribe(
            str(path),
            path_or_hf_repo=str(model_path),
            **options,
        )
        selected_text = str(response.get("text", ""))
        quality = evaluate_transcript(selected_text)
        if quality.passed:
            return TranscriptionResult(selected_text, quality, attempts)
        failure_reasons.append(quality.reason or "unknown_quality_failure")

    quality_detail = ";".join(
        f"attempt_{index}={reason}"
        for index, reason in enumerate(failure_reasons, start=1)
    )[:MAX_QUALITY_DETAIL_CHARACTERS]
    return TranscriptionResult(
        selected_text,
        QualityResult(False, "needs_review"),
        attempts,
        quality_detail,
    )
