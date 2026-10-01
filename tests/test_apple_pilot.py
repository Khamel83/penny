import io
import json
import sys
from pathlib import Path

import pytest

import apple_pilot
from shared_whisper.server import create_app
from tests.test_shared_whisper_server import FakeSupervisor


def test_capture_survives_upload_removal_and_deduplicates(tmp_path):
    source = tmp_path / "source.m4a"
    source.write_bytes(b"immutable test audio")
    store = apple_pilot.PilotStore(tmp_path / "pilot")
    first = store.capture(source, "atlas", {"text": "baseline"})
    assert store.capture(source, "atlas", {"text": "second baseline"}) == first
    source.unlink()
    job = store.claim()
    assert job["id"] == first
    assert Path(job["audio_path"]).read_bytes() == b"immutable test audio"
    assert json.loads(job["baseline"])["text"] == "second baseline"
    assert store.claim() is None
    assert Path(job["audio_path"]).stat().st_mode & 0o777 == 0o600


def test_capacity_refusal_does_not_leave_new_audio(tmp_path):
    store = apple_pilot.PilotStore(tmp_path / "pilot", max_jobs=1)
    source = tmp_path / "file.wav"
    source.write_bytes(b"first")
    store.capture(source, "penny")
    source.write_bytes(b"second")
    with pytest.raises(ValueError, match="pilot_capacity_limit"):
        store.capture(source, "penny")
    assert len(list(store.objects.iterdir())) == 1


def test_interrupted_job_recovery_is_bounded(tmp_path):
    store = apple_pilot.PilotStore(tmp_path / "pilot")
    source = tmp_path / "file.wav"
    source.write_bytes(b"test")
    store.capture(source, "penny")
    for _ in range(3):
        assert store.claim()
        store.recover_interrupted()
    assert store.claim() is None
    assert store.status()["states"] == {"failed": 1}


@pytest.mark.parametrize("failure", [False, True])
def test_shadow_capture_cannot_change_success_response(tmp_path, failure):
    store = apple_pilot.PilotStore(tmp_path / "pilot")
    if failure:
        store.capture = lambda *args: (_ for _ in ()).throw(OSError("private detail"))
    app = create_app(FakeSupervisor(), auth_token="token", pilot_store=store)
    response = app.test_client().post(
        "/v1/audio/transcriptions",
        headers={"Authorization": "Bearer token", "X-Whisper-Client": "atlas"},
        data={"file": (io.BytesIO(b"original audio"), "file.wav")},
    )
    assert response.status_code == 200
    assert response.json["text"] == "hello"
    assert "private detail" not in str(response.json)
    if not failure:
        assert store.status()["states"] == {"pending": 1}
        assert json.loads(store.claim()["baseline"])["text"] == "hello"


def test_unauthorized_audio_never_enters_pilot(tmp_path):
    store = apple_pilot.PilotStore(tmp_path / "pilot")
    app = create_app(FakeSupervisor(), auth_token="token", pilot_store=store)
    response = app.test_client().post(
        "/v1/audio/transcriptions",
        headers={"X-Whisper-Client": "penny"},
        data={"file": (io.BytesIO(b"test"), "file.wav")},
    )
    assert response.status_code == 401
    assert store.status()["states"] == {}


def test_corrupt_snapshot_fails_without_running_apple(tmp_path, monkeypatch):
    store = apple_pilot.PilotStore(tmp_path / "pilot")
    source = tmp_path / "file.wav"
    source.write_bytes(b"test")
    store.capture(source, "penny")
    job = store.claim()
    Path(job["audio_path"]).write_bytes(b"changed")
    monkeypatch.setattr(
        apple_pilot,
        "run_bounded",
        lambda *_: pytest.fail("must not execute corrupted audio"),
    )
    apple_pilot.process_job(store, tmp_path / "binary", job)
    assert store.status()["states"] == {"failed": 1}
    assert not list(store.results.iterdir())


def test_valid_result_stays_private_and_records_quality_hold(tmp_path, monkeypatch):
    store = apple_pilot.PilotStore(tmp_path / "pilot")
    source = tmp_path / "file.wav"
    source.write_bytes(b"test")
    binary = tmp_path / "binary"
    binary.write_bytes(b"test executable")
    store.capture(source, "penny")
    payload = {
        "engine": "apple-speechtranscriber",
        "audio_seconds": 10,
        "text": "hello hello hello hello",
        "segments": [{"start": 0, "end": 10, "text": "hello"}],
    }
    monkeypatch.setattr(apple_pilot, "run_bounded", lambda *_: json.dumps(payload))
    job = store.claim()
    apple_pilot.process_job(store, binary, job)
    assert store.status()["states"] == {"completed": 1}
    assert store.status()["quality_passed"] == 0
    result = store.results / (job["id"] + ".json")
    assert (
        json.loads(result.read_text())["metadata"]["quality_reason"]
        == "consecutive_token_repetition"
    )
    assert result.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "segments",
    [
        [None],
        [{"start": 5, "end": 2, "text": "hello"}],
        [{"start": 0, "end": float("nan"), "text": "hello"}],
        [{"start": 0, "end": 11, "text": "hello"}, {"start": 2, "end": 3, "text": "hello"}],
    ],
)
def test_invalid_timestamps_are_not_accepted(segments):
    with pytest.raises((ValueError, TypeError)):
        apple_pilot.validate_result(
            {
                "engine": "apple-speechtranscriber",
                "text": "hello",
                "audio_seconds": 10,
                "segments": segments,
            }
        )


def test_real_process_deadline_is_enforced():
    with pytest.raises(RuntimeError, match="process_timeout"):
        apple_pilot.run_bounded(
            [sys.executable, "-c", "import time; time.sleep(10)"], 0.05
        )
    assert not apple_pilot._PROCESSES
