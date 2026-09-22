#!/usr/bin/env python3
"""Run the approved historical recovery independently of an interactive shell.

Reads the installed watcher's private environment without printing it. Holds a
single-run lock, saves metadata progress, and yields the model to new captures.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
from pathlib import Path
import plistlib
import tempfile
import time


def main():
    state = Path.home() / '.penny'
    with (state / 'historical-recovery.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('historical_recovery_already_running')
            return 1
        plist = Path.home() / 'Library/LaunchAgents/com.penny.watcher.plist'
        os.environ.update(plistlib.loads(plist.read_bytes()).get('EnvironmentVariables', {}))
        os.environ['PENNY_SHARED_WHISPER_TIMEOUT_SECONDS'] = '300'
        from backfill_voice_memos import run_backfill
        logging.disable(logging.CRITICAL)
        attempted = 0
        while True:
            report = run_backfill(limit=1)
            attempted += report['attempted_count']
            report['run_attempted_count'] = attempted
            report['observed_at_epoch'] = int(time.time())
            with tempfile.NamedTemporaryFile(mode='w', dir=state, delete=False) as handle:
                temporary = Path(handle.name)
                os.chmod(temporary, 0o600)
                json.dump(report, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, state / 'historical-recovery.json')
            print(json.dumps({'attempted': attempted,
                              'placeholders_remaining': report['placeholder_source_count'],
                              'unindexed_ranges': report['unindexed_ranges'],
                              'failed_this_attempt': report['failed_count']}), flush=True)
            if report['selected_count'] == 0:
                if report['future_source_retry_count']:
                    time.sleep(30)
                    continue
                return 0 if not report['placeholder_source_count'] and not report['unindexed_ranges'] else 2
            time.sleep(1)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error_class': type(exc).__name__}), flush=True)
        raise SystemExit(2)
