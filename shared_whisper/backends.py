"""Pinned backend identities; selecting a model never loads it in the caller."""

from __future__ import annotations

import os
from pathlib import Path

from config import WHISPER_MODEL_ID, WHISPER_MODEL_REVISION, get_config

PARAKEET_REVISION = "ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15"
PARAKEET_ID = "mlx-community/parakeet-tdt-0.6b-v3@" + PARAKEET_REVISION


def primary_identity() -> tuple[str, str]:
    backend = os.environ.get("PENNY_SHARED_ASR_BACKEND")
    if backend is None:
        backend = getattr(get_config().shared_whisper, "backend", "whisper")
    if backend == "parakeet":
        return PARAKEET_ID, PARAKEET_REVISION
    if backend != "whisper":
        raise ValueError("unsupported_shared_asr_backend")
    return WHISPER_MODEL_ID, WHISPER_MODEL_REVISION


def parakeet_path() -> Path:
    value = os.environ.get("PENNY_PARAKEET_MODEL_PATH", "")
    path = Path(value).expanduser()
    if not value or not path.is_absolute():
        raise ValueError("absolute_parakeet_model_path_required")
    return path
