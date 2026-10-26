from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import patch

import pytest

from transcript_view import maintain_view


@pytest.fixture
def view():
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        db = base / 'ledger.db'
        conn = sqlite3.connect(db)
        conn.execute('''CREATE TABLE transcripts (id INTEGER, source TEXT,
            transcript TEXT, recorded_at TEXT, created_at TEXT,
            quality_status TEXT, audio_sha256 TEXT, transcription_backend TEXT,
            transcription_model TEXT)''')
        conn.executemany('INSERT INTO transcripts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', [
            (1, 'iCloud', 'accepted words', None, '2026-01-01', 'passed', '', None, None),
            (2, 'iCloud', 'held words', None, '2026-01-02', 'needs_review', '', None, None)])
        conn.commit()
        conn.close()
        root = base / 'view'
        root.mkdir()
        yield db, root, base / 'scratch'


def test_reconcile_retains_names_history_and_updates_text_without_duplicates(view):
    db, root, scratch = view
    old = root / '2026' / 'old__p1__name.md'
    old.parent.mkdir()
    old.write_text('old accepted snapshot')
    held = root / 'held__p2__name.md'
    held.write_text('preserved history')
    result = maintain_view(*view)
    assert result['accepted'] == 1 and result['retained_history'] == 1
    assert 'accepted words' in old.read_text()
    assert held.read_text() == 'preserved history'
    assert 'retained history' in (root / 'INDEX.md').read_text()
    before = old.stat().st_mtime_ns
    assert maintain_view(*view)['changed'] == 0
    assert old.stat().st_mtime_ns == before
    conn = sqlite3.connect(db)
    conn.execute("UPDATE transcripts SET transcript='corrected words' WHERE id=1")
    conn.execute("INSERT INTO transcripts VALUES (3,'iCloud','new accepted words',NULL,'2026-01-03','passed','',NULL,NULL)")
    conn.commit()
    conn.close()
    assert maintain_view(*view)['changed'] == 2
    assert 'corrected words' in old.read_text()
    assert len(list(root.rglob('*.md'))) == 4
    assert 'transcript__p3__.md' in (root / 'INDEX.md').read_text()
    assert all(p.suffix == '.md' for p in root.rglob('*') if p.is_file())


def test_unaccepted_new_rows_never_export(view):
    maintain_view(*view)
    assert not any('__p2__' in p.name for p in view[1].iterdir())


def test_failure_before_index_is_retryable(view):
    with patch('transcript_view.os.replace', side_effect=OSError('offline')):
        with pytest.raises(OSError):
            maintain_view(*view)
    assert not (view[1] / 'INDEX.md').exists()
    assert list(view[2].glob('tmp*')) == []
    assert maintain_view(*view)['changed'] == 1


def test_duplicate_and_symlink_refuse_without_writes(view):
    root = view[1]
    (root / 'a__p1__.md').write_text('original')
    (root / 'b__p1__.md').write_text('duplicate')
    with pytest.raises(ValueError, match='duplicate'):
        maintain_view(*view)
    (root / 'b__p1__.md').unlink()
    (root / 'jump').symlink_to(view[0])
    with pytest.raises(ValueError, match='symlink'):
        maintain_view(*view)
    assert (root / 'a__p1__.md').read_text() == 'original'


def test_watcher_bounds_file_provider_and_keeps_output_private():
    import subprocess
    import watcher
    with (patch('transcript_view.DEFAULT_ROOT') as root,
          patch('subprocess.run', side_effect=subprocess.TimeoutExpired('view', 30)) as run):
        root.is_dir.return_value = True
        watcher._process_transcript_view()
    assert run.call_args.kwargs['timeout'] == 30
    assert run.call_args.kwargs['capture_output'] is True
