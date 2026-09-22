#!/usr/bin/env python3
"""Exercise Penny's local content-validation contract with synthetic files.

This smoke check intentionally uses a deterministic detector double instead of
loading a model or contacting a service. The production detector has the same
small result contract: content label, MIME type, and a bounded outcome. The
check proves the ordering boundary and durable local ledger evidence without
staging, transcribing, or delivering any fixture.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import transcript_log  # noqa: E402


SUPPORTED_CLASSIFICATIONS = {
    "aac": frozenset({".aac"}),
    "amr": frozenset({".amr"}),
    "caf": frozenset({".caf"}),
    "m4a": frozenset({".m4a"}),
    "mp3": frozenset({".mp3"}),
    "mp4": frozenset({".mp4"}),
    "ogg": frozenset({".oga", ".ogg"}),
    "wav": frozenset({".wav"}),
}


@dataclass(frozen=True)
class Detection:
    label: str
    mime_type: str


@dataclass(frozen=True)
class ValidationOutcome:
    case: str
    outcome: str
    label: str
    reason: str
    row_id: int


class SyntheticDetector:
    """Byte-driven fixture detector used only by this offline smoke check."""

    def identify_path(self, path: Path) -> Detection:
        data = path.read_bytes()
        suffix = path.suffix.lower()
        if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
            if len(data) < 44:
                return Detection("unknown_incomplete", "application/octet-stream")
            return Detection("wav", "audio/wav")
        if data.startswith(b"fLaC"):
            return Detection("flac", "audio/flac")
        if suffix == ".m4a" and data.startswith(b"not-audio"):
            return Detection("generic_binary", "application/octet-stream")
        return Detection("unknown", "application/octet-stream")


class MagikaDetector:
    """Small adapter for the production Magika Python API."""

    def __init__(self) -> None:
        from magika import Magika

        self._detector = Magika()

    def identify_path(self, path: Path) -> Detection:
        result = self._detector.identify_path(path)
        output = result.output
        return Detection(str(output.label), str(output.mime_type))


def _synthetic_wav() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8_000)
        handle.writeframes(b"\x00\x00" * 80)
    return output.getvalue()


def _validate(path: Path, detector: object) -> tuple[str, str, str]:
    try:
        detection = detector.identify_path(path)
    except (FileNotFoundError, PermissionError, OSError):
        return "retryable", "unknown", "content_read_failed"

    suffix = path.suffix.lower()
    allowed_suffixes = SUPPORTED_CLASSIFICATIONS.get(detection.label)
    if allowed_suffixes is None:
        if detection.label == "unknown_incomplete":
            return "retryable", "unknown", "content_incomplete"
        if detection.label == "unknown":
            return "rejected", detection.label, "content_unknown"
        if detection.label == "generic_binary":
            return "rejected", detection.label, "content_non_audio"
        return "rejected", detection.label, "content_unsupported"
    if suffix not in allowed_suffixes:
        return "rejected", detection.label, "content_extension_mismatch"
    return "accepted", detection.label, "content_supported"


def _record_outcome(
    case: str, path: Path, outcome: str, label: str, reason: str
) -> int:
    digest = (
        hashlib.sha256(path.read_bytes()).hexdigest()
        if path.exists()
        else hashlib.sha256(case.encode()).hexdigest()
    )
    state = "validated" if outcome == "accepted" else "needs_review"
    result = transcript_log.insert_transcript_result(
        content_hash=digest,
        source="content-validation-smoke",
        transcript=f"(synthetic content validation: {case})",
        ingest_state=state,
        quality_status="passed" if outcome == "accepted" else "needs_review",
        quality_detail=f"content_validation={outcome};label={label};reason={reason}",
        enqueue_slack=False,
    )
    if result.row_id is None:
        raise RuntimeError(f"ledger write failed for {case}")
    return int(result.row_id)


def run_smoke(
    root: Path | None = None, detector: object | None = None
) -> list[ValidationOutcome]:
    """Run all cases in an isolated directory and return metadata-only results."""
    detector = detector or SyntheticDetector()
    with tempfile.TemporaryDirectory(prefix="penny-content-smoke-", dir=root) as temp_dir:
        fixture_root = Path(temp_dir)
        valid = fixture_root / "valid.wav"
        valid.write_bytes(_synthetic_wav())
        mislabeled = fixture_root / "not-audio.m4a"
        mislabeled.write_bytes(b"not-audio fixture bytes")
        unsupported = fixture_root / "unsupported.flac"
        unsupported.write_bytes(b"fLaC" + b"synthetic flac fixture")
        incomplete = fixture_root / "incomplete.wav"
        incomplete.write_bytes(_synthetic_wav()[:20])
        unreadable = fixture_root / "missing.wav"

        cases: Iterable[tuple[str, Path]] = (
            ("valid_audio", valid),
            ("audio_extension_non_audio_bytes", mislabeled),
            ("unsupported_audio", unsupported),
            ("incomplete_input", incomplete),
            ("unreadable_input", unreadable),
        )
        results: list[ValidationOutcome] = []
        for case, path in cases:
            outcome, label, reason = _validate(path, detector)
            row_id = _record_outcome(case, path, outcome, label, reason)
            results.append(ValidationOutcome(case, outcome, label, reason, row_id))
        return results


def _assert_expected(results: list[ValidationOutcome]) -> None:
    expected = {
        "valid_audio": ("accepted", "wav", "content_supported"),
        "audio_extension_non_audio_bytes": (
            "rejected",
            "generic_binary",
            "content_non_audio",
        ),
        "unsupported_audio": ("rejected", "flac", "content_unsupported"),
        "incomplete_input": ("retryable", "unknown", "content_incomplete"),
        "unreadable_input": ("retryable", "unknown", "content_read_failed"),
    }
    actual = {item.case: (item.outcome, item.label, item.reason) for item in results}
    if actual != expected:
        raise AssertionError(f"unexpected validation outcomes: {actual}")
    if len({item.row_id for item in results}) != len(results):
        raise AssertionError("validation outcomes did not receive distinct ledger rows")


def _assert_real_results(results: list[ValidationOutcome]) -> None:
    by_case = {item.case: item for item in results}
    if by_case["valid_audio"].outcome != "accepted":
        raise AssertionError("Magika did not admit the synthetic WAV")
    if by_case["audio_extension_non_audio_bytes"].outcome != "rejected":
        raise AssertionError("Magika accepted non-audio bytes with an audio suffix")
    if by_case["unsupported_audio"].outcome != "rejected":
        raise AssertionError("unsupported audio was admitted")
    if by_case["unreadable_input"].outcome != "retryable":
        raise AssertionError("unreadable input was not retryable")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--real-magika",
        action="store_true",
        help="use the installed Magika model instead of the fixture detector",
    )
    parser.add_argument("--json", action="store_true", help="emit metadata-only JSON")
    args = parser.parse_args(argv)

    original_db_path = transcript_log.TRANSCRIPT_DB_PATH
    try:
        with tempfile.TemporaryDirectory(prefix="penny-content-ledger-") as db_dir:
            transcript_log.TRANSCRIPT_DB_PATH = Path(db_dir) / "smoke.db"
            transcript_log.init_db()
            detector = MagikaDetector() if args.real_magika else SyntheticDetector()
            results = run_smoke(detector=detector)
            if args.real_magika:
                _assert_real_results(results)
            else:
                _assert_expected(results)
            payload = {
                "status": "passed",
                "detector": "magika" if args.real_magika else "synthetic-local-fixture",
                "ledger_rows": len(results),
                "outcomes": [
                    {
                        "case": item.case,
                        "outcome": item.outcome,
                        "label": item.label,
                        "reason": item.reason,
                        "row_id": item.row_id,
                    }
                    for item in results
                ],
                "downstream_delivery": "not_attempted",
            }
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("content validation smoke: PASS (5 local ledger outcomes)")
            return 0
    finally:
        transcript_log.TRANSCRIPT_DB_PATH = original_db_path


if __name__ == "__main__":
    raise SystemExit(main())
