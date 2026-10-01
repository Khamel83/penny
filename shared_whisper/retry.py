"""Bounded excerpts for explicitly requested second-model checks."""

from __future__ import annotations
import math
from pathlib import Path
import subprocess


def audio_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    duration = float(result.stdout.strip())
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("invalid_audio_duration")
    return duration


def extract_excerpt(
    source: Path, destination: Path, start: float, end: float, context: float = 5
) -> float:
    duration = audio_duration(source)
    if not all(math.isfinite(v) for v in (start, end, context)) or not (
        0 <= start < end <= duration
    ):
        raise ValueError("invalid_retry_range")
    if end - start > 600 or not 0 <= context <= 30:
        raise ValueError("retry_excerpt_too_large")
    offset = max(0, start - context)
    length = min(duration, end + context) - offset
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-ss",
            str(offset),
            "-i",
            str(source),
            "-t",
            str(length),
            "-ar",
            "16000",
            "-ac",
            "1",
            str(destination),
        ],
        capture_output=True,
        timeout=120,
        check=True,
    )
    return offset
