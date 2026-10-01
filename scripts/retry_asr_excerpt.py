#!/usr/bin/env python3
"""Produce a local Whisper second opinion for a bounded original-audio range.

Never modifies a canonical transcript, source recording, queue or delivery.
"""

from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import WHISPER_MODEL_ID, WHISPER_MODEL_REVISION, get_config
from shared_whisper.client import SharedWhisperClient
from shared_whisper.protocol import ClientKind
from shared_whisper.retry import extract_excerpt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("audio", type=Path)
    p.add_argument("--start", type=float, required=True)
    p.add_argument("--end", type=float, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    os.umask(0o077)
    cfg = get_config()
    client = SharedWhisperClient(
        base_url=cfg.shared_whisper.url,
        auth_token=cfg.shared_whisper.auth_token,
        model_id=WHISPER_MODEL_ID,
        model_revision=WHISPER_MODEL_REVISION,
        client_kind=ClientKind.BACKFILL,
        timeout=300,
    )
    with tempfile.TemporaryDirectory(
        prefix="asr-excerpt-", dir=a.output.parent
    ) as temp:
        excerpt = Path(temp) / "audio.wav"
        before = a.audio.stat()
        source_hash = hashlib.sha256()
        with a.audio.open("rb") as source_stream:
            for chunk in iter(lambda: source_stream.read(1024 * 1024), b""):
                source_hash.update(chunk)
        offset = extract_excerpt(a.audio, excerpt, a.start, a.end)
        after = a.audio.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise RuntimeError("retry_source_changed")
        digest = hashlib.sha256(excerpt.read_bytes()).hexdigest()
        result = client.transcribe(excerpt, language="en", word_timestamps=True)
        payload = asdict(result)
        for segment in payload["segments"]:
            for key in ("start", "end"):
                segment[key] += offset
            for word in segment.get("words", []):
                for key in ("start", "end"):
                    word[key] += offset
        payload.update(
            source=str(a.audio.resolve()),
            source_size=a.audio.stat().st_size,
            source_sha256=source_hash.hexdigest(),
            range_start=a.start,
            range_end=a.end,
            excerpt_offset=offset,
            excerpt_sha256=digest,
            timestamp_origin="original_audio",
        )
        with a.output.open("x") as stream:
            json.dump(payload, stream)
        a.output.chmod(0o600)
    print(
        json.dumps(
            {
                "output": str(a.output),
                "model_id": result.model_id,
                "request_id": result.request_id,
            }
        )
    )


if __name__ == "__main__":
    main()
