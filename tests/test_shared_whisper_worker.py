from shared_whisper.protocol import WhisperResult
from shared_whisper.worker import (
    MacMemoryGuard,
    build_result,
    parse_free_percent,
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
