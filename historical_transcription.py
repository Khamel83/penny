"""Bounded local transcription of long historical audio with private checkpoints."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time

from config import WHISPER_MODEL_ID
from transcript_quality import QualityResult, TranscriptionResult
from shared_whisper.protocol import WhisperBusy, WhisperPreempted


def transcribe_historical(staged, *, duration_seconds, model, transcribe, checkpoint_root):
    def run(path):
        from config import get_config, WHISPER_MODEL_REVISION
        from shared_whisper.client import SharedWhisperClient
        from shared_whisper.protocol import ClientKind
        cfg = get_config()
        client = SharedWhisperClient(
            base_url=cfg.shared_whisper.url, auth_token=cfg.shared_whisper.auth_token,
            model_id=WHISPER_MODEL_ID, model_revision=WHISPER_MODEL_REVISION,
            timeout=cfg.shared_whisper.timeout_seconds, client_kind=ClientKind.BACKFILL,
        )
        for attempt in range(60):
            try:
                return transcribe(path, model=model, client=client)
            except (WhisperBusy, WhisperPreempted):
                if attempt == 59:
                    raise
                time.sleep(5)
    if duration_seconds is None or duration_seconds <= 300:
        return run(staged.path)
    if not math.isfinite(duration_seconds) or duration_seconds > 86400:
        raise ValueError('historical_duration_out_of_bounds')
    # Staging is immutable and hash-bound; cached chunks never enter routing.
    cache = Path(checkpoint_root) / staged.audio_sha256
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    texts, failures = [], []
    for index in range(math.ceil(duration_seconds / 300)):
        checkpoint = cache / f'{index:05d}.json'
        result = None
        if checkpoint.is_file():
            cached = json.loads(checkpoint.read_text())
            if cached.get('model') == WHISPER_MODEL_ID and cached.get('audio_sha256') == staged.audio_sha256:
                result = TranscriptionResult(cached['text'], QualityResult(cached['passed']), 1)
        if result is None:
            with tempfile.TemporaryDirectory(prefix='chunk-', dir=cache) as temporary:
                chunk = Path(temporary) / 'audio.wav'
                decoded = subprocess.run(
                    ['ffmpeg', '-nostdin', '-v', 'error', '-ss', str(index * 300),
                     '-i', str(staged.path), '-t', str(min(300, duration_seconds - index * 300)),
                     '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(chunk)],
                    capture_output=True, timeout=120,
                )
                if decoded.returncode or not chunk.is_file() or chunk.stat().st_size <= 44:
                    raise RuntimeError('historical_chunk_decode_failed')
                result = run(chunk)
            payload = {'model': WHISPER_MODEL_ID, 'audio_sha256': staged.audio_sha256,
                       'text': result.text, 'passed': result.quality.passed}
            with tempfile.NamedTemporaryFile(mode='w', dir=cache, delete=False) as handle:
                partial = Path(handle.name)
                os.chmod(partial, 0o600)
                json.dump(payload, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(partial, checkpoint)
        texts.append(result.text)
        if not result.quality.passed:
            failures.append(index)
    return TranscriptionResult(
        '\n'.join(texts), QualityResult(not failures, 'chunk_quality_review' if failures else None),
        1, f'chunk_quality_review_count={len(failures)}' if failures else None,
    )
