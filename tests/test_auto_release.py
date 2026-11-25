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
        self.unloaded: set[str] = set()

    def __call__(self) -> dict:
        return {label: {'label': label, 'loaded': label not in self.unloaded, 'revision': revision}
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
            self.agents.unloaded = set()
        elif self.result == 'partial':
            self.agents.revisions['com.penny.watcher'] = head
        return {'status': 'activated' if self.result == 'activated' else 'failed',
                'error': self.error, 'services': []}


def run(checkout, tmp_path, agents, deploy, busy=False, **kwargs):
    return release.release_once(checkout, directory=tmp_path / 'state', runtime_fn=agents,
                                deploy_fn=deploy, busy_fn=lambda: busy, **kwargs)


def status(tmp_path) -> dict:
    return json.loads((tmp_path / 'state/status.json').read_text())


def doctor_release(tmp_path, monkeypatch) -> tuple[str, str]:
    """What Doctor's release component reports for the status the job wrote."""
    import doctor
    monkeypatch.setattr(doctor, '_release_status_path', lambda: tmp_path / 'state/status.json')
    return doctor._infer_status('release', doctor._default_probe_release())


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


def test_partial_release_stays_partial_until_retry_converges_it(repos, tmp_path, monkeypatch):
    work, checkout, _ = repos
    agents = Agents(git(checkout, 'rev-parse', 'HEAD'))
    target = commit(work, 'watcher.py', 'v2\n')
    deploy = Deploy(agents, result='partial', error='command_failed:launchctl')
    code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state']) == (1, 'partial')
    assert git(checkout, 'rev-parse', 'HEAD') == target
    # Later runs keep reporting partial (not blocked) and do not deploy again.
    for _ in range(3):
        code, outcome = run(checkout, tmp_path, agents, deploy)
        assert (code, outcome['state'], outcome['reason']) == (1, 'partial', 'command_failed:launchctl')
    assert deploy.calls == 1
    saved = status(tmp_path)
    assert (saved['state'], saved['target_revision']) == ('partial', target)
    assert doctor_release(tmp_path, monkeypatch) == ('unready', 'release_partial')
    # --retry deploys to every agent from the mixed state.
    deploy.result = 'activated'
    code, outcome = run(checkout, tmp_path, agents, deploy, retry=True)
    assert (code, outcome['state'], deploy.calls) == (0, 'released', 2)
    assert set(agents.revisions.values()) == {target}
    assert doctor_release(tmp_path, monkeypatch) == ('ready', 'ok')
    code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state'], deploy.calls) == (0, 'current', 2)


def test_partial_release_is_not_left_by_a_new_merge(repos, tmp_path):
    work, checkout, _ = repos
    old = git(checkout, 'rev-parse', 'HEAD')
    agents = Agents(old)
    first = commit(work, 'watcher.py', 'v2\n')
    deploy = Deploy(agents, result='partial', error='activation_not_verified:com.penny.watcher')
    run(checkout, tmp_path, agents, deploy)
    second = commit(work, 'core.py', 'v2\n')
    code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state'], outcome['target_revision']) == (1, 'partial', second)
    assert outcome['reason'] == 'activation_not_verified:com.penny.watcher'
    assert deploy.calls == 1 and git(checkout, 'rev-parse', 'HEAD') == first
    # --retry fast-forwards to the new main and converges every agent on it.
    deploy.result = 'activated'
    code, outcome = run(checkout, tmp_path, agents, deploy, retry=True)
    assert (code, outcome['state'], deploy.calls) == (0, 'released', 2)
    assert git(checkout, 'rev-parse', 'HEAD') == second
    assert set(agents.revisions.values()) == {second}


def test_retry_from_a_partial_state_that_fails_again_stays_partial(repos, tmp_path):
    work, checkout, _ = repos
    agents = Agents(git(checkout, 'rev-parse', 'HEAD'))
    commit(work, 'watcher.py', 'v2\n')
    deploy = Deploy(agents, result='partial', error='command_failed:launchctl')
    run(checkout, tmp_path, agents, deploy)
    # Busy owner: the retry waits; the next scheduled run is still partial.
    code, outcome = run(checkout, tmp_path, agents, deploy, busy=True, retry=True)
    assert (code, outcome['state'], deploy.calls) == (0, 'waiting', 1)
    code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state']) == (1, 'partial')
    # A retry whose deploy changes nothing still leaves the agents mixed.
    deploy.result, deploy.error = 'failed', 'shared_whisper_busy'
    code, outcome = run(checkout, tmp_path, agents, deploy, retry=True)
    assert (code, outcome['state'], outcome['reason']) == (1, 'partial', 'shared_whisper_busy')
    code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state'], deploy.calls) == (1, 'partial', 2)


def test_partial_release_with_an_unloaded_agent_stays_partial(repos, tmp_path):
    work, checkout, _ = repos
    agents = Agents(git(checkout, 'rev-parse', 'HEAD'))
    target = commit(work, 'watcher.py', 'v2\n')

    def unload_one(repo):
        agents.revisions = {label: target for label in LABELS}
        agents.unloaded = {'com.penny.export'}
        return {'status': 'failed', 'error': 'command_failed:launchctl', 'services': []}

    code, outcome = run(checkout, tmp_path, agents, unload_one)
    assert (code, outcome['state']) == (1, 'partial')
    # Every loaded agent runs main, but one is missing: not current.
    code, outcome = run(checkout, tmp_path, agents, unload_one)
    assert (code, outcome['state'], outcome['reason']) == (1, 'partial', 'command_failed:launchctl')
    deploy = Deploy(agents)
    code, outcome = run(checkout, tmp_path, agents, deploy, retry=True)
    assert (code, outcome['state'], deploy.calls) == (0, 'released', 1)


def test_partial_release_that_unloaded_the_first_agent_stays_partial(repos, tmp_path):
    work, checkout, _ = repos
    old = git(checkout, 'rev-parse', 'HEAD')
    agents = Agents(old)
    commit(work, 'watcher.py', 'v2\n')

    def unload_first(repo):
        agents.unloaded = {'com.penny.shared-whisper'}
        return {'status': 'failed', 'error': 'command_failed:launchctl', 'services': []}

    assert run(checkout, tmp_path, agents, unload_first)[1]['state'] == 'partial'
    code, outcome = run(checkout, tmp_path, agents, unload_first)
    assert (code, outcome['state'], outcome['running_revision']) == (1, 'partial', old)
    # A retry that changes nothing does not turn it into a plain failure.
    code, outcome = run(checkout, tmp_path, agents, unload_first, retry=True)
    assert (code, outcome['state']) == (1, 'partial')


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
    for _ in range(release.FETCH_FAILURE_LIMIT - 1):
        code, outcome = run(checkout, tmp_path, agents, Deploy(agents))
    assert (code, outcome['state'], outcome['reason']) == (1, 'failed', 'fetch_failed')


def _leave_failed(work, checkout, tmp_path, agents):
    commit(work, 'watcher.py', 'v2\n')
    deploy = Deploy(agents, result='failed', error='command_failed:backup_penny.py')
    assert run(checkout, tmp_path, agents, deploy)[1]['state'] == 'failed'


def _leave_blocked(work, checkout, tmp_path, agents):
    commit(work, 'requirements.txt', 'flask\n')
    assert run(checkout, tmp_path, agents, Deploy(agents))[1]['state'] == 'blocked'


def _leave_partial(work, checkout, tmp_path, agents):
    commit(work, 'watcher.py', 'v2\n')
    deploy = Deploy(agents, result='partial', error='command_failed:launchctl')
    assert run(checkout, tmp_path, agents, deploy)[1]['state'] == 'partial'


def _leave_diverged(work, checkout, tmp_path, agents):
    old = agents.revisions['com.penny.export']
    commit(work, 'watcher.py', 'v2\n')
    assert run(checkout, tmp_path, agents, Deploy(agents))[1]['state'] == 'released'
    agents.revisions = {label: old for label in LABELS}
    assert run(checkout, tmp_path, agents, Deploy(agents))[1]['state'] == 'diverged'


@pytest.mark.parametrize(('leave', 'expected'), [
    (_leave_failed, ('failed', 'command_failed:backup_penny.py', 'degraded', 'release_failed')),
    (_leave_blocked, ('blocked', 'manual_release_required', 'degraded', 'release_blocked')),
    (_leave_partial, ('partial', 'command_failed:launchctl', 'unready', 'release_partial')),
    (_leave_diverged, ('diverged', 'running_left_released_revision', 'degraded', 'release_diverged')),
])
@pytest.mark.parametrize('stop', ['fetch', 'hold'])
def test_fetch_failure_or_hold_keeps_a_terminal_status(repos, tmp_path, monkeypatch, leave, expected, stop):
    work, checkout, _ = repos
    agents = Agents(git(checkout, 'rev-parse', 'HEAD'))
    leave(work, checkout, tmp_path, agents)
    before = status(tmp_path)
    if stop == 'fetch':
        git(checkout, 'remote', 'set-url', 'origin', str(tmp_path / 'missing.git'))
    else:
        (tmp_path / 'state/hold').touch()
    detail = {'fetch': 'fetch_failed', 'hold': 'hold_file_present'}[stop]
    deploy = Deploy(agents)
    for _ in range(3):
        code, outcome = run(checkout, tmp_path, agents, deploy)
        assert (code, outcome['state'], outcome['reason'], outcome['detail']) == (1, *expected[:2], detail)
    saved = status(tmp_path)
    assert (saved['state'], saved['reason'], saved['detail']) == (*expected[:2], detail)
    assert saved['target_revision'] == before['target_revision']
    assert doctor_release(tmp_path, monkeypatch) == expected[2:]
    assert deploy.calls == 0
    # Once the run can look again, the status is evaluated afresh.
    if stop == 'fetch':
        git(checkout, 'remote', 'set-url', 'origin', str(tmp_path / 'origin.git'))
    else:
        (tmp_path / 'state/hold').unlink()
    code, outcome = run(checkout, tmp_path, agents, Deploy(agents))
    assert outcome.get('detail') is None and status(tmp_path)['detail'] is None


def test_hold_after_a_good_release_reports_held(repos, tmp_path, monkeypatch):
    work, checkout, _ = repos
    agents = Agents(git(checkout, 'rev-parse', 'HEAD'))
    commit(work, 'watcher.py', 'v2\n')
    run(checkout, tmp_path, agents, Deploy(agents))
    (tmp_path / 'state/hold').touch()
    code, outcome = run(checkout, tmp_path, agents, Deploy(agents))
    assert (code, outcome['state'], outcome['reason']) == (0, 'held', 'hold_file_present')
    assert doctor_release(tmp_path, monkeypatch) == ('ready', 'disabled')


def test_agents_leaving_a_released_revision_are_reported_not_redeployed(repos, tmp_path, monkeypatch):
    work, checkout, _ = repos
    old = git(checkout, 'rev-parse', 'HEAD')
    agents = Agents(old)
    target = commit(work, 'watcher.py', 'v2\n')
    deploy = Deploy(agents)
    assert run(checkout, tmp_path, agents, deploy)[1]['state'] == 'released'
    # A rollback by hand (or restored plists) puts the agents back on old.
    agents.revisions = {label: old for label in LABELS}
    for _ in range(3):
        code, outcome = run(checkout, tmp_path, agents, deploy)
        assert (code, outcome['state'], outcome['reason']) == (1, 'diverged', 'running_left_released_revision')
        assert (outcome['target_revision'], outcome['running_revision']) == (target, old)
    assert deploy.calls == 1
    assert doctor_release(tmp_path, monkeypatch) == ('degraded', 'release_diverged')
    # --retry releases main again.
    code, outcome = run(checkout, tmp_path, agents, deploy, retry=True)
    assert (code, outcome['state'], deploy.calls) == (0, 'released', 2)
    assert set(agents.revisions.values()) == {target}


def test_a_revision_seen_running_is_not_redeployed_after_a_rollback(repos, tmp_path):
    work, checkout, _ = repos
    old = git(checkout, 'rev-parse', 'HEAD')
    target = commit(work, 'watcher.py', 'v2\n')
    git(checkout, 'pull', '-q', '--ff-only', 'origin', 'main')
    agents = Agents(target)  # deployed by hand before the job ran
    deploy = Deploy(agents)
    assert run(checkout, tmp_path, agents, deploy)[1]['state'] == 'current'
    agents.revisions = {label: old for label in LABELS}
    code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state'], deploy.calls) == (1, 'diverged', 0)


def test_a_new_merge_after_a_divergence_is_released(repos, tmp_path):
    work, checkout, _ = repos
    old = git(checkout, 'rev-parse', 'HEAD')
    agents = Agents(old)
    commit(work, 'watcher.py', 'v2\n')
    deploy = Deploy(agents)
    run(checkout, tmp_path, agents, deploy)
    agents.revisions = {label: old for label in LABELS}
    assert run(checkout, tmp_path, agents, deploy)[1]['state'] == 'diverged'
    fixed = commit(work, 'watcher.py', 'v3\n')
    code, outcome = run(checkout, tmp_path, agents, deploy)
    assert (code, outcome['state'], deploy.calls) == (0, 'released', 2)
    assert set(agents.revisions.values()) == {fixed}


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
