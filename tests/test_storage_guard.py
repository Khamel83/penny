import plistlib
from unittest.mock import Mock

from scripts import storage_guard


def test_guard_refuses_missing_volume_before_opening_logs(monkeypatch):
    monkeypatch.setenv('COMPOST_STORAGE_VOLUME', '/missing-penny-ssd')
    monkeypatch.setenv('COMPOST_STORAGE_UUID', 'expected')
    execute = Mock()
    monkeypatch.setattr(storage_guard.os, 'execv', execute)
    assert storage_guard.main() == 75
    execute.assert_not_called()


def test_guard_refuses_wrong_volume_identity(monkeypatch, tmp_path):
    monkeypatch.setenv('COMPOST_STORAGE_VOLUME', str(tmp_path))
    monkeypatch.setenv('COMPOST_STORAGE_UUID', 'expected')
    monkeypatch.setattr(storage_guard.Path, 'is_mount', lambda self: True)
    monkeypatch.setattr(storage_guard.subprocess, 'check_output', lambda *a, **k:
        plistlib.dumps({'MountPoint': str(tmp_path), 'VolumeUUID': 'wrong'}))
    execute = Mock()
    monkeypatch.setattr(storage_guard.os, 'execv', execute)
    assert storage_guard.main() == 75
    execute.assert_not_called()
