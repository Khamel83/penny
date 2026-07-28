"""Deterministic quality checks for Penny Whisper transcripts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata


CONTROL_TOKEN_RE = re.compile(r"<\|[^|>]+\|>")
TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
MAX_CONSECUTIVE_TOKEN_REPETITION = 3
SUFFIX_TOKEN_WINDOW = 20
LOW_DIVERSITY_SUFFIX_MAX_UNIQUE_TOKENS = 2


@dataclass(frozen=True)
class QualityResult:
    passed: bool
    reason: str | None = None


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    quality: QualityResult
    attempts: int


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
    model: str | None = None,
) -> TranscriptionResult:
    """Transcribe at most twice and retain the selected Whisper text verbatim."""
    import mlx_whisper

    if model is None:
        from config import get_config

        model = get_config().voice_memos.whisper_model

    selected_text = ""
    for attempts, options in enumerate(
        (PRIMARY_TRANSCRIBE_OPTIONS, FALLBACK_TRANSCRIBE_OPTIONS), start=1
    ):
        response = mlx_whisper.transcribe(
            str(path),
            path_or_hf_repo=model,
            **options,
        )
        selected_text = str(response.get("text", ""))
        quality = evaluate_transcript(selected_text)
        if quality.passed:
            return TranscriptionResult(selected_text, quality, attempts)

    return TranscriptionResult(
        selected_text,
        QualityResult(False, "needs_review"),
        attempts,
    )
