"""Acknowledgement applies to exact terminal records, never future failures."""
import json
import sqlite3

import pytest


def ledger(tmp_path, monkeypatch):
    import transcript_log
    path = tmp_path / 'ledger.sqlite'
    monkeypatch.setattr(transcript_log, 'TRANSCRIPT_DB_PATH', path)
    c = sqlite3.connect(path)
    c.executescript('''
      CREATE TABLE apple_effects(effect_key TEXT, transcript_id INTEGER,
        state TEXT, last_error_code TEXT, attempt_count INTEGER, updated_at TEXT);
      CREATE TABLE transcripts(id INTEGER, maya_delivery_status TEXT,
        maya_dead_letter_at TEXT, maya_dead_letter_reason TEXT,
        maya_delivery_attempt_count INTEGER, updated_at TEXT);
      CREATE TABLE voice_memo_ingest(recording_pk INTEGER, status TEXT,
        terminal_at TEXT, error_message TEXT, attempt_count INTEGER, updated_at TEXT);
      INSERT INTO apple_effects VALUES('effect1',493,'quarantined','timeout_uncertain',17,'2026-08-12');
      INSERT INTO transcripts VALUES(735,'dead_letter','2026-09-11','attempt_cap',20,'2026-09-11');
      INSERT INTO voice_memo_ingest VALUES(112,'failed_terminal','2026-09-22','file_not_downloaded',0,'2026-09-22');
      INSERT INTO voice_memo_ingest VALUES(293,'unavailable','2026-08-10','file_not_downloaded',8,'2026-08-10');
    ''')
    c.commit()
    monkeypatch.setenv('PENNY_HEALTH_HISTORY_FILE', str(tmp_path / 'history.json'))
    return c


def test_acknowledgement_keeps_rows_and_only_matches_exact_exceptions(tmp_path, monkeypatch):
    from health_history import acknowledge, acknowledged_counts
    c = ledger(tmp_path, monkeypatch)
    assert acknowledged_counts('apple_effects') == {}
    acknowledge()
    assert acknowledged_counts('apple_effects') == {'acknowledged_quarantined_count': 1}
    assert acknowledged_counts('maya') == {'acknowledged_dead_letter_count': 1}
    assert acknowledged_counts('voice_memos') == {
        'acknowledged_historical_failure_count': 1, 'acknowledged_unavailable_count': 1}
    c.execute("INSERT INTO apple_effects VALUES('effect2',494,'quarantined','timeout_uncertain',17,'2026-10-19')")
    c.execute("UPDATE apple_effects SET attempt_count=18 WHERE effect_key='effect1'")
    c.execute("UPDATE transcripts SET maya_dead_letter_at='2026-10-19' WHERE id=735")
    c.execute("UPDATE voice_memo_ingest SET updated_at='2026-10-19' WHERE recording_pk=112")
    c.commit()
    assert acknowledged_counts('apple_effects') == {'acknowledged_quarantined_count': 0}
    assert acknowledged_counts('maya') == {'acknowledged_dead_letter_count': 0}
    assert acknowledged_counts('voice_memos')['acknowledged_historical_failure_count'] == 0
    assert c.execute('SELECT count(*) FROM apple_effects').fetchone()[0] == 2
    # An accepted set cannot be silently advanced on a repeat invocation.
    with pytest.raises(FileExistsError):
        acknowledge()
    c.close()


def test_corrupt_acknowledgement_fails_closed(tmp_path, monkeypatch):
    from health_history import acknowledge, acknowledged_counts
    ledger(tmp_path, monkeypatch).close()
    path = acknowledge()
    payload = json.loads(path.read_text())
    assert payload['schema'] == 'penny.health-history/v1'
    assert 'timeout_uncertain' not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    path.write_text('{}')
    with pytest.raises(ValueError):
        acknowledged_counts('maya')
