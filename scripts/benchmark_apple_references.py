#!/usr/bin/env python3
"""Bounded public-reference comparison; does not activate the Apple pilot."""

from __future__ import annotations
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from array import array
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import WHISPER_MODEL_ID, WHISPER_MODEL_REVISION  # noqa: E402
from shared_whisper.client import SharedWhisperClient  # noqa: E402
from shared_whisper.protocol import ClientKind, WhisperProtocolError  # noqa: E402

CASES = {
    "musk": (
        "https://media.blubrry.com/takeituneasy/content.blubrry.com/takeituneasy/lex_ai_elon_musk_2.mp3",
        600,
        900,
    ),
    "sean": (
        "https://media.blubrry.com/takeituneasy/content.blubrry.com/takeituneasy/mit_ai_sean_carroll.mp3",
        300,
        600,
    ),
    "kyle": (
        "https://media.blubrry.com/takeituneasy/content.blubrry.com/takeituneasy/mit_ai_kyle_vogt.mp3",
        300,
        600,
    ),
}


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True))
    path.chmod(0o600)


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def recognition_exists(root):
    return any(
        (root / f"{name}-{engine}.json").exists()
        for name in CASES
        for engine in ("apple", "whisper")
    )


def required_artifacts(root):
    files = []
    for name in CASES:
        files.extend(
            root / (name + suffix)
            for suffix in (
                ".mp3",
                "-clip.wav",
                "-reference.txt",
                "-scope.json",
                "-apple.json",
                "-whisper.json",
            )
        )
        files.extend(
            [root / "musk.pdf", root / "musk.txt"]
            if name == "musk"
            else [root / (name + ".html")]
        )
    return files


def record_manifest(root, binary):
    save(
        root / "recognition-manifest.json",
        {
            "observed_at": time.time(),
            "cases": CASES,
            "apple_binary_sha256": digest(binary),
            "whisper_model_id": WHISPER_MODEL_ID,
            "whisper_model_revision": WHISPER_MODEL_REVISION,
            "files": {p.name: digest(p) for p in required_artifacts(root)},
        },
    )


def verify_manifest(root, binary):
    manifest = json.loads((root / "recognition-manifest.json").read_text())
    if (
        manifest.get("apple_binary_sha256") != digest(binary)
        or manifest.get("whisper_model_id") != WHISPER_MODEL_ID
        or manifest.get("whisper_model_revision") != WHISPER_MODEL_REVISION
        or manifest.get("cases") != json.loads(json.dumps(CASES))
    ):
        raise RuntimeError("recognition_identity_mismatch")
    if any(
        manifest.get("files", {}).get(p.name) != digest(p)
        for p in required_artifacts(root)
    ):
        raise RuntimeError("recognition_artifact_changed")


def turns(root, name):
    if name == "musk":
        text = (root / "musk.txt").read_text()
        text = "\n".join(
            line
            for line in text.splitlines()
            if not any(
                x in line
                for x in [
                    "This transcript was exported",
                    "Transcript by Rev.com",
                    "Page ",
                    "Completed:",
                ]
            )
        )
        pattern = re.compile(r"^(?:Lex Fridman|Elon Musk):\s+(\d{2}:\d{2})\s+", re.M)
        marks = list(pattern.finditer(text))
        result = []
        for i, match in enumerate(marks):
            mm, ss = map(int, match[1].split(":"))
            spoken = text[
                match.end() : marks[i + 1].start() if i + 1 < len(marks) else len(text)
            ]
            result.append((mm * 60 + ss, re.sub(r"\s+", " ", spoken).strip()))
        return result
    text = (root / (name + ".html")).read_text()
    result = []
    for block in re.findall(r'<div class="ts-segment">(.*?)</div>', text, re.S):
        stamp = re.search(r"\((\d\d):(\d\d):(\d\d)\)", block)
        spoken = re.search(r'<span class="ts-text">(.*?)</span>', block, re.S)
        if stamp and spoken:
            h, m, s = map(int, stamp.groups())
            words = html.unescape(re.sub("<[^>]+>", " ", spoken[1]))
            result.append((h * 3600 + m * 60 + s, re.sub(r"\s+", " ", words).strip()))
    return result


def prepare(root):
    if recognition_exists(root) or any(
        (root / (name + "-clip.wav")).exists() for name in CASES
    ):
        raise RuntimeError("existing_campaign_use_fresh_root")

    def fetch(item):
        name, (url, _, _) = item
        path = root / (name + ".mp3")
        if not path.exists():
            temp = path.with_suffix(".download")
            with requests.get(url, stream=True, timeout=(10, 30)) as r:
                r.raise_for_status()
                size = 0
                started = time.monotonic()
                with temp.open("wb") as f:
                    for chunk in r.iter_content(1024 * 1024):
                        size += len(chunk)
                        if size > 256 * 1024**2 or time.monotonic() - started > 180:
                            raise RuntimeError("download_bound")
                        f.write(chunk)
            temp.replace(path)
            path.chmod(0o600)
        return name

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(fetch, CASES.items()))
    for name, (_, lo, hi) in CASES.items():
        t = turns(root, name)
        starts = [i for i, (s, _) in enumerate(t) if s >= lo]
        ends = [i for i, (s, _) in enumerate(t) if s >= hi]
        if not starts or not ends:
            raise RuntimeError("reference_turns_missing")
        first, last = starts[0], ends[0]
        begin = t[first][0]
        end = t[last][0]
        reference = " ".join(words for _, words in t[first:last])
        (root / (name + "-reference.txt")).write_text(reference)
        clip = root / (name + "-clip.wav")
        if not clip.exists():
            subprocess.run(
                [
                    "/opt/homebrew/bin/ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-ss",
                    str(max(0, begin - 30)),
                    "-i",
                    str(root / (name + ".mp3")),
                    "-t",
                    str(end - begin + 60),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    str(clip),
                ],
                check=True,
                timeout=60,
            )
        save(
            root / (name + "-scope.json"),
            {
                "reference_start": begin,
                "reference_end": end,
                "clip_start": max(0, begin - 30),
                "clip_seconds": end - begin + 60,
                "audio_sha256": hashlib.sha256(clip.read_bytes()).hexdigest(),
                "reference_words": len(reference.split()),
                "complete_turns": last - first,
            },
        )
        print(
            json.dumps(
                {
                    "prepared": name,
                    "clip_seconds": end - begin + 60,
                    "reference_words": len(reference.split()),
                }
            ),
            flush=True,
        )


def recognize(root, binary):
    if recognition_exists(root):
        raise RuntimeError("existing_recognition_use_verified_score")
    plist = plistlib.loads(
        (
            Path.home() / "Library/LaunchAgents/com.penny.shared-whisper.plist"
        ).read_bytes()
    )
    token = plist["EnvironmentVariables"]["PENNY_SHARED_WHISPER_TOKEN"]
    client = SharedWhisperClient(
        base_url="http://127.0.0.1:10311/v1",
        auth_token=token,
        model_id=WHISPER_MODEL_ID,
        model_revision=WHISPER_MODEL_REVISION,
        client_kind=ClientKind.BACKFILL,
        timeout=180,
    )
    for name in CASES:
        clip = root / (name + "-clip.wav")
        output = root / (name + "-apple.json")
        if not output.exists():
            started = time.monotonic()
            r = subprocess.run(
                ["/usr/bin/time", "-l", str(binary), str(clip)],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if r.returncode:
                raise RuntimeError("apple_failed")
            payload = json.loads(r.stdout)
            payload["request_elapsed_seconds"] = time.monotonic() - started
            output.write_text(json.dumps(payload))
            output.chmod(0o600)
            (root / (name + "-apple-resources.txt")).write_text(r.stderr)
            print(
                json.dumps(
                    {
                        "completed": name,
                        "engine": "apple",
                        "seconds": round(payload["request_elapsed_seconds"], 2),
                    }
                ),
                flush=True,
            )
        output = root / (name + "-whisper.json")
        if output.exists():
            continue
        for attempt in range(18):
            try:
                health = requests.get("http://127.0.0.1:10311/health", timeout=5).json()
                if health.get("active_client"):
                    time.sleep(5)
                    continue
                started = time.monotonic()
                p = client.transcribe(
                    clip,
                    language="en",
                    task="transcribe",
                    condition_on_previous_text=False,
                    word_timestamps=True,
                )
                save(
                    output,
                    {
                        "text": p.text,
                        "segments": p.segments,
                        "model_id": p.model_id,
                        "model_revision": p.model_revision,
                        "request_elapsed_seconds": time.monotonic() - started,
                        "worker_pid": health.get("worker_pid"),
                    },
                )
                print(
                    json.dumps(
                        {
                            "completed": name,
                            "engine": "whisper",
                            "seconds": round(time.monotonic() - started, 2),
                        }
                    ),
                    flush=True,
                )
                break
            except WhisperProtocolError:
                if attempt == 17:
                    raise RuntimeError("whisper_unavailable") from None
                time.sleep(5)
        else:
            raise RuntimeError("whisper_busy_bound")

    record_manifest(root, binary)


def integer_words(n):
    small = [
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
    ]
    tens = [
        "",
        "",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
    ]
    if n < 20:
        return small[n]
    if n < 100:
        return tens[n // 10] + (" " + small[n % 10] if n % 10 else "")
    if n < 1000:
        return (
            small[n // 100]
            + " hundred"
            + (" " + integer_words(n % 100) if n % 100 else "")
        )
    if n < 1000000:
        return (
            integer_words(n // 1000)
            + " thousand"
            + (" " + integer_words(n % 1000) if n % 1000 else "")
        )
    return " ".join(small[int(c)] for c in str(n))


def normalize(text, content=False):
    text = text.casefold().replace("’", "'").replace("%", " percent ")
    for a, b in {
        "can't": "can not",
        "cannot": "can not",
        "won't": "will not",
        "it's": "it is",
        "that's": "that is",
        "there's": "there is",
        "what's": "what is",
        "let's": "let us",
    }.items():
        text = text.replace(a, b)
    text = re.sub(r"n['’]t\b", " not", text)
    text = re.sub(r"['’]re\b", " are", text)
    text = re.sub(r"['’]ve\b", " have", text)
    text = re.sub(r"['’]ll\b", " will", text)
    text = re.sub(r"['’]m\b", " am", text)
    # Cosmetic number/ordinal and compound spacing changes apply to all texts.
    ordinals = {
        1: "first",
        2: "second",
        3: "third",
        4: "fourth",
        5: "fifth",
        6: "sixth",
        7: "seventh",
        8: "eighth",
        9: "ninth",
        10: "tenth",
    }
    text = re.sub(
        r"\b(\d{1,6})(st|nd|rd|th)\b",
        lambda m: ordinals.get(int(m[1]), integer_words(int(m[1])) + "th"),
        text,
    )
    text = re.sub(r"\b\d{1,6}\b", lambda m: integer_words(int(m[0])), text)
    text = re.sub(r"\bapple\s+iis\b", "apple twos", text)
    text = re.sub(r"\bapple\s+ii\b", "apple two", text)
    text = re.sub(r"\bspacetime\b", "space time", text)
    text = re.sub(r"\bbattlebots\b", "battle bots", text)
    tokens = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text)
    if content:
        result = []
        for token in tokens:
            if token in {"uh", "um", "hmm", "ah"}:
                continue
            if not result or result[-1] != token:
                result.append(token)
        return result
    return tokens


def align(reference, hypothesis):
    """Levenshtein alignment with unscored outer hypothesis padding only."""
    n, m = len(reference), len(hypothesis)
    d = [array("i", [0]) * (m + 1) for _ in range(n + 1)]
    matches = [array("i", [0]) * (m + 1) for _ in range(n + 1)]
    operations = [bytearray(m + 1) for _ in range(n + 1)]
    for row in range(n + 1):
        d[row][0] = row
        operations[row][0] = 1
    for i, a in enumerate(reference, 1):
        for j, b in enumerate(hypothesis, 1):
            choices = [
                (
                    int(d[i - 1][j - 1]) + (a != b),
                    int(matches[i - 1][j - 1]) + (a == b),
                    0,
                ),
                (int(d[i - 1][j]) + 1, int(matches[i - 1][j]), 1),
                (int(d[i][j - 1]) + 1, int(matches[i][j - 1]), 2),
            ]
            cost, equal, op = min(choices, key=lambda x: (x[0], -x[1], x[2]))
            d[i][j] = cost
            matches[i][j] = equal
            operations[i][j] = op
    j = min(range(m + 1), key=lambda k: (int(d[n][k]), -int(matches[n][k]), k))
    end = j
    i = n
    changes = []
    equal = 0
    counts = {"substitutions": 0, "deletions": 0, "insertions": 0}
    while i:
        op = operations[i][j]
        if op == 0:
            if reference[i - 1] == hypothesis[j - 1]:
                equal += 1
            else:
                counts["substitutions"] += 1
                changes.append(
                    {
                        "type": "substitution",
                        "ref_index": i - 1,
                        "reference": reference[i - 1],
                        "hypothesis": hypothesis[j - 1],
                    }
                )
            i -= 1
            j -= 1
        elif op == 1:
            counts["deletions"] += 1
            changes.append(
                {"type": "deletion", "ref_index": i - 1, "reference": reference[i - 1]}
            )
            i -= 1
        else:
            counts["insertions"] += 1
            changes.append(
                {"type": "insertion", "ref_index": i, "hypothesis": hypothesis[j - 1]}
            )
            j -= 1
    return {
        **counts,
        "reference_tokens": n,
        "equal_tokens": equal,
        "error_percent": 100 * sum(counts.values()) / max(1, n),
        "hypothesis_start": j,
        "hypothesis_end": end,
        "hypothesis_tokens": m,
        "changes": list(reversed(changes)),
    }


def score(root, binary):
    verify_manifest(root, binary)
    result = {}
    for name in CASES:
        ref = (root / (name + "-reference.txt")).read_text()
        g = {}
        for engine in ["apple", "whisper"]:
            p = json.loads((root / (name + "-" + engine + ".json")).read_text())
            strict = align(normalize(ref), normalize(p["text"]))
            content = align(normalize(ref, True), normalize(p["text"], True))
            save(
                root / (name + "-" + engine + "-alignment.json"),
                {"strict": strict, "content": content},
            )
            g[engine] = {k: v for k, v in strict.items() if k != "changes"}
            g[engine]["content_error_percent"] = content["error_percent"]
            g[engine]["elapsed_seconds"] = p["request_elapsed_seconds"]
        result[name] = g
    save(root / "summary.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--binary", type=Path)
    p.add_argument("phase", choices=["prepare", "recognize", "score"])
    a = p.parse_args()
    if a.phase == "prepare":
        prepare(a.root)
    elif a.phase == "recognize":
        if not a.binary:
            p.error("--binary required")
        recognize(a.root, a.binary)
    else:
        if not a.binary:
            p.error("--binary required to verify the completed recognition manifest")
        score(a.root, a.binary)


if __name__ == "__main__":
    main()
