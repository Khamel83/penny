"""Rebuildable, accepted-text-only iCloud projection of the canonical ledger.

Runs as a bounded child of the existing watcher, never as a second scheduler.
No raw content or paths are printed. Existing legacy files are retained even
when their current ledger quality is not passed; they are not re-exported.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from urllib.parse import quote

from archive import _markdown_bytes, fsync_directory

DEFAULT_ROOT = (Path.home() / 'Library/Mobile Documents/com~apple~CloudDocs'
                / 'Sync/Penny Transcripts')
IDENTITY = re.compile(r'__p([1-9][0-9]*)__')


def _write(path: Path, payload: bytes, scratch: Path) -> bool:
    if path.is_symlink():
        raise ValueError('view_symlink')
    if path.exists() and path.read_bytes() == payload:
        return False
    # Stage outside iCloud on the same filesystem. Never leave temporary or
    # conflict generations in the shared view, including after a killed child.
    with tempfile.NamedTemporaryFile(dir=scratch, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            os.chmod(temporary, 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
            fsync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)
    if path.read_bytes() != payload:
        raise OSError('view_readback_failed')
    return True


def maintain_view(db: Path, root: Path, scratch: Path) -> dict[str, int]:
    """Idempotently reconcile files by canonical ID; commit the index last.

    The file readback and index are the projection receipt. A private flock
    serializes concurrent callers. No schema, capture or delivery state changes.
    """
    if not root.is_dir() or root.is_symlink():
        raise ValueError('view_root_unavailable')
    scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
    if scratch.is_symlink() or scratch.resolve().is_relative_to(root.resolve()):
        raise ValueError('view_scratch_unsafe')
    os.chmod(scratch, 0o700)
    if scratch.stat().st_dev != root.stat().st_dev:
        raise ValueError('view_scratch_wrong_filesystem')
    with (scratch / 'view.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _reconcile(db, root, scratch)


def _reconcile(db: Path, root: Path, scratch: Path) -> dict[str, int]:
    names: dict[int, Path] = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('view_symlink')
        if path.is_dir():
            continue
        if path == root / 'INDEX.md':
            continue
        match = IDENTITY.search(path.name)
        if path.suffix != '.md' or match is None:
            raise ValueError('view_unknown_file')
        identity = int(match[1])
        if identity in names:
            raise ValueError('view_duplicate_identity')
        names[identity] = path
    conn = sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute('''SELECT id, source, transcript, recorded_at,
            created_at, quality_status, audio_sha256, transcription_backend,
            transcription_model FROM transcripts ORDER BY id''').fetchall()
    finally:
        conn.close()
    by_id = {row['id']: row for row in rows}
    if names.keys() - by_id.keys():
        raise ValueError('view_unknown_identity')
    changed = 0
    accepted = 0
    for row in rows:
        if row['quality_status'] != 'passed' or not row['transcript'].strip():
            continue
        identity = row['id']
        path = names.get(identity, root / f'transcript__p{identity}__.md')
        payload = _markdown_bytes(
            transcript_id=identity, source=row['source'],
            captured_at=row['recorded_at'] or row['created_at'],
            transcript=row['transcript'], audio_sha256=row['audio_sha256'] or '',
            transcript_sha256=hashlib.sha256(row['transcript'].encode()).hexdigest(),
            backend=row['transcription_backend'], model=row['transcription_model'],
            quality_status='passed')
        changed += int(_write(path, payload, scratch))
        names[identity] = path
        accepted += 1
    index = ['# Penny Transcripts', '',
             'Text projection of the Penny ledger. Audio remains outside this view.',
             'Retained history is preserved unchanged and is not newly accepted.', '',
             '| Canonical ID | Markdown | Ledger quality |',
             '| --- | --- | --- |']
    for identity, path in sorted(names.items()):
        quality = 'passed' if (by_id[identity]['quality_status'] == 'passed'
                              and by_id[identity]['transcript'].strip()) else 'retained history'
        link = quote(path.relative_to(root).as_posix(), safe='/')
        index.append(f'| {identity} | [Transcript]({link}) | {quality} |')
    index_changed = _write(root / 'INDEX.md', ('\n'.join(index) + '\n').encode(), scratch)
    return {'accepted': accepted, 'retained_history': len(names) - accepted,
            'changed': changed, 'index_changed': int(index_changed)}


def main() -> int:
    from transcript_log import TRANSCRIPT_DB_PATH
    try:
        result = maintain_view(TRANSCRIPT_DB_PATH, DEFAULT_ROOT,
                              Path.home() / 'Library/Caches/Penny/transcript-view')
    except Exception:
        print(json.dumps({'state': 'failed', 'reason': 'view_unavailable'}))
        return 1
    print(json.dumps({'state': 'verified', **result}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
