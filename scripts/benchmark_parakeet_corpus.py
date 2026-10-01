#!/usr/bin/env python3
"""Recognize ten public full episodes sequentially, preserving local receipts."""

import argparse
from dataclasses import asdict
import gc
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w") as stream:
        json.dump(data, stream)
    temp.chmod(0o600)
    temp.replace(path)


def footprint():
    r = subprocess.run(
        ["vmmap", "-summary", str(os.getpid())],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if r.returncode:
        raise RuntimeError("vmmap_failed")
    result = {}
    for key, label in [
        ("physical_bytes", "Physical footprint:"),
        ("lifetime_peak_bytes", "Physical footprint (peak):"),
    ]:
        m = re.search(re.escape(label) + r"\s*([\d.]+)([KMG])", r.stdout)
        if not m:
            raise RuntimeError("vmmap_missing_measurement")
        result[key] = float(m[1]) * 1024 ** ("KMG".index(m[2]) + 1)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument(
        "--resume",
        action="store_true",
        help="Reuse only hash-verified completed receipts.",
    )
    a = p.parse_args()
    os.umask(0o077)
    episodes = json.loads((a.root / "corpus.json").read_text())["episodes"]
    if len(episodes) != 10 or len({e["id"] for e in episodes}) != 10:
        raise RuntimeError("ten_distinct_episodes_required")
    model_files = {p.name: digest(p) for p in a.model.iterdir() if p.is_file()}
    identity = {
        "repository": "mlx-community/parakeet-tdt-0.6b-v3",
        "revision": a.model.name,
        "files": model_files,
        "dtype": "bfloat16",
        "window_band_seconds": [25, 35],
        "versions": {
            n: importlib.metadata.version(n)
            for n in ["mlx", "mlx-audio", "fermion-research"]
        },
    }
    pending = []
    completed = {}
    for e in episodes:
        audio = Path(e["audio_path"])
        ref = Path(e["reference_path"])
        inputs = {"audio_sha256": digest(audio), "reference_sha256": digest(ref)}
        if (
            inputs["audio_sha256"] != e["audio_sha256"]
            or inputs["reference_sha256"] != e["reference_sha256"]
        ):
            raise RuntimeError("source_manifest_hash_mismatch:" + e["id"])
        receipt = a.root / (e["id"] + "-receipt.json")
        output = a.root / (e["id"] + "-parakeet.json")
        if receipt.exists() or output.exists():
            if not a.resume or not receipt.exists() or not output.exists():
                raise RuntimeError(
                    "existing_results_require_verified_resume:" + e["id"]
                )
            old = json.loads(receipt.read_text())
            if (
                old["inputs"] != inputs
                or old["identity"] != identity
                or old["output_sha256"] != digest(output)
                or old["wav_sha256"] != digest(a.root / (e["id"] + ".wav"))
            ):
                raise RuntimeError("receipt_identity_mismatch:" + e["id"])
            completed[e["id"]] = old
        else:
            pending.append((e, inputs))
    if not pending:
        print(
            json.dumps({"verified_completed": len(completed), "recognized": 0}),
            flush=True,
        )
        return
    samples = []
    stop = threading.Event()
    ready = threading.Event()

    def monitor():
        try:
            while not stop.is_set():
                sample = {"monotonic": time.monotonic(), **footprint()}
                samples.append(sample)
                if sample["physical_bytes"] > 5 * 1024**3:
                    raise RuntimeError("sampled_5_gib_abort")
                ready.set()
                stop.wait(1)
        except Exception as error:
            try:
                save(
                    a.root / "monitor-failure.json",
                    {"error": str(error), "samples": samples},
                )
            finally:
                os._exit(3)

    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    if not ready.wait(12):
        raise RuntimeError("physical_monitor_not_ready")
    import mlx.core as mx
    from mlx_audio.stt.utils import load
    from fermion._speech.engine_phonon2 import Phonon2SpeechModel

    mx.set_cache_limit(100 * 1024**2)
    started = time.monotonic()
    base = load(a.model, lazy=True)
    base.set_dtype(mx.bfloat16)
    mx.eval(base.parameters())
    model = Phonon2SpeechModel(
        base,
        path=a.model,
        profile="parakeet-v3-bf16",
        backend="mlx-stock",
        decode={},
        load_seconds=0,
    )
    mx.synchronize()
    load_seconds = time.monotonic() - started
    save(
        a.root / "session-load.json",
        {"identity": identity, "load_seconds": load_seconds},
    )
    try:
        for e, inputs in pending:
            wav = a.root / (e["id"] + ".wav")
            if wav.exists():
                raise RuntimeError("unverified_existing_wav:" + e["id"])
            else:
                subprocess.run(
                    [
                        "/opt/homebrew/bin/ffmpeg",
                        "-nostdin",
                        "-v",
                        "error",
                        "-i",
                        e["audio_path"],
                        "-ar",
                        "16000",
                        "-ac",
                        "1",
                        str(wav),
                    ],
                    check=True,
                    timeout=120,
                )
            mx.reset_peak_memory()
            first = len(samples)
            started = time.monotonic()
            result = model.transcribe_detailed(wav)
            mx.synchronize()
            elapsed = time.monotonic() - started
            data = asdict(result)
            data["request_elapsed_seconds"] = elapsed
            output = a.root / (e["id"] + "-parakeet.json")
            save(output, data)
            receipt = {
                "id": e["id"],
                "inputs": inputs,
                "identity": identity,
                "wav_sha256": digest(wav),
                "output_sha256": digest(output),
                "audio_seconds": result.audio_seconds,
                "elapsed_seconds": elapsed,
                "decode_seconds": result.decode_seconds,
                "word_count": len(result.words),
                "segment_count": len(result.segments),
                "truncated": result.truncated,
                "mlx_peak_bytes": mx.get_peak_memory(),
            }
            del result, data
            mx.clear_cache()
            gc.collect()
            time.sleep(2)
            receipt.update(
                mlx_retained_bytes=mx.get_active_memory(),
                cache_bytes=mx.get_cache_memory(),
                post_request_physical_bytes=footprint()["physical_bytes"],
                sampled_case_peak_physical_bytes=max(
                    [s["physical_bytes"] for s in samples[first:]]
                    or [footprint()["physical_bytes"]]
                ),
            )
            save(a.root / (e["id"] + "-receipt.json"), receipt)
            completed[e["id"]] = receipt
            save(a.root / "memory-samples.json", samples)
            print(
                json.dumps(
                    {
                        k: receipt[k]
                        for k in [
                            "id",
                            "audio_seconds",
                            "elapsed_seconds",
                            "word_count",
                            "truncated",
                            "sampled_case_peak_physical_bytes",
                            "post_request_physical_bytes",
                            "mlx_retained_bytes",
                        ]
                    }
                ),
                flush=True,
            )
    finally:
        stop.set()
        watcher.join(timeout=12)
        save(a.root / "memory-samples.json", samples)
    save(
        a.root / "campaign-receipt.json",
        {
            "identity": identity,
            "episodes": completed,
            "load_seconds": load_seconds,
            "physical_lifetime_peak_bytes": max(
                s["lifetime_peak_bytes"] for s in samples
            ),
            "completed": len(completed),
        },
    )


if __name__ == "__main__":
    main()
