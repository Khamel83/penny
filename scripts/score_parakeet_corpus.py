#!/usr/bin/env python3
"""Score fixed reference sections; extra words are not content-coverage failures."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.reference_alignment import normalize, align
from scripts.benchmark_parakeet_corpus import digest, save


def candidate_region(reference, hypothesis, expected):
    index = defaultdict(list)
    for i in range(len(hypothesis) - 4):
        index[tuple(hypothesis[i : i + 5])].append(i)
    offsets = []
    for i in range(len(reference) - 4):
        positions = index.get(tuple(reference[i : i + 5]), [])
        if len(positions) == 1:
            offsets.append(positions[0] - i)
    estimated = int(statistics.median(offsets)) if offsets else expected
    begin = max(0, estimated - 300)
    end = min(len(hypothesis), estimated + len(reference) + 400)
    return begin, end, len(offsets)


def deletion_runs(changes):
    runs = []
    current = []
    for c in changes:
        if c["type"] == "deletion" and (
            not current or c["ref_index"] == current[-1]["ref_index"] + 1
        ):
            current.append(c)
        else:
            if current:
                runs.append(current)
            current = [c] if c["type"] == "deletion" else []
    if current:
        runs.append(current)
    return [
        {
            "words": len(r),
            "ref_index": r[0]["ref_index"],
            "text": " ".join(c["reference"] for c in r),
        }
        for r in runs
        if len(r) >= 8
    ]


def score(root):
    corpus = json.loads((root / "corpus.json").read_text())["episodes"]
    plans = json.loads((root / "reference-windows.json").read_text())
    summary = {}
    for e in corpus:
        receipt_path = root / (e["id"] + "-receipt.json")
        if not receipt_path.exists():
            continue
        receipt = json.loads(receipt_path.read_text())
        output = root / (e["id"] + "-parakeet.json")
        if (
            digest(output) != receipt["output_sha256"]
            or digest(Path(e["reference_path"]))
            != receipt["inputs"]["reference_sha256"]
        ):
            raise RuntimeError("score_artifact_mismatch:" + e["id"])
        ref = normalize(
            " ".join(
                t["text"]
                for t in json.loads(Path(e["reference_path"]).read_text())["turns"]
            ),
            True,
        )
        payload = json.loads(output.read_text())
        hyp = normalize(payload["text"], True)
        plan = plans[e["id"]]
        windows = []
        for w in plan["windows"]:
            target = w["tokens"]
            if target != ref[w["reference_start_index"] : w["reference_end_index"]]:
                raise RuntimeError("frozen_reference_window_changed:" + e["id"])
            expected = int(len(hyp) * w["reference_start_index"] / len(ref))
            begin, end, anchors = candidate_region(target, hyp, expected)
            result = align(target, hyp[begin:end], insertion_cost=0)
            window = {
                "label": w["label"],
                "reference_tokens": len(target),
                "matched_tokens": result["equal_tokens"],
                "reference_recall_percent": 100 * result["equal_tokens"] / len(target),
                "substitutions": result["substitutions"],
                "deletions": result["deletions"],
                "extra_tokens": result["insertions"],
                "unique_five_word_anchors": anchors,
                "hypothesis_start_index": begin + result["hypothesis_start"],
                "hypothesis_end_index": begin + result["hypothesis_end"],
                "long_deletions": deletion_runs(result["changes"]),
                "changes": result["changes"],
            }
            windows.append(window)
        words = payload.get("words") or []
        invalid = sum(
            not (0 <= w["start"] <= w["end"] <= payload["audio_seconds"] + 0.05)
            for w in words
        )
        backwards = sum(a["start"] > b["start"] for a, b in zip(words, words[1:]))
        # Long repeated phrases are a separate review signal, never filler penalties.
        raw = normalize(payload["text"])
        longest = 0
        run = 0
        previous = None
        for token in raw:
            run = run + 1 if token == previous else 1
            longest = max(longest, run)
            previous = token
        record = {
            "windows": windows,
            "reference_recall_percent": 100
            * sum(w["matched_tokens"] for w in windows)
            / sum(w["reference_tokens"] for w in windows),
            "word_timestamps_invalid": invalid,
            "word_timestamps_backwards": backwards,
            "max_identical_token_run": longest,
            "output_sha256": receipt["output_sha256"],
        }
        save(root / (e["id"] + "-score.json"), record)
        summary[e["id"]] = {k: v for k, v in record.items() if k != "windows"}
        summary[e["id"]]["windows"] = [
            {k: v for k, v in w.items() if k != "changes"} for w in windows
        ]
        print(
            json.dumps(
                {
                    "id": e["id"],
                    "reference_recall_percent": record["reference_recall_percent"],
                    "long_deletions": sum(len(w["long_deletions"]) for w in windows),
                }
            ),
            flush=True,
        )
    save(root / "content-summary.json", summary)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    score(p.parse_args().root)
