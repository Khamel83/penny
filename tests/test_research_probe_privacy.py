"""Research probes must secure pre-existing destinations before writing."""

import importlib.util
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def load_probe(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / 'scripts' / 'research' / (name + '.py')
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_apple_probe_secures_existing_directory_and_outputs(tmp_path, monkeypatch):
    probe = load_probe('apple_batch_probe')
    output = tmp_path / 'results'
    output.mkdir(mode=0o755)
    for name in ('job-0.json', 'job-0.stderr', 'receipt.json'):
        (output / name).write_text('old fixture')
        (output / name).chmod(0o644)

    def launch(args, stdout, stderr, **kwargs):
        stdout.write('synthetic fixture')
        return SimpleNamespace(returncode=0, poll=lambda: 0, wait=lambda: 0)

    monkeypatch.setattr(probe.subprocess, 'Popen', launch)
    monkeypatch.setattr(sys, 'argv', ['probe', 'fake-binary', 'fake-audio', str(output)])
    prior = os.umask(0o022)
    try:
        probe.main()
    finally:
        os.umask(prior)
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in output.iterdir())


def test_phonon_probe_secures_existing_transcript_file(tmp_path, monkeypatch):
    probe = load_probe('phonon_probe')
    output = tmp_path / 'result.json'
    output.write_text('old fixture')
    output.chmod(0o644)
    result = SimpleNamespace(
        text='synthetic fixture', audio_seconds=1, decode_seconds=0.1,
        truncated=False, segments=[], words=[],
    )
    speech = SimpleNamespace(describe=lambda: {}, transcribe_detailed=lambda _: result)
    monkeypatch.setitem(sys.modules, 'fermion', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'fermion._speech', SimpleNamespace(
        backends=SimpleNamespace(load=lambda *a, **k: speech), fetch=None,
    ))
    monkeypatch.setitem(sys.modules, 'fermion.transcribe', SimpleNamespace(
        _resolve=lambda _: ('repo', 'profile', {'backend': 'fake'}, 'local-model'),
    ))
    monkeypatch.setattr(probe, 'footprint', lambda: {})
    monkeypatch.setattr(sys, 'argv', ['probe', '--engine', 'cpu', '--output', str(output), 'fake-audio'])
    prior = os.umask(0o022)
    try:
        probe.main()
    finally:
        os.umask(prior)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
