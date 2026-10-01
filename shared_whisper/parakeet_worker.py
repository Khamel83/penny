"""Isolated Parakeet runtime. Private results travel only through a local pipe."""

from __future__ import annotations

import contextlib
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import sys

# Bind approved bytes, including tokenizer, without permitting a hub lookup.
MODEL_HASHES = {
    "model.safetensors": "05e01c7f396c298cf7d23f61da7b504adeab698f0aaeafd9c82d198625464592",
    "config.json": "f320f1292511f34ec47f513755fe20fd01dbfc09a925d42730e66059a6e1ef4c",
    "tokenizer.model": "eacec2b0a77f336d4a2ca4a25a7047575d3c2b74de47e997f4c205126ed3135e",
    "tokenizer.vocab": "41130ff456706304a1adec782ccc9e003c4d417e8e324353d281be958cac4e17",
    "vocab.txt": "3cde1409fd78783a79b29ed4d32da57c746993856f7c8263bcb905d2e5839db7",
}


def verify_model(path: Path) -> None:
    for name, expected in MODEL_HASHES.items():
        h = hashlib.sha256()
        with (path / name).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest() != expected:
            raise ValueError("parakeet_model_hash_mismatch")


def verbose_result(result, duration: float) -> dict:
    """Join wordpieces with their own timing, preserving sentence boundaries."""
    segments = []
    previous = 0.0
    for sentence in result.sentences:
        words = []
        for token in sentence.tokens:
            start, end = float(token.start), float(token.end)
            if not (
                math.isfinite(start)
                and math.isfinite(end)
                and 0 <= start <= end <= duration + 0.05
            ):
                raise ValueError("invalid_parakeet_token_time")
            if start < previous:
                raise ValueError("backwards_parakeet_token_time")
            previous = start
            text = str(token.text)
            if text.startswith(" ") or not words:
                if text.strip():
                    words.append({"word": text.strip(), "start": start, "end": end})
            elif words:
                words[-1]["word"] += text
                words[-1]["end"] = max(words[-1]["end"], end)
        if words:
            segments.append(
                {
                    "start": words[0]["start"],
                    "end": words[-1]["end"],
                    "text": sentence.text.strip(),
                    "words": words,
                }
            )
    if not segments or not result.text.strip():
        raise ValueError("empty_parakeet_output")
    return {"text": result.text.strip(), "segments": segments}


def main() -> None:
    if os.environ.get("HF_HUB_OFFLINE") != "1":
        raise RuntimeError("offline_mode_required")
    from setproctitle import setproctitle

    setproctitle("Penny Shared Parakeet Worker")
    path = Path(sys.argv[1])
    verify_model(path)
    import mlx.core as mx
    from mlx_audio.stt.utils import load, load_audio

    mx.set_cache_limit(100 * 1024**2)
    with contextlib.redirect_stdout(sys.stderr):
        model = load(path, lazy=True)
    model.set_dtype(mx.bfloat16)
    mx.eval(model.parameters())
    for line in sys.stdin:
        request = json.loads(line)
        try:
            options = request.get("options") or {}
            if options.get("task", "transcribe") != "transcribe":
                raise ValueError("parakeet_translation_not_supported")
            audio = load_audio(request["audio_path"], 16000, dtype=mx.bfloat16)
            duration = len(audio) / 16000
            if not 0 < duration <= 86400:
                raise ValueError("audio_duration_out_of_bounds")
            with contextlib.redirect_stdout(sys.stderr):
                result = model.generate(audio, chunk_duration=30, overlap_duration=2)
            mx.synchronize()
            payload = verbose_result(result, duration)
            del result, audio
            reply = {"ok": payload}
        except Exception:
            reply = {"error": "parakeet_transcription_failed"}
        finally:
            mx.synchronize()
            mx.clear_cache()
            gc.collect()
        print(json.dumps(reply), flush=True)


if __name__ == "__main__":
    main()
