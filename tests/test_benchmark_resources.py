"""Failed physical-memory observation must not look like measured zero."""

from types import SimpleNamespace
from unittest.mock import patch
import subprocess
import pytest
from scripts.benchmark_phonon_references import sample_footprint


def test_physical_memory_includes_kernel_lifetime_peak():
    result = SimpleNamespace(
        returncode=0,
        stdout="Physical footprint: 2.0G\nPhysical footprint (peak): 4.3G\n",
    )
    with patch(
        "scripts.benchmark_phonon_references.subprocess.run", return_value=result
    ):
        sample = sample_footprint(123)
    assert sample == {"footprint": 2 * 1024**3, "process_lifetime_peak": 4.3 * 1024**3}


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(returncode=1, stdout=""),
        SimpleNamespace(returncode=0, stdout="Physical footprint: 2.0G\n"),
    ],
)
def test_failed_or_incomplete_measurement_is_rejected(result):
    with patch(
        "scripts.benchmark_phonon_references.subprocess.run", return_value=result
    ):
        with pytest.raises(RuntimeError):
            sample_footprint(123)


def test_monitor_timeout_is_not_a_zero_measurement():
    with patch(
        "scripts.benchmark_phonon_references.subprocess.run",
        side_effect=subprocess.TimeoutExpired("vmmap", 10),
    ):
        with pytest.raises(subprocess.TimeoutExpired):
            sample_footprint(123)


def test_existing_benchmark_output_is_private_before_json_write(tmp_path, monkeypatch):
    import stat
    from scripts import benchmark_phonon_references as probe

    output = tmp_path / 'existing.json'
    output.write_text('old fixture')
    output.chmod(0o644)
    original_dump = probe.json.dump

    def checked_dump(value, stream, **kwargs):
        assert stat.S_IMODE(output.stat().st_mode) == 0o600
        return original_dump(value, stream, **kwargs)

    monkeypatch.setattr(probe.json, 'dump', checked_dump)
    probe.write_private_json(output, {'text': 'synthetic fixture'})
