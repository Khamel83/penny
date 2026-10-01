"""Isolated research probe. Outputs local results only; no Penny state writes."""

import argparse
import gc
import json
import os
import re
import subprocess
import time
from pathlib import Path


def footprint():
    p = subprocess.run(
        ["vmmap", "-summary", str(os.getpid())],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return {
        key: value
        for key, value in re.findall(
            r"^(Physical footprint(?: \(peak\))?):\s*(.+)$", p.stdout, re.MULTILINE
        )
    }


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--clear-cache", action="store_true")
    parser.add_argument("--engine", choices=("mlx", "cpu"), default="mlx")
    parser.add_argument("--cache-limit-mib", type=int)
    parser.add_argument("audio", nargs="+", type=Path)
    args = parser.parse_args()
    from fermion._speech import backends, fetch
    from fermion.transcribe import _resolve

    if args.engine == "mlx":
        import mlx.core as mx

        if args.cache_limit_mib is not None:
            mx.set_cache_limit(args.cache_limit_mib * 1024 * 1024)
    else:
        mx = None

    repo, key, pin, local_dir = _resolve("phonon-2")
    model_dir = local_dir or fetch.ensure(repo, key, pin)
    start = time.perf_counter()
    speech = backends.load(
        args.engine, model_dir, profile=key, backend=pin["backend"], quiet=True
    )
    report = {
        "load_seconds": time.perf_counter() - start,
        "engine": speech.describe(),
        "loaded_footprint": footprint(),
        "rows": [],
    }
    for audio in args.audio:
        if mx:
            mx.reset_peak_memory()
        start = time.perf_counter()
        result = speech.transcribe_detailed(audio)
        wall = time.perf_counter() - start
        row = {
            "file": audio.name,
            "wall_seconds": wall,
            "audio_seconds": result.audio_seconds,
            "decode_seconds": result.decode_seconds,
            "text": result.text,
            "truncated": result.truncated,
            "segments": result.segments,
            "words": result.words,
            "mlx_peak_bytes": mx.get_peak_memory() if mx else None,
            "mlx_active_bytes": mx.get_active_memory() if mx else None,
            "mlx_cache_bytes": mx.get_cache_memory() if mx else None,
            "post_footprint": footprint(),
        }
        if args.clear_cache and mx:
            mx.synchronize()
            mx.clear_cache()
            gc.collect()
            row["cleared_footprint"] = footprint()
            row["cleared_mlx_active_bytes"] = mx.get_active_memory()
            row["cleared_mlx_cache_bytes"] = mx.get_cache_memory()
        report["rows"].append(row)
        args.output.write_text(json.dumps(report, indent=2, default=str) + "\n")
        print(
            json.dumps(
                {
                    k: row[k]
                    for k in (
                        "file",
                        "wall_seconds",
                        "audio_seconds",
                        "decode_seconds",
                        "truncated",
                        "mlx_peak_bytes",
                        "post_footprint",
                    )
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
