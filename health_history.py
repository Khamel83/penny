"""Explicit, exact-record health acknowledgements; never change delivery state."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote

import transcript_log

SCHEMA = 'penny.health-history/v1'
# Only terminal history is eligible. A changed state, timestamp, attempt or
# identity invalidates its fingerprint and makes the exception alert again.
GROUPS = {
    'apple_effects': {
        'quarantined': "SELECT effect_key, transcript_id, state, last_error_code, attempt_count, updated_at FROM apple_effects WHERE state='quarantined'",
    },
    'maya': {
        'dead_letter': "SELECT id, maya_delivery_status, maya_dead_letter_at, maya_dead_letter_reason, maya_delivery_attempt_count, updated_at FROM transcripts WHERE maya_delivery_status='dead_letter'",
    },
    'voice_memos': {
        'historical_failure': "SELECT recording_pk, status, terminal_at, error_message, attempt_count, updated_at FROM voice_memo_ingest WHERE status='failed_terminal'",
        'unavailable': "SELECT recording_pk, status, terminal_at, error_message, attempt_count, updated_at FROM voice_memo_ingest WHERE status='unavailable'",
    },
}


def history_path() -> Path:
    return Path(os.environ.get('PENNY_HEALTH_HISTORY_FILE', '~/.penny/health-history.json')).expanduser()


def snapshot(component: str | None = None) -> dict[str, list[str]]:
    path = transcript_log.TRANSCRIPT_DB_PATH.resolve()
    conn = sqlite3.connect(f'file:{quote(str(path), safe="/")}?mode=ro', uri=True)
    try:
        result = {}
        for name, groups in GROUPS.items():
            if component is not None and component != name:
                continue
            for group, query in groups.items():
                if group == 'dead_letter':
                    query += ' AND ' + transcript_log._maya_health_predicate()
                result[group] = sorted(
                    hashlib.sha256(json.dumps(list(row), separators=(',', ':')).encode()).hexdigest()
                    for row in conn.execute(query)
                )
        return result
    finally:
        conn.close()


def acknowledge() -> Path:
    """Freeze the reviewed set once; never silently advance an existing set."""
    payload = {'schema': SCHEMA, 'acknowledged_at': datetime.now(timezone.utc).isoformat(),
               'records': snapshot()}
    path = history_path()
    # Exclusive creation refuses an existing file or symlink. Interrupted
    # writes remain invalid and fail closed in the Doctor.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return path


def acknowledged_counts(component: str) -> dict[str, int]:
    path = history_path()
    try:
        with path.open() as stream:
            raw = stream.read(1024 * 1024 + 1)
    except FileNotFoundError:
        return {}
    if len(raw) > 1024 * 1024:
        raise ValueError('health_history_too_large')
    payload = json.loads(raw)
    records = payload.get('records') if isinstance(payload, dict) else None
    expected = {group for groups in GROUPS.values() for group in groups}
    if not isinstance(records, dict) or payload.get('schema') != SCHEMA or set(records) != expected:
        raise ValueError('health_history_invalid')
    for values in records.values():
        if not isinstance(values, list) or any(not isinstance(v, str) or not re.fullmatch(r'[0-9a-f]{64}', v) for v in values):
            raise ValueError('health_history_invalid')
    current = snapshot(component)
    return {f'acknowledged_{group}_count': len(set(values) & set(records[group]))
            for group, values in current.items()}
