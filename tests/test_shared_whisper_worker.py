from shared_whisper.protocol import WhisperResult
from shared_whisper.worker import (
    MacMemoryGuard,
    build_result,
    parse_free_percent,
    prepare_transcription_options,
)


MODEL_ID = "mlx-community/whisper-large-v3-turbo"
REVISION = "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb"


def test_build_result_adds_exact_pinned_model_identity():
    result = build_result(
        request_id="request-1",
        response={
            "text": "hello",
            "segments": [{"start": 0.0, "end": 1.0, "text": "hello"}],
        },
        model_id=MODEL_ID,
        model_revision=REVISION,
    )

    assert result == WhisperResult(
        text="hello",
        segments=[{"start": 0.0, "end": 1.0, "text": "hello"}],
        model_id=MODEL_ID,
        model_revision=REVISION,
        request_id="request-1",
    )


def test_memory_pressure_parser_reads_macos_free_percentage():
    output = "System-wide memory free percentage: 35%\n"

    assert parse_free_percent(output) == 35


def test_memory_guard_detects_existing_large_owner_and_high_pressure():
    guard = MacMemoryGuard(
        process_reader=lambda: "62096 Penny Shared Whisper Worker (large-v3-turbo)",
        pressure_reader=lambda: "System-wide memory free percentage: 9%",
        min_free_percent=12,
    )

    assert guard.has_existing_large_owner() is True
    assert guard.pressure_high() is True


def test_memory_guard_ignores_unchanged_tiny_wyoming_owner():
    guard = MacMemoryGuard(
        process_reader=lambda: (
            "82401 agent-cli-server-whisper --backend mlx "
            "--wyoming-port 10300 --port 10301 --model tiny"
        ),
        pressure_reader=lambda: "System-wide memory free percentage: 35%",
        min_free_percent=12,
    )

    assert guard.has_existing_large_owner() is False


def test_memory_guard_fails_closed_when_pressure_probe_is_unreadable():
    guard = MacMemoryGuard(
        process_reader=lambda: "",
        pressure_reader=lambda: "unparseable",
        min_free_percent=12,
    )

    assert guard.has_existing_large_owner() is False
    assert guard.pressure_high() is True


def test_memory_guard_fails_closed_when_process_probe_raises():
    def broken_process_reader():
        raise OSError("ps unavailable")

    guard = MacMemoryGuard(
        process_reader=broken_process_reader,
        pressure_reader=lambda: "System-wide memory free percentage: 35%",
    )

    assert guard.has_existing_large_owner() is True


def test_worker_maps_openai_form_fields_to_supported_mlx_options():
    assert prepare_transcription_options(
        {
            "language": "en",
            "vad_filter": False,
            "timestamp_granularities": ["segment", "word"],
            "condition_on_previous_text": False,
        }
    ) == {
        "language": "en",
        "condition_on_previous_text": False,
        "word_timestamps": False,
    }


def test_worker_preserves_an_explicit_word_timestamp_request():
    assert prepare_transcription_options({"word_timestamps": True}) == {
        "word_timestamps": True,
    }


def test_worker_bounds_cache_and_releases_it_after_success_and_failure(monkeypatch):
    import queue
    import sys
    from types import ModuleType, SimpleNamespace
    from shared_whisper.worker import _worker_main

    events = []
    core = ModuleType("mlx.core")
    core.set_cache_limit = lambda size: events.append(("limit", size))
    core.synchronize = lambda: events.append("sync")
    core.clear_cache = lambda: events.append("clear")
    mlx = ModuleType("mlx")
    mlx.core = core
    monkeypatch.setitem(sys.modules, "mlx", mlx)
    monkeypatch.setitem(sys.modules, "mlx.core", core)
    calls = []

    def transcribe(path, **options):
        calls.append((path, options))
        events.append("transcribe")
        if path == "failed.wav":
            raise RuntimeError("synthetic failure")
        return {"text": "hello", "segments": [{"start": 0, "end": 1, "text": "hello"}]}

    monkeypatch.setitem(sys.modules, "mlx_whisper", SimpleNamespace(transcribe=transcribe))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    requests, results = queue.Queue(), queue.Queue()
    for path in ("first.wav", "failed.wav", "last.wav"):
        requests.put({"request_id": path, "audio_path": path,
                      "options": {"language": "en", "word_timestamps": True}})
    requests.put(None)
    _worker_main(requests, results, "/pinned/model", MODEL_ID, REVISION)
    assert events == [("limit", 100 * 1024 * 1024)] + ["transcribe", "sync", "clear"] * 3
    first, failed, last = [results.get_nowait() for _ in range(3)]
    assert first[0] == last[0] == "ok"
    assert first[1].text == last[1].text == "hello"
    assert failed == ("error", "transcription_failed")
    assert all(options == {"path_or_hf_repo": "/pinned/model", "language": "en",
                           "word_timestamps": True} for _, options in calls)

