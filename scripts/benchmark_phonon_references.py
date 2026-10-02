#!/usr/bin/env python3
"""Isolated Phonon/Parakeet comparison on existing public clips and one episode."""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def sample_footprint(pid):
    r = subprocess.run(
        ["vmmap", "-summary", str(pid)], capture_output=True, text=True, timeout=10
    )
    if r.returncode:
        raise RuntimeError("vmmap_failed")
    values = {}
    for key, label in [
        ("footprint", "Physical footprint:"),
        ("process_lifetime_peak", "Physical footprint (peak):"),
    ]:
        match = re.search(re.escape(label) + r"\s*([\d.]+)([KMG])", r.stdout)
        if not match:
            raise RuntimeError("vmmap_missing_physical_measurement")
        values[key] = float(match[1]) * 1024 ** ("KMG".index(match[2]) + 1)
    return values


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--references", type=Path, required=True)
    p.add_argument("--engine", choices=["phonon", "parakeet"], default="phonon")
    p.add_argument("--case", choices=["lex", "dwarkesh"], default="lex")
    a = p.parse_args()
    os.umask(0o077)
    manifest_name = (
        ("run.json" if a.engine == "phonon" else "parakeet-run.json")
        if a.case == "lex"
        else a.engine + "-dwarkesh-run.json"
    )
    if (a.root / manifest_name).exists():
        raise RuntimeError("completed_run_use_existing_results")
    names = (
        (
            ["sean", "kyle", "musk-full"]
            if a.engine == "phonon"
            else ["musk", "sean", "kyle", "musk-full"]
        )
        if a.case == "lex"
        else ["dwarkesh"]
    )
    if any((a.root / (n + "-" + a.engine + ".json")).exists() for n in names):
        raise RuntimeError("partial_run_refused_before_model_load")
    samples = []
    done = threading.Event()
    ready = threading.Event()

    def monitor():
        while not done.is_set():
            try:
                values = sample_footprint(os.getpid())
            except Exception as error:
                (
                    a.root / (a.engine + "-" + a.case + "-monitor-failure.json")
                ).write_text(
                    json.dumps(
                        {
                            "error": type(error).__name__ + ": " + str(error),
                            "samples": samples,
                        }
                    )
                )
                os._exit(3)
            samples.append({"monotonic": time.monotonic(), **values})
            if values.get("footprint", 0) > 5 * 1024**3:
                (a.root / "memory-abort.json").write_text(json.dumps(samples))
                os._exit(2)
            ready.set()
            done.wait(1)

    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    if not ready.wait(12):
        raise RuntimeError("physical_monitor_not_ready")
    from fermion.transcribe import _resolve
    from fermion._speech import backends
    import mlx.core as mx

    # Bound free buffers; live weights and active work are separately measured.
    mx.set_cache_limit(100 * 1024**2)
    started = time.monotonic()
    if a.engine == "phonon":
        _, key, pin, model_dir = _resolve(
            str(
                a.root / "cache/speech/FermionResearch__Phonon-2/model_phonon2_c4c_int6"
            )
        )
        model = backends.load(
            "mlx", model_dir, profile=key, backend=pin["backend"], quiet=True
        )
    else:
        from mlx_audio.stt.utils import load
        from fermion._speech.engine_phonon2 import Phonon2SpeechModel

        model_dir = Path((a.root / "parakeet-path.txt").read_text())
        base = load(model_dir, lazy=True)
        base.set_dtype(mx.bfloat16)
        mx.eval(base.parameters())
        # Use exactly the same pause-aligned segmentation and token/word timing adapter.
        model = Phonon2SpeechModel(
            base,
            path=model_dir,
            profile="parakeet-v3-bf16",
            backend="mlx-stock",
            decode={},
            load_seconds=0,
        )
    mx.synchronize()
    load_seconds = time.monotonic() - started
    runs = {}
    try:
        cases = [
            ("sean", a.references / "sean-clip.wav"),
            ("kyle", a.references / "kyle-clip.wav"),
            ("musk-full", a.root / "musk-full.wav"),
        ]
        if a.engine == "parakeet":
            cases.insert(0, ("musk", a.references / "musk-clip.wav"))
        if a.case == "dwarkesh":
            cases = [("dwarkesh", a.root / "dwarkesh-clip.wav")]
        for name, path in cases:
            output = a.root / (name + "-" + a.engine + ".json")
            if output.exists():
                raise RuntimeError("partial_run_refused")
            start = time.monotonic()
            result = model.transcribe_detailed(path)
            mx.synchronize()
            elapsed = time.monotonic() - start
            data = asdict(result)
            data.update(request_elapsed_seconds=elapsed, audio_sha256=digest(path))
            output.write_text(json.dumps(data))
            peak = mx.get_peak_memory()
            mx.clear_cache()
            runs[name] = dict(
                elapsed_seconds=elapsed,
                audio_seconds=result.audio_seconds,
                decode_seconds=result.decode_seconds,
                words=len(result.words),
                truncated=result.truncated,
                mlx_peak_bytes=peak,
                mlx_retained_bytes=mx.get_active_memory(),
                mlx_cache_bytes=mx.get_cache_memory(),
            )
            print(json.dumps({"case": name, **runs[name]}), flush=True)
    finally:
        done.set()
        watcher.join(timeout=12)
        (a.root / (a.engine + "-" + a.case + "-memory-samples.json")).write_text(
            json.dumps(samples)
        )
    configuration = model.describe()
    if a.engine == "parakeet":
        configuration["runtime"] = (
            "mlx-audio Parakeet v3, BF16 weights; shared pause-aligned window adapter"
        )
        configuration["load_seconds"] = load_seconds
    metadata = dict(
        engine=a.engine,
        case=a.case,
        load_seconds=load_seconds,
        configuration=configuration,
        runs=runs,
        model_files={p.name: digest(p) for p in model_dir.iterdir() if p.is_file()},
        sampled_peak_physical_bytes=max(s["footprint"] for s in samples),
        lifetime_peak_physical_bytes=max(s["process_lifetime_peak"] for s in samples),
    )
    (a.root / manifest_name).write_text(json.dumps(metadata, indent=2))
    print(
        json.dumps(
            {
                "load_seconds": load_seconds,
                "sampled_peak_physical_bytes": metadata["sampled_peak_physical_bytes"],
                "lifetime_peak_physical_bytes": metadata[
                    "lifetime_peak_physical_bytes"
                ],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
