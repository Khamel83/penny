from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess

import pytest

from scripts import auto_release as release

ROOT = Path(__file__).resolve().parents[1]
LABELS = ('com.penny.shared-whisper', 'com.penny.watcher', 'com.penny.export')


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test',
                             '-c', 'user.email=test@example.net', *args],
                            capture_output=True, text=True, check=True)
    return result.stdout.strip()


def commit(work: Path, path: str, text: str) -> str:
    target = work / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    git(work, 'add', path)
    git(work, 'commit', '-q', '-m', 'change ' + path)
    git(work, 'push', '-q', 'origin', 'main')
    return git(work, 'rev-parse', 'HEAD')


@pytest.fixture
def repos(tmp_path):
    origin = tmp_path / 'origin.git'
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(origin)], check=True)
    work = tmp_path / 'work'
    subprocess.run(['git', 'clone', '-q', str(origin), str(work)], check=True,
                   capture_output=True)
    git(work, 'checkout', '-q', '-b', 'main')
    first = commit(work, 'watcher.py', 'v1\n')
    commit(work, 'README.md', 'readme\n')
    checkout = tmp_path / 'checkout'
    subprocess.run(['git', 'clone', '-q', str(origin), str(checkout)], check=True,
                   capture_output=True)
    return work, checkout, first


class Agents:
    def __init__(self, revision: str):
        self.revisions = {label: revision for label in LABELS}

    def __call__(self) -> dict:
        return {label: {'label': label, 'loaded': True, 'revision': revision}
                for label, revision in self.revisions.items()}


class Deploy:
    """Stands in for deploy_penny.py --apply."""

    def __init__(self, agents: Agents, result: str = 'activated', error: str | None = None):
        self.agents, self.result, self.error, self.calls = agents, result, error, 0

    def __call__(self, repo: Path) -> dict:
        self.calls += 1
        head = git(repo, 'rev-parse', 'HEAD')
        if self.result == 'activated':
            self.agents.revisions = {label: head for label in LABELS}
        elif self.result == 'partial':
            self.agents.revisions['com.penny.watcher'] = head
        return {'status': 'activated' if self.result == 'activated' else 'failed',
                'error': self.error, 'services': []}


def run(checkout, tmp_path, agents, deploy, busy=False, **kwargs):
    return release.release_once(checkout, directory=tmp_path / 'state', runtime_fn=agents,
                                deploy_fn=deploy, busy_fn=lambda: busy, **kwargs)


def status(tmp_path) -> dict:
    return json.loads((tmp_path / 'state/status.json').read_text())


def test_classify_follows_the_documented_rules():
    assert release.classify('docs/runbook.md') == 'ignore'
    assert release.classify('tests/test_x.py') == 'ignore'
    assert release.classify('.github/workflows/tests.yml') == 'ignore'
    assert release.classify('HANDOFF.md') == 'ignore'
    assert release.classify('shared_whisper/README.md') == 'release'
    assert release.classify('watcher.py') == 'release'
    assert release.classify('launchd/com.penny.watcher.plist.template') == 'release'
    assert release.classify('requirements.txt') == 'manual'
    assert release.classify('requirements-asr.lock') == 'manual'


def test_infra_release_paths_match_the_code():
    text = (ROOT / 'INFRA.md').read_text()
    block = re.search(r'<!-- release-paths:begin -->\n(.*?)\n<!-- release-paths:end -->', text, re.S)
    assert block, 'INFRA.md must list the release paths'
    expected = [f'- `{pattern}`: {meaning}' for pattern, meaning in release.RULES]
    expected.append('- every other path: release')
    assert block.group(1).splitlines() == expected


def test_docs_only_merge_is_not_a_release(repos, tmp_path):
    work, checkout, first = repos
    agents = Agents(git(checkout, 'rev-parse', 'HEAD'))
    head = git(checkout, 'rev-parse', 'HEAD')
    commit(work, 'docs/note.md', 'note\n')
    commit(work, 'tests/test_note.py', 'pass\n')
    deploy = Deploy(agents)
    code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state'], outcome['reason']) == (0, 'current', 'no_release_paths')
    assert deploy.calls == 0
    assert git(checkout, 'rev-parse', 'HEAD') == head
    assert status(tmp_path)['state'] == 'current'


def test_code_merge_fast_forwards_and_deploys(repos, tmp_path):
    work, checkout, _ = repos
    agents = Agents(git(checkout, 'rev-parse', 'HEAD'))
    target = commit(work, 'watcher.py', 'v2\n')
    deploy = Deploy(agents)
    code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state']) == (0, 'released')
    assert deploy.calls == 1
    assert git(checkout, 'rev-parse', 'HEAD') == target
    saved = status(tmp_path)
    assert saved['state'] == 'released' and saved['target_revision'] == target
    assert saved['release_paths'] == ['watcher.py']
    assert oct((tmp_path / 'state/status.json').stat().st_mode & 0o777) == '0o600'
    # The next run finds the agents on main and does nothing.
    code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state'], deploy.calls) == (0, 'current', 1)


def test_busy_shared_asr_is_retried_then_failed(repos, tmp_path):
    work, checkout, _ = repos
    head = git(checkout, 'rev-parse', 'HEAD')
    agents = Agents(head)
    commit(work, 'watcher.py', 'v2\n')
    deploy = Deploy(agents, result='failed', error='shared_whisper_busy')
    for _ in range(release.RETRY_LIMIT - 1):
        code, outcome = run(checkout, tmp_path, agents, deploy)
        assert (code, outcome['state'], outcome['reason']) == (0, 'waiting', 'shared_whisper_busy')
        assert git(checkout, 'rev-parse', 'HEAD') == head
    code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state']) == (1, 'failed')
    assert deploy.calls == release.RETRY_LIMIT
    run(checkout, tmp_path, agents, deploy)
    assert deploy.calls == release.RETRY_LIMIT


def test_busy_owner_waits_without_starting_a_deploy(repos, tmp_path):
    work, checkout, _ = repos
    head = git(checkout, 'rev-parse', 'HEAD')
    agents = Agents(head)
    commit(work, 'watcher.py', 'v2\n')
    deploy = Deploy(agents)
    for _ in range(release.RETRY_LIMIT + 2):
        code, outcome = run(checkout, tmp_path, agents, deploy, busy=True)
        assert (code, outcome['state'], outcome['reason']) == (0, 'waiting', 'shared_whisper_busy')
    assert deploy.calls == 0 and git(checkout, 'rev-parse', 'HEAD') == head
    code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state']) == (0, 'released')


def test_failed_deploy_is_tried_once_and_retry_tries_again(repos, tmp_path):
    work, checkout, _ = repos
    head = git(checkout, 'rev-parse', 'HEAD')
    agents = Agents(head)
    commit(work, 'watcher.py', 'v2\n')
    deploy = Deploy(agents, result='failed', error='command_failed:backup_penny.py')
    code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state'], outcome['reason']) == (1, 'failed', 'command_failed:backup_penny.py')
    assert git(checkout, 'rev-parse', 'HEAD') == head
    run(checkout, tmp_path, agents, deploy)
    assert deploy.calls == 1
    deploy.result = 'activated'
    code, outcome = run(checkout, tmp_path, agents, deploy, retry=True)
    assert (code, outcome['state'], deploy.calls) == (0, 'released', 2)


def test_partial_release_is_reported_and_not_repeated(repos, tmp_path):
    work, checkout, _ = repos
    agents = Agents(git(checkout, 'rev-parse', 'HEAD'))
    target = commit(work, 'watcher.py', 'v2\n')
    deploy = Deploy(agents, result='partial', error='command_failed:launchctl')
    code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state']) == (1, 'partial')
    assert git(checkout, 'rev-parse', 'HEAD') == target
    code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state'], deploy.calls) == (1, 'blocked', 1)
    assert outcome['reason'] == 'running_revision_mixed'


def test_dependency_change_blocks_until_deployed_by_hand(repos, tmp_path):
    work, checkout, _ = repos
    agents = Agents(git(checkout, 'rev-parse', 'HEAD'))
    commit(work, 'watcher.py', 'v2\n')
    commit(work, 'requirements.txt', 'flask\n')
    deploy = Deploy(agents)
    code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state'], outcome['reason']) == (1, 'blocked', 'manual_release_required')
    assert deploy.calls == 0


@pytest.mark.parametrize('problem', ['dirty', 'branch', 'mixed', 'unknown', 'foreign'])
def test_unsafe_checkout_or_runtime_blocks(repos, tmp_path, problem):
    work, checkout, _ = repos
    agents = Agents(git(checkout, 'rev-parse', 'HEAD'))
    commit(work, 'watcher.py', 'v2\n')
    expected = {
        'dirty': 'checkout_dirty',
        'branch': 'checkout_not_main',
        'mixed': 'running_revision_mixed',
        'unknown': 'running_revision_unknown',
        'foreign': 'running_revision_not_on_main',
    }[problem]
    if problem == 'dirty':
        (checkout / 'watcher.py').write_text('local edit\n')
    elif problem == 'branch':
        git(checkout, 'checkout', '-q', '-b', 'other')
    elif problem == 'mixed':
        agents.revisions['com.penny.export'] = '0' * 40
    elif problem == 'unknown':
        agents.revisions['com.penny.export'] = None
    else:
        agents.revisions = {label: 'f' * 40 for label in LABELS}
    deploy = Deploy(agents)
    code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state'], outcome['reason']) == (1, 'blocked', expected)
    assert deploy.calls == 0


def test_hold_file_and_lock_stop_a_run(repos, tmp_path):
    work, checkout, _ = repos
    agents = Agents(git(checkout, 'rev-parse', 'HEAD'))
    commit(work, 'watcher.py', 'v2\n')
    deploy = Deploy(agents)
    (tmp_path / 'state').mkdir()
    (tmp_path / 'state/hold').touch()
    code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state']) == (0, 'held')
    (tmp_path / 'state/hold').unlink()
    with open(tmp_path / 'state/release.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state']) == (75, 'locked')
    assert deploy.calls == 0


def test_fetch_failure_waits(repos, tmp_path):
    _, checkout, _ = repos
    agents = Agents(git(checkout, 'rev-parse', 'HEAD'))
    git(checkout, 'remote', 'set-url', 'origin', str(tmp_path / 'missing.git'))
    code, outcome = run(checkout, tmp_path, agents, Deploy(agents))
    assert (code, outcome['state'], outcome['reason']) == (0, 'waiting', 'fetch_failed')


class Launchctl:
    def __init__(self):
        self.calls, self.loaded = [], False

    def __call__(self, *args):
        self.calls.append(args[0])
        if args[0] == 'bootstrap':
            self.loaded = True
        elif args[0] == 'bootout':
            self.loaded = False
        code = 0 if args[0] != 'print' or self.loaded else 113
        return subprocess.CompletedProcess(args, code, '', '')


def test_install_reuses_the_export_guard_without_secrets(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    agents_dir = home / 'Library/LaunchAgents'
    agents_dir.mkdir(parents=True)
    ssd_logs = tmp_path / 'ssd/logs'
    ssd_logs.mkdir(parents=True)
    monkeypatch.setenv('HOME', str(home))
    guard = str(home / '.local/libexec/compost/with-storage-volume.py')
    python = str(ROOT / 'venv/bin/python')
    export = {
        'Label': 'com.penny.export',
        'ProgramArguments': ['/opt/homebrew/bin/python3', guard, python,
                             str(ROOT / 'scripts/backup_penny.py')],
        'WorkingDirectory': str(home),
        'EnvironmentVariables': {
            'PATH': '/usr/bin:/bin',
            'COMPOST_STORAGE_VOLUME': str(tmp_path / 'ssd'),
            'COMPOST_STORAGE_UUID': 'UUID',
            'PENNY_RUNTIME_ROOT': str(tmp_path / 'ssd'),
            'PENNY_RUNTIME_LOG': str(ssd_logs / 'export.system.log'),
            'PENNY_BACKUP_REMOTE': 'homelab:/mnt/main2/backups/penny',
            'SLACK_BOT_TOKEN': 'secret-token',
            'PENNY_SOURCE_REVISION': 'a' * 40,
        },
    }
    (agents_dir / 'com.penny.export.plist').write_bytes(plistlib.dumps(export))
    launchctl = Launchctl()
    assert release.install(launchctl)['status'] == 'installed'
    path = agents_dir / 'com.penny.release.plist'
    data = plistlib.loads(path.read_bytes())
    assert data['ProgramArguments'] == ['/opt/homebrew/bin/python3', guard, python,
                                        str(ROOT / 'scripts/auto_release.py')]
    assert data['StartInterval'] == 300 and data['RunAtLoad'] is True
    assert data['StandardOutPath'] == '/dev/null'
    assert data['EnvironmentVariables'] == {
        'PATH': '/usr/bin:/bin',
        'COMPOST_STORAGE_VOLUME': str(tmp_path / 'ssd'),
        'COMPOST_STORAGE_UUID': 'UUID',
        'PENNY_RUNTIME_ROOT': str(tmp_path / 'ssd'),
        'PENNY_RUNTIME_LOG': str(ssd_logs / 'release.system.log'),
    }
    assert 'secret-token' not in path.read_text(errors='ignore')
    assert oct(path.stat().st_mode & 0o777) == '0o600'
    assert oct((ssd_logs / 'release.system.log').stat().st_mode & 0o777) == '0o600'
    assert launchctl.calls[-2:] == ['bootstrap', 'print']
    # Reinstalling replaces the loaded agent.
    release.install(launchctl)
    assert 'bootout' in launchctl.calls

    (home / '.penny/release').mkdir(parents=True)
    (home / '.penny/release/status.json').write_text('{}')
    assert release.uninstall(launchctl)['status'] == 'uninstalled'
    assert not path.exists()
    assert not (home / '.penny/release/status.json').exists()


def test_install_refuses_an_unvalidated_export_agent(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    (home / 'Library/LaunchAgents').mkdir(parents=True)
    monkeypatch.setenv('HOME', str(home))
    export = {'Label': 'com.penny.export', 'ProgramArguments': ['/bin/sh', '-c', 'true'],
              'WorkingDirectory': str(ROOT)}
    (home / 'Library/LaunchAgents/com.penny.export.plist').write_bytes(plistlib.dumps(export))
    from scripts import deploy_penny
    with pytest.raises(deploy_penny.DeploymentError):
        release.install(Launchctl())
    assert not (home / 'Library/LaunchAgents/com.penny.release.plist').exists()
