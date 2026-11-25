#!/usr/bin/env python3
"""Release merged ``main`` to the installed Penny agents without a person.

The ``com.penny.release`` launch agent runs this every five minutes on the
Mac runtime checkout (install it with ``--install``). One run:

1. takes a lock (exit 75 when another run holds it) and honours the hold
   file ``~/.penny/release/hold``;
2. requires the checkout to be a clean ``main`` and fetches ``origin/main``;
3. compares the revision the agents run with ``origin/main`` by changed
   paths, not by commit count (``RULES`` below; INFRA.md lists the same);
4. fast-forwards the checkout and runs ``scripts/deploy_penny.py --apply``
   unchanged, so every guard of the manual release still applies;
5. writes ``~/.penny/release/status.json``, which Doctor's ``release``
   component reports to the owner's monitoring.

Each target revision is tried once (``--retry`` tries it again). Two refusals change nothing and are
retried on later runs a bounded number of times: a busy shared-ASR owner and
``origin/main`` moving during the deploy. A failed deploy that left every
agent on its old revision returns the checkout to that revision.

Prints one JSON line per run with no command output, plist or credential.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile
from typing import Callable
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LABEL = 'com.penny.release'
START_INTERVAL_SECONDS = 300
DEPLOY_TIMEOUT_SECONDS = 30 * 60
FETCH_TIMEOUT_SECONDS = 120
# A refusal that changed nothing is retried on later runs up to this many
# times (half an hour at five-minute runs); then the release is failed.
RETRY_LIMIT = 6
RETRYABLE_DEPLOY_ERRORS = frozenset({'shared_whisper_busy', 'pushed_revision_mismatch'})
# Twelve failed fetches in a row (an hour) turn waiting into failed.
FETCH_FAILURE_LIMIT = 12
REMEMBERED_TARGETS = 20

# Which changed paths start a release. INFRA.md "Release" must list exactly
# these rules; tests/test_auto_release.py checks that it does.
NON_RELEASE_DIRECTORIES = ('docs/', 'tests/', '.github/')
NON_RELEASE_ROOT_SUFFIX = '.md'
MANUAL_RELEASE_PATHS = ('requirements.txt', 'requirements-asr.lock')
RULES = (
    *((directory + '**', 'not a release') for directory in NON_RELEASE_DIRECTORIES),
    ('*' + NON_RELEASE_ROOT_SUFFIX, 'not a release (repository root only)'),
    *((path, 'blocks the release') for path in MANUAL_RELEASE_PATHS),
)

# Only these launch-environment keys are copied from the installed export
# agent into the release agent; no token or secret is copied.
COPIED_ENVIRONMENT_KEYS = ('PATH', 'LANG', 'LC_ALL', 'PENNY_RUNTIME_ROOT')
COPIED_ENVIRONMENT_PREFIX = 'COMPOST_'
RELEASE_LOG_NAME = 'release.system.log'

EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_BUSY = 75
_SAFE_TEXT = re.compile(r'^[A-Za-z0-9_.:/-]{1,120}$')


class ReleaseError(RuntimeError):
    """A bounded, printable reason a run cannot release."""


def classify(path: str) -> str:
    """Return ``release``, ``ignore`` or ``manual`` for one changed path."""
    if path in MANUAL_RELEASE_PATHS:
        return 'manual'
    if path.startswith(NON_RELEASE_DIRECTORIES):
        return 'ignore'
    if '/' not in path and path.endswith(NON_RELEASE_ROOT_SUFFIX):
        return 'ignore'
    return 'release'


def _safe(text: object) -> str:
    value = str(text or '')
    return value if _SAFE_TEXT.fullmatch(value) else 'unknown'


def _now_text(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def state_dir() -> Path:
    return Path.home() / '.penny/release'


def _deploy_module():
    from scripts import deploy_penny
    return deploy_penny


def git(repo: Path, *args: str, timeout: int = 60) -> str:
    try:
        result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True,
                                text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReleaseError('git_failed:' + args[0]) from exc
    if result.returncode:
        raise ReleaseError('git_failed:' + args[0])
    return result.stdout.strip()


def is_ancestor(repo: Path, older: str, newer: str) -> bool:
    result = subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor', older, newer],
                            capture_output=True, text=True, timeout=60)
    if result.returncode not in (0, 1):
        raise ReleaseError('git_failed:merge-base')
    return result.returncode == 0


def default_runtime() -> dict[str, dict]:
    deploy = _deploy_module()
    return {label: deploy.runtime(label) for label in deploy.LABELS}


def default_busy() -> bool:
    """True while the shared ASR owner is serving a client.

    Checked before each attempt so a busy owner does not cost a backup and a
    test run; deploy_penny.py still makes its own check before any reload.
    """
    try:
        with urlopen('http://127.0.0.1:10311/health', timeout=5) as response:
            return bool(json.load(response).get('active_client'))
    except (OSError, ValueError, AttributeError):
        return False


def default_deploy(repo: Path) -> dict:
    """Run the manual release unchanged and return its final JSON receipt."""
    try:
        result = subprocess.run([sys.executable, str(repo / 'scripts/deploy_penny.py'), '--apply'],
                                cwd=repo, capture_output=True, text=True,
                                timeout=DEPLOY_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return {'status': 'failed', 'error': 'deploy_timeout'}
    except (OSError, subprocess.SubprocessError):
        return {'status': 'failed', 'error': 'deploy_not_started'}
    for line in reversed(result.stdout.splitlines()):
        try:
            receipt = json.loads(line)
        except ValueError:
            continue
        if isinstance(receipt, dict) and 'status' in receipt and 'services' in receipt:
            return receipt
    return {'status': 'failed', 'error': 'deploy_receipt_missing'}


def _read_json(path: Path, default: dict) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default
    return value if isinstance(value, dict) else default


def _write_json(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False,
                                     encoding='utf-8') as handle:
        temporary = Path(handle.name)
        os.chmod(temporary, 0o600)
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _running_revision(runtime: dict[str, dict]) -> str:
    revisions = {item.get('revision') for item in runtime.values() if item.get('loaded')}
    if not revisions or None in revisions:
        raise ReleaseError('running_revision_unknown')
    if len(revisions) > 1:
        raise ReleaseError('running_revision_mixed')
    return revisions.pop()


def _unchanged(before: dict[str, dict], after: dict[str, dict]) -> bool:
    return all(after.get(label, {}).get('loaded') == item.get('loaded')
               and after.get(label, {}).get('revision') == item.get('revision')
               for label, item in before.items())


def _all_at(runtime: dict[str, dict], revision: str) -> bool:
    return bool(runtime) and all(item.get('loaded') and item.get('revision') == revision
                                 for item in runtime.values())


def _release(repo: Path, directory: Path, memory: dict, write_status: Callable[[dict], None],
             runtime_fn: Callable[[], dict], deploy_fn: Callable[[Path], dict],
             busy_fn: Callable[[], bool], fetch: bool) -> dict:
    if (directory / 'hold').exists():
        return {'state': 'held', 'reason': 'hold_file_present'}
    if git(repo, 'symbolic-ref', '--quiet', '--short', 'HEAD') != 'main':
        raise ReleaseError('checkout_not_main')
    if git(repo, 'status', '--porcelain'):
        raise ReleaseError('checkout_dirty')
    if fetch:
        try:
            git(repo, 'fetch', '--quiet', 'origin', '+refs/heads/main:refs/remotes/origin/main',
                timeout=FETCH_TIMEOUT_SECONDS)
        except ReleaseError:
            memory['fetch_failures'] = int(memory.get('fetch_failures', 0)) + 1
            state = 'failed' if memory['fetch_failures'] >= FETCH_FAILURE_LIMIT else 'waiting'
            return {'state': state, 'reason': 'fetch_failed'}
        memory['fetch_failures'] = 0
    target = git(repo, 'rev-parse', '--verify', 'refs/remotes/origin/main^{commit}')
    head = git(repo, 'rev-parse', '--verify', 'HEAD^{commit}')
    before = runtime_fn()
    running = _running_revision(before)
    result = {'target_revision': target, 'running_revision': running}
    if running == target:
        return {**result, 'state': 'current', 'reason': 'running_is_main'}
    try:
        git(repo, 'cat-file', '-e', running + '^{commit}')
    except ReleaseError:
        raise ReleaseError('running_revision_not_on_main') from None
    if not is_ancestor(repo, running, target):
        raise ReleaseError('running_revision_not_on_main')
    if not is_ancestor(repo, head, target):
        raise ReleaseError('checkout_not_on_main')

    changed = [path for path in git(repo, 'diff', '--name-only', '--no-renames', running, target).splitlines() if path]
    manual = [path for path in changed if classify(path) == 'manual']
    release = [path for path in changed if classify(path) == 'release']
    result['release_paths'] = (manual + release)[:20]
    if manual:
        return {**result, 'state': 'blocked', 'reason': 'manual_release_required'}
    if not release:
        return {**result, 'state': 'current', 'reason': 'no_release_paths'}

    attempts = memory.setdefault('attempts', {})
    record = attempts.get(target, {})
    if record.get('outcome') in {'failed', 'partial', 'released'}:
        # Each revision is tried once; a new merge or a manual deploy moves on.
        return {**result, 'state': record['outcome'], 'reason': record.get('reason', 'unknown')}

    if busy_fn():
        return {**result, 'state': 'waiting', 'reason': 'shared_whisper_busy'}
    write_status({**result, 'state': 'running', 'reason': 'deploying'})
    moved = head != target
    if moved:
        git(repo, 'merge', '--ff-only', '--quiet', target)
    receipt = deploy_fn(repo)
    after = runtime_fn()
    if receipt.get('status') == 'activated' and _all_at(after, target):
        attempts[target] = {'outcome': 'released', 'reason': 'activated'}
        return {**result, 'running_revision': target, 'state': 'released', 'reason': 'activated'}

    error = _safe(receipt.get('error') or receipt.get('status'))
    if not _unchanged(before, after):
        attempts[target] = {'outcome': 'partial', 'reason': error}
        return {**result, 'state': 'partial', 'reason': error}
    if moved:
        git(repo, 'reset', '--quiet', '--keep', head)
    if error in RETRYABLE_DEPLOY_ERRORS:
        retries = int(record.get('retries', 0)) + 1
        attempts[target] = {'outcome': 'waiting', 'reason': error, 'retries': retries}
        if retries < RETRY_LIMIT:
            return {**result, 'state': 'waiting', 'reason': error}
    attempts[target] = {'outcome': 'failed', 'reason': error}
    return {**result, 'state': 'failed', 'reason': error}


def release_once(repo: Path = ROOT, *, directory: Path | None = None,
                 runtime_fn: Callable[[], dict] = default_runtime,
                 deploy_fn: Callable[[Path], dict] = default_deploy,
                 busy_fn: Callable[[], bool] = default_busy,
                 fetch: bool = True, retry: bool = False,
                 now: datetime | None = None) -> tuple[int, dict]:
    directory = directory or state_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = open(directory / 'release.lock', 'a')
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return EXIT_BUSY, {'state': 'locked', 'reason': 'another_run_holds_the_lock'}
        memory = _read_json(directory / 'state.json', {})
        if retry:
            # The owner fixed the cause by hand; try the current target again.
            memory['attempts'] = {}

        def write_status(outcome: dict) -> None:
            status = {
                'schema': 1,
                'state': outcome['state'],
                'reason': _safe(outcome.get('reason')),
                'target_revision': outcome.get('target_revision'),
                'running_revision': outcome.get('running_revision'),
                'release_paths': outcome.get('release_paths', []),
                'updated_at': _now_text(now),
            }
            _write_json(directory / 'status.json', status)

        try:
            outcome = _release(repo, directory, memory, write_status, runtime_fn, deploy_fn,
                               busy_fn, fetch)
        except ReleaseError as exc:
            outcome = {'state': 'blocked', 'reason': str(exc)}
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            outcome = {'state': 'failed', 'reason': 'release_error:' + type(exc).__name__}
        attempts = memory.get('attempts', {})
        if len(attempts) > REMEMBERED_TARGETS:
            memory['attempts'] = dict(list(attempts.items())[-REMEMBERED_TARGETS:])
        _write_json(directory / 'state.json', memory)
        write_status(outcome)
        code = EXIT_OK if outcome['state'] in {'current', 'released', 'waiting', 'held'} else EXIT_PROBLEM
        return code, outcome
    finally:
        lock.close()


# ---------------------------------------------------------------- install

def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(['launchctl', *args], capture_output=True, text=True, timeout=30)


def agent_plist(home: Path | None = None) -> tuple[dict, Path | None]:
    """Build the release agent from the installed, validated export agent.

    Returns the plist and the SSD log file the storage guard opens (None when
    the export agent is not guarded).
    """
    home = home or Path.home()
    deploy = _deploy_module()
    _, export = deploy.installed('com.penny.export')
    args = export['ProgramArguments']
    guards = {str(home / '.local/libexec/compost/with-storage-volume.py'),
              str(deploy.ROOT / 'scripts/storage_guard.py')}
    guarded = len(args) >= 3 and args[1] in guards
    python = args[2] if guarded else args[0]
    source = export.get('EnvironmentVariables', {})
    environment = {key: value for key, value in source.items()
                   if key in COPIED_ENVIRONMENT_KEYS or key.startswith(COPIED_ENVIRONMENT_PREFIX)}
    log = None
    if 'PENNY_RUNTIME_LOG' in source:
        log = Path(source['PENNY_RUNTIME_LOG']).with_name(RELEASE_LOG_NAME)
        environment['PENNY_RUNTIME_LOG'] = str(log)
    output = '/dev/null' if guarded else str(home / '.penny/logs' / RELEASE_LOG_NAME)
    data = {
        'Label': LABEL,
        'ProgramArguments': [*(args[:2] if guarded else []), python,
                             str(deploy.ROOT / 'scripts/auto_release.py')],
        'WorkingDirectory': export['WorkingDirectory'],
        'EnvironmentVariables': environment,
        'StartInterval': START_INTERVAL_SECONDS,
        'RunAtLoad': True,
        'KeepAlive': False,
        'ProcessType': 'Background',
        'StandardOutPath': output,
        'StandardErrorPath': output,
    }
    return data, log


def install(launchctl: Callable[..., subprocess.CompletedProcess] = _launchctl) -> dict:
    home = Path.home()
    data, log = agent_plist(home)
    if log is not None:
        os.close(os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600))
    else:
        Path(data['StandardOutPath']).parent.mkdir(parents=True, exist_ok=True)
    path = home / 'Library/LaunchAgents' / (LABEL + '.plist')
    if path.is_symlink():
        raise ReleaseError('plist_symlink')
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        os.chmod(temporary, 0o600)
        plistlib.dump(data, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    target = f'gui/{os.getuid()}/{LABEL}'
    if launchctl('print', target).returncode == 0:
        launchctl('bootout', target)
    if launchctl('bootstrap', f'gui/{os.getuid()}', str(path)).returncode:
        raise ReleaseError('bootstrap_failed')
    if launchctl('print', target).returncode:
        raise ReleaseError('agent_not_loaded')
    return {'status': 'installed', 'label': LABEL, 'start_interval_seconds': START_INTERVAL_SECONDS}


def uninstall(launchctl: Callable[..., subprocess.CompletedProcess] = _launchctl) -> dict:
    target = f'gui/{os.getuid()}/{LABEL}'
    if launchctl('print', target).returncode == 0:
        launchctl('bootout', target)
    path = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
    path.unlink(missing_ok=True)
    # Without a status file Doctor reports release as manual ("disabled").
    (state_dir() / 'status.json').unlink(missing_ok=True)
    return {'status': 'uninstalled', 'label': LABEL}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--install', action='store_true',
                       help='install and load the com.penny.release launch agent')
    group.add_argument('--uninstall', action='store_true',
                       help='unload and remove the launch agent; releases are manual again')
    group.add_argument('--retry', action='store_true',
                       help='run once now and try a commit that already failed again')
    args = parser.parse_args(argv)
    try:
        if args.install:
            print(json.dumps(install(), sort_keys=True))
            return EXIT_OK
        if args.uninstall:
            print(json.dumps(uninstall(), sort_keys=True))
            return EXIT_OK
    except (ReleaseError, OSError, ValueError, subprocess.SubprocessError) as exc:
        error = str(exc) if isinstance(exc, ReleaseError) else type(exc).__name__
        if exc.__class__.__name__ == 'DeploymentError':
            error = str(exc)
        print(json.dumps({'status': 'failed', 'error': _safe(error)}, sort_keys=True))
        return EXIT_PROBLEM
    code, outcome = release_once(retry=args.retry)
    print(json.dumps({key: outcome.get(key) for key in
                      ('state', 'reason', 'target_revision', 'running_revision')}, sort_keys=True))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
