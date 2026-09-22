from unittest.mock import patch
import plistlib

import pytest
from scripts import deploy_penny as deploy


def make_installed(tmp_path, monkeypatch, label, tail):
    monkeypatch.setattr(deploy.Path, 'home', lambda: tmp_path)
    path = tmp_path / 'Library/LaunchAgents' / (label + '.plist')
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {'Label': label, 'WorkingDirectory': str(deploy.ROOT),
            'ProgramArguments': [str(deploy.ROOT / 'venv/bin/python3'), *tail]}
    path.write_bytes(plistlib.dumps(data))
    return path


def test_stale_entrypoint_is_not_stamped(tmp_path, monkeypatch):
    make_installed(tmp_path, monkeypatch, 'com.penny.watcher', ['/tmp/stale/watcher.py'])
    with pytest.raises(deploy.DeploymentError, match='runtime_path_mismatch'):
        deploy.installed('com.penny.watcher')


def test_stopped_shared_service_can_be_bootstrapped(tmp_path, monkeypatch):
    label = 'com.penny.shared-whisper'
    make_installed(tmp_path, monkeypatch, label, ['-m', 'shared_whisper.server'])
    backups = tmp_path / 'backups'
    backups.mkdir()
    before = {'label': label, 'loaded': False, 'pid': None, 'revision': None}
    after = {'label': label, 'loaded': True, 'pid': '123', 'revision': 'a' * 40}
    with (patch.object(deploy, 'urlopen', side_effect=OSError),
          patch.object(deploy, 'runtime', side_effect=[before, after]),
          patch.object(deploy, 'command') as command,
          patch('shared_whisper.worker.MacMemoryGuard.has_existing_large_owner', return_value=False)):
        assert deploy.reload_agent(label, 'a' * 40, backups) == after
    assert command.call_args[0][0][1] == 'bootstrap'


@pytest.mark.parametrize('answers,reason', [
    ([' M watcher.py'], 'checkout_dirty'),
    (['', 'feature'], 'checkout_not_main'),
    (['', 'main', 'a' * 40, 'b' * 40 + '\trefs/heads/main'], 'pushed_revision_mismatch'),
])
def test_release_refuses_unpushed_or_unreviewed_code(answers, reason):
    with patch.object(deploy, 'command', side_effect=answers):
        with pytest.raises(deploy.DeploymentError, match=reason):
            deploy.pushed_revision()


def test_runtime_does_not_return_secret_values():
    from subprocess import CompletedProcess
    output = '\n state = running\n pid = 123\n TOKEN => secret-value\n PENNY_SOURCE_REVISION => ' + 'a' * 40
    with patch.object(deploy.subprocess, 'run', return_value=CompletedProcess([], 0, output, '')):
        result = deploy.runtime('com.penny.watcher')
    assert result['revision'] == 'a' * 40
    assert 'secret-value' not in str(result)


def test_drop_runtime_configuration_preserves_existing_credentials(tmp_path, monkeypatch):
    assert hasattr(deploy, 'configure_drop'), 'Safe runtime Drop configuration missing'
    for label in ('com.penny.watcher','com.penny.webhook'):
        path = make_installed(tmp_path,monkeypatch,label,deploy.ENTRYPOINTS[label])
        data = plistlib.loads(path.read_bytes())
        data['EnvironmentVariables']={'EXISTING_SECRET':'keep-me'}
        path.write_bytes(plistlib.dumps(data))
    backup = tmp_path/'backups'
    backup.mkdir()
    deploy.configure_drop('drop-test-secret',backup)
    for label in ('com.penny.watcher','com.penny.webhook'):
        data=plistlib.loads((tmp_path/'Library/LaunchAgents'/f'{label}.plist').read_bytes())
        assert data['EnvironmentVariables']['EXISTING_SECRET']=='keep-me'
        assert data['EnvironmentVariables']['PENNY_DROP_ENABLED']=='true'
    watcher=plistlib.loads((tmp_path/'Library/LaunchAgents/com.penny.watcher.plist').read_bytes())
    assert watcher['EnvironmentVariables']['PENNY_DROP_TOKEN']=='drop-test-secret'
    webhook=plistlib.loads((tmp_path/'Library/LaunchAgents/com.penny.webhook.plist').read_bytes())
    assert 'PENNY_DROP_TOKEN' not in webhook['EnvironmentVariables']


def wrapped_export(tmp_path, monkeypatch):
    label = 'com.penny.export'
    path = make_installed(tmp_path, monkeypatch, label, deploy.ENTRYPOINTS[label])
    data = plistlib.loads(path.read_bytes())
    data['ProgramArguments'] = ['/opt/homebrew/bin/python3',
        str(tmp_path / '.local/libexec/compost/with-storage-volume.py'),
        *data['ProgramArguments']]
    data['EnvironmentVariables'] = {
        'PENNY_BACKUP_ROOT': '/Volumes/fixture/backup',
        'PENNY_BACKUP_VERIFICATION_RECEIPT': '/Volumes/fixture/backup/receipt.json',
        'COMPOST_STORAGE_VOLUME': '/Volumes/fixture',
        'COMPOST_STORAGE_UUID': 'fixture-volume-uuid',
    }
    path.write_bytes(plistlib.dumps(data))
    return path, data


def test_deploy_preserves_known_export_volume_wrapper(tmp_path, monkeypatch):
    path, data = wrapped_export(tmp_path, monkeypatch)
    assert deploy.installed('com.penny.export') == (path, data)


def test_predeployment_backup_uses_installed_guard_and_placement(tmp_path, monkeypatch):
    _, data = wrapped_export(tmp_path, monkeypatch)
    assert hasattr(deploy, 'backup_before_deploy'), 'Installed backup invocation is not preserved'
    with patch.object(deploy, 'command') as command:
        deploy.backup_before_deploy()
    args, kwargs = command.call_args
    assert args[0] == [*data['ProgramArguments'], '--skip-export']
    assert data['EnvironmentVariables'].items() <= kwargs['env'].items()


@pytest.mark.parametrize('replacement', ['/tmp/unknown-wrapper.py', '/tmp/stale/backup_penny.py'])
def test_wrapped_export_rejects_unknown_wrapper_or_stale_target(tmp_path, monkeypatch, replacement):
    path, data = wrapped_export(tmp_path, monkeypatch)
    data['ProgramArguments'][1 if 'wrapper' in replacement else 3] = replacement
    path.write_bytes(plistlib.dumps(data))
    with pytest.raises(deploy.DeploymentError, match='runtime_path_mismatch'):
        deploy.installed('com.penny.export')
