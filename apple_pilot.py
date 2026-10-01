"""Bounded, private Apple shadow queue. Never writes Penny's canonical ledger."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import signal
import sqlite3
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from transcript_quality import evaluate_transcript

_STOP = threading.Event()
_PROCESSES: dict[int, subprocess.Popen] = {}
_PROCESS_LOCK = threading.RLock()


def stop_worker(_signum, _frame) -> None:
    _STOP.set()
    with _PROCESS_LOCK:
        for pid in list(_PROCESSES):
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def volume_uuid(volume: Path) -> str:
    import plistlib

    result = subprocess.run(
        ["/usr/sbin/diskutil", "info", "-plist", str(volume)],
        capture_output=True,
        timeout=10,
        check=True,
    )
    return plistlib.loads(result.stdout)["VolumeUUID"]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def private_json(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        temporary = Path(f.name)
        os.chmod(temporary, 0o600)
        json.dump(value, f, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


class PilotStore:
    def __init__(
        self, root: Path, *, max_jobs: int = 200, max_bytes: int = 8 * 1024**3
    ):
        self.root = root
        self.max_jobs = max_jobs
        self.max_bytes = max_bytes
        self.volume = (
            Path("/Volumes") / root.parts[2]
            if root.is_absolute() and root.parts[1:2] == ("Volumes",)
            else None
        )
        if self.volume:
            expected = os.environ.get("PENNY_APPLE_PILOT_VOLUME_UUID")
            if (
                not expected
                or not self.volume.is_mount()
                or volume_uuid(self.volume) != expected
            ):
                raise RuntimeError("pilot_volume_unverified")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.device = root.stat().st_dev
        os.chmod(root, 0o700)
        self.objects = root / "audio"
        self.objects.mkdir(exist_ok=True, mode=0o700)
        self.results = root / "results"
        self.results.mkdir(exist_ok=True, mode=0o700)
        self.database = root / "pilot.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, client TEXT NOT NULL, source_ref TEXT,
                audio_sha256 TEXT NOT NULL, audio_path TEXT NOT NULL,
                audio_bytes INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL,
                finished REAL, error_code TEXT, baseline TEXT, metadata TEXT)""")
        os.chmod(self.database, 0o600)

    @contextmanager
    def connect(self):
        if self.volume and (
            not self.volume.is_mount() or self.volume.stat().st_dev != self.device
        ):
            raise RuntimeError("pilot_volume_unavailable")
        db = sqlite3.connect(self.database, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def capture(
        self,
        path: Path,
        client: str,
        baseline: dict | None = None,
        source_ref: str | None = None,
    ) -> str:
        """Immutable snapshot + durable admission; bounded and deduplicated."""
        with path.open("rb") as original:
            return self.capture_stream(original, path.suffix, client, baseline, source_ref)

    def capture_stream(self, original, suffix, client, baseline=None, source_ref=None):
        """Snapshot an owned descriptor even after its upload pathname is removed."""
        stat = os.fstat(original.fileno())
        if not 0 < stat.st_size <= 512 * 1024**2:
            raise ValueError("pilot_file_size_limit")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT count(*) FROM jobs").fetchone()[0]
            used = sum(p.stat().st_size for p in self.objects.iterdir() if p.is_file())
            if count >= self.max_jobs or used + stat.st_size > self.max_bytes:
                raise ValueError("pilot_capacity_limit")
            digest = hashlib.sha256()
            with tempfile.NamedTemporaryFile(dir=self.objects, delete=False) as f:
                temporary = Path(f.name)
                os.chmod(temporary, 0o600)
                try:
                    for chunk in iter(lambda: original.read(1024 * 1024), b""):
                        digest.update(chunk)
                        f.write(chunk)
                    f.flush()
                    os.fsync(f.fileno())
                    after = os.fstat(original.fileno())
                    if (stat.st_size, stat.st_mtime_ns) != (
                        after.st_size,
                        after.st_mtime_ns,
                    ):
                        raise ValueError("pilot_source_changed")
                    audio_hash = digest.hexdigest()
                    job_id = hashlib.sha256(
                        f"{client}:{audio_hash}".encode()
                    ).hexdigest()
                    destination = self.objects / (audio_hash + suffix[:12])
                    if not destination.exists():
                        os.replace(temporary, destination)
                    db.execute(
                        """INSERT INTO jobs
                        (id,client,source_ref,audio_sha256,audio_path,audio_bytes,created,baseline)
                        VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                        baseline=coalesce(excluded.baseline,jobs.baseline)""",
                        (
                            job_id,
                            client,
                            source_ref,
                            audio_hash,
                            str(destination),
                            stat.st_size,
                            time.time(),
                            json.dumps(baseline) if baseline else None,
                        ),
                    )
                finally:
                    temporary.unlink(missing_ok=True)
        return job_id

    def claim(self) -> dict | None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT * FROM jobs WHERE state='pending' ORDER BY
                CASE client WHEN 'penny' THEN 0 WHEN 'atlas' THEN 1 ELSE 2 END,
                created LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE jobs SET state='running',attempts=attempts+1 WHERE id=?",
                (row["id"],),
            )
            return dict(row)

    def recover_interrupted(self) -> None:
        with self.connect() as db:
            db.execute("""UPDATE jobs SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,
                error_code='interrupted' WHERE state='running'""")

    def finish(self, job_id: str, metadata: dict, *, error: str | None = None) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE jobs SET state=?,finished=?,error_code=?,metadata=? WHERE id=?",
                (
                    "failed" if error else "completed",
                    time.time(),
                    error,
                    json.dumps(metadata),
                    job_id,
                ),
            )

    @staticmethod
    def _counts(db) -> dict:
        states = dict(
            db.execute("SELECT state,count(*) FROM jobs GROUP BY state").fetchall()
        )
        clients = dict(
            db.execute("SELECT client,count(*) FROM jobs GROUP BY client").fetchall()
        )
        rows = [
            json.loads(r[0])
            for r in db.execute("SELECT metadata FROM jobs WHERE state='completed'")
        ]
        return {
            "states": states,
            "clients": clients,
            "completed_audio_seconds": sum(r["audio_seconds"] for r in rows),
            "quality_passed": sum(r["quality_passed"] for r in rows),
        }

    def status(self) -> dict:
        with self.connect() as db:
            counts = self._counts(db)
        return {**counts, "max_jobs": self.max_jobs, "max_bytes": self.max_bytes}

    @classmethod
    def read_status(cls, root: Path) -> dict:
        """Observe an existing queue without creating or repairing any files."""
        db = sqlite3.connect((root / "pilot.sqlite3").as_uri() + "?mode=ro", uri=True)
        try:
            return cls._counts(db)
        finally:
            db.close()


class AsyncPilotCapture:
    """Best-effort live admission; disk work never runs on the response thread.

    At most two descriptors and daemon threads can be retained. A stalled disk
    occupies a slot; subsequent live admissions are refused without waiting.
    Only a committed PilotStore job is a durable receipt.
    """

    def __init__(self, store):
        self.store = store
        self.slots = threading.BoundedSemaphore(2)

    def capture(self, path, client, baseline=None):
        if not self.slots.acquire(blocking=False):
            raise RuntimeError("pilot_admission_busy")
        original = None
        try:
            original = path.open("rb")
            def snapshot():
                try:
                    with original:
                        self.store.capture_stream(original, path.suffix, client, baseline)
                except Exception:  # noqa: BLE001 - best-effort shadow; no private error logs
                    pass
                finally:
                    self.slots.release()
            threading.Thread(target=snapshot, name="apple-pilot-admission", daemon=True).start()
        except BaseException:
            if original is not None:
                original.close()
            self.slots.release()
            raise


def run_bounded(args: list[str], timeout: float) -> str:
    """Kill the whole subprocess group on deadline; never include private stderr."""
    with _PROCESS_LOCK:
        if _STOP.is_set():
            raise RuntimeError("worker_stopping")
        process = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        _PROCESSES[process.pid] = process
        # A signal handler can re-enter this lock during Popen on the main thread.
        if _STOP.is_set():
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        try:
            stdout, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise RuntimeError("process_timeout") from None
    finally:
        with _PROCESS_LOCK:
            _PROCESSES.pop(process.pid, None)
    if process.returncode:
        raise RuntimeError("process_failed")
    return stdout


def validate_result(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise TypeError("invalid_engine_result")
    duration = payload.get("audio_seconds")
    if (
        not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration <= 0
    ):
        raise ValueError("invalid_audio_duration")
    if payload.get("engine") != "apple-speechtranscriber" or not isinstance(
        payload.get("text"), str
    ):
        raise ValueError("invalid_engine_result")
    segments = payload.get("segments")
    if not isinstance(segments, list):
        raise TypeError("invalid_segments")
    previous = 0.0
    for segment in segments:
        if not isinstance(segment, dict):
            raise TypeError("invalid_segment")
        if not isinstance(segment.get("text"), str):
            raise TypeError("invalid_segment_text")
        start, end = segment.get("start"), segment.get("end")
        if (
            not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or not math.isfinite(start)
            or not math.isfinite(end)
            or start < previous - 0.01
            or end < start
            or end > duration + 1
        ):
            raise ValueError("invalid_segment_timing")
        previous = end


def process_job(
    store: PilotStore, binary: Path, job: dict, *, timeout: float = 300
) -> None:
    started = time.monotonic()
    try:
        path = Path(job["audio_path"])
        if file_hash(path) != job["audio_sha256"]:
            raise ValueError("audio_hash_mismatch")
        with tempfile.TemporaryDirectory(dir=store.root) as scratch:
            wav = Path(scratch) / "input.wav"
            run_bounded(
                [
                    "/opt/homebrew/bin/ffmpeg",
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(path),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    str(wav),
                ],
                120,
            )
            payload = json.loads(run_bounded([str(binary), str(wav)], timeout))
        validate_result(payload)
        quality = evaluate_transcript(payload["text"])
        metadata = {
            "engine": payload["engine"],
            "audio_seconds": payload["audio_seconds"],
            "elapsed_seconds": time.monotonic() - started,
            "quality_passed": quality.passed,
            "quality_reason": quality.reason,
            "segment_count": len(payload["segments"]),
            "word_count": len(payload["text"].split()),
            "os_version": payload.get("os_version"),
            "binary_sha256": file_hash(binary),
        }
        if job.get("baseline"):
            baseline = json.loads(job["baseline"])
            baseline_text = baseline.get("text", "")
            metadata["baseline_word_count"] = len(baseline_text.split())
            metadata["baseline_quality_passed"] = evaluate_transcript(
                baseline_text
            ).passed
            metadata["baseline_elapsed_seconds"] = baseline.get("elapsed_seconds")
        private_json(
            store.results / (job["id"] + ".json"), {**payload, "metadata": metadata}
        )
        store.finish(job["id"], metadata)
    except (
        OSError,
        ValueError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
        code = (
            str(exc)
            if isinstance(exc, (ValueError, RuntimeError)) and str(exc).isidentifier()
            else type(exc).__name__
        )
        store.finish(
            job["id"], {"elapsed_seconds": time.monotonic() - started}, error=code
        )


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if args.status:
        print(json.dumps(PilotStore.read_status(args.root), sort_keys=True))
        return
    store = PilotStore(args.root)
    if args.binary is None:
        parser.error("--binary is required for worker")
    signal.signal(signal.SIGTERM, stop_worker)
    signal.signal(signal.SIGINT, stop_worker)
    with (args.root / "worker.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        probe = json.loads(run_bounded([str(args.binary), "--probe"], 20))
        if probe.get("asset_status") != "installed":
            raise RuntimeError("apple_assets_not_installed")
        store.recover_interrupted()
        with ThreadPoolExecutor(max_workers=2) as pool:
            running = []
            while not _STOP.is_set():
                for future in running:
                    if future.done():
                        future.result()
                running = [future for future in running if not future.done()]
                # Use existing read-only host pressure policy; no second MLX owner is loaded.
                from shared_whisper.worker import MacMemoryGuard

                if len(running) < 2 and not MacMemoryGuard().pressure_high():
                    job = store.claim()
                    if job:
                        running.append(
                            pool.submit(process_job, store, args.binary, job)
                        )
                private_json(
                    args.root / "health.json",
                    {
                        "service": "penny-apple-pilot",
                        "mode": "shadow",
                        "observed_at": time.time(),
                        "source_revision": os.environ.get(
                            "PENNY_SOURCE_REVISION", "unknown"
                        ),
                        "active_jobs": len(running),
                        **store.status(),
                    },
                )
                time.sleep(1)


if __name__ == "__main__":
    main()
