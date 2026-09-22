#!/usr/bin/env python3
"""Deploy a clean pushed main checkout to existing local Penny launch agents.

Preserves installed credentials and runtime paths. Prints only revision,
label, PID, and bounded status metadata, never launchctl or plist contents.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LABELS = ('com.penny.shared-whisper', 'com.penny.watcher',
          'com.penny.webhook', 'com.penny.tasks', 'com.penny.export')
ENTRYPOINTS = {
    'com.penny.shared-whisper': ['-m', 'shared_whisper.server'],
    'com.penny.watcher': [str(ROOT / 'watcher.py')],
    'com.penny.webhook': [str(ROOT / 'webhook/server.py')],
    'com.penny.tasks': [str(ROOT / 'tasks_poller.py')],
    'com.penny.export': [str(ROOT / 'scripts/backup_penny.py')],
}


class DeploymentError(RuntimeError):
    pass


def command(args: list[str], *, env=None, allowed=(0,)) -> str:
    result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True,
                            text=True, timeout=300)
    if result.returncode not in allowed:
        step = Path(args[1]).name if len(args) > 1 and args[1].endswith('.py') else Path(args[0]).name
        raise DeploymentError('command_failed:' + step)
    return result.stdout


def pushed_revision() -> str:
    if command(['git', 'status', '--porcelain']).strip():
        raise DeploymentError('checkout_dirty')
    if command(['git', 'branch', '--show-current']).strip() != 'main':
        raise DeploymentError('checkout_not_main')
    sha = command(['git', 'rev-parse', 'HEAD']).strip()
    remote = command(['git', 'ls-remote', 'origin', 'refs/heads/main']).split()
    if not remote or remote[0] != sha:
        raise DeploymentError('pushed_revision_mismatch')
    return sha


def runtime(label: str) -> dict:
    result = subprocess.run(['launchctl', 'print', f'gui/{os.getuid()}/{label}'],
                            capture_output=True, text=True, timeout=10)
    def field(pattern):
        match = re.search(pattern, result.stdout)
        return match.group(1) if match else None
    return {'label': label, 'loaded': result.returncode == 0,
            'revision': field(r'PENNY_SOURCE_REVISION => ([0-9a-f]{40})'),
            'pid': field(r'\n\s*pid = (\d+)'),
            'state': field(r'\n\s*state = ([a-z ]+)')}


def installed(label: str) -> tuple[Path, dict]:
    path = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
    if path.is_symlink():
        raise DeploymentError('plist_symlink:' + label)
    data = plistlib.loads(path.read_bytes())
    args = data.get('ProgramArguments', [])
    if (data.get('Label') != label or data.get('WorkingDirectory') != str(ROOT)
            or not args or args[0] not in {str(ROOT / 'venv/bin/python'), str(ROOT / 'venv/bin/python3')}
            or args[1:] != ENTRYPOINTS[label]
            or data.get('Program', args[0]) != args[0]):
        raise DeploymentError('runtime_path_mismatch:' + label)
    return path, data


def reload_agent(label: str, sha: str, backup_dir: Path) -> dict:
    path, data = installed(label)
    old_worker = None
    before = runtime(label)
    if label == 'com.penny.shared-whisper':
        try:
            with urlopen('http://127.0.0.1:10311/health', timeout=5) as response:
                health = json.load(response)
        except OSError:
            from shared_whisper.worker import MacMemoryGuard
            if before['pid'] or MacMemoryGuard().has_existing_large_owner():
                raise DeploymentError('shared_whisper_owner_unverified')
            health = {}
        for _ in range(120):
            if not health.get('active_client'):
                break
            time.sleep(0.5)
            with urlopen('http://127.0.0.1:10311/health', timeout=5) as response:
                health = json.load(response)
        else:
            raise DeploymentError('shared_whisper_busy')
        old_worker = health.get('worker_pid')
    shutil.copy2(path, backup_dir / path.name)
    os.chmod(backup_dir / path.name, 0o600)
    data.setdefault('EnvironmentVariables', {})['PENNY_SOURCE_REVISION'] = sha
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        os.chmod(temporary, 0o600)
        plistlib.dump(data, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    target = f'gui/{os.getuid()}/{label}'
    if before['loaded']:
        command(['launchctl', 'bootout', target])
    for old_pid in filter(None, (before['pid'], old_worker)):
        for _ in range(100):
            try:
                os.kill(int(old_pid), 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            raise DeploymentError('old_process_still_running:' + label)
    command(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(path)])
    for _ in range(100):
        after = runtime(label)
        if (after['loaded'] and after['revision'] == sha
                and (not data.get('KeepAlive') or after['pid'])):
            return after
        time.sleep(0.1)
    raise DeploymentError('activation_not_verified:' + label)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='back up and activate pushed main')
    args = parser.parse_args()
    receipt = {'status': 'unverified', 'services': []}
    try:
        sha = pushed_revision()
        receipt['revision'] = sha
        for label in LABELS:
            installed(label)
        receipt['services'] = [runtime(label) for label in LABELS]
        if args.apply:
            command([str(ROOT / 'venv/bin/python'), 'scripts/trust_check.py'])
            command([str(ROOT / 'venv/bin/python'), 'scripts/backup_penny.py', '--skip-export'])
            directory = Path.home() / '.penny/deployments' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            directory.mkdir(parents=True, mode=0o700)
            receipt['services'] = []
            for label in LABELS:
                receipt['services'].append(reload_agent(label, sha, directory))
                print(json.dumps(receipt['services'][-1]), flush=True)
            receipt['status'] = 'activated'
            (directory / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            os.chmod(directory / 'receipt.json', 0o600)
        else:
            receipt['status'] = 'current' if all(
                r['loaded'] and r['revision'] == sha
                and (r['label'] == 'com.penny.export' or r['pid'])
                for r in receipt['services']
            ) else 'revision_drift'
        print(json.dumps(receipt, sort_keys=True))
        return 0 if receipt['status'] in {'current', 'activated'} else 1
    except (DeploymentError, OSError, ValueError, subprocess.SubprocessError) as exc:
        receipt['status'] = 'failed'
        receipt['error'] = str(exc) if isinstance(exc, DeploymentError) else type(exc).__name__
        print(json.dumps(receipt, sort_keys=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
