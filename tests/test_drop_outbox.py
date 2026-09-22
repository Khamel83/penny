import hashlib
import json
import sqlite3

import pytest
import transcript_log as ledger


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, 'TRANSCRIPT_DB_PATH', tmp_path / 'ledger.db')
    monkeypatch.setattr(ledger, '_MIGRATION_SOURCES', [])
    ledger.init_db()
    return ledger._get_conn()


def memo(db, text='Hello 🌍\n<!channel> literal', **extra):
    values = dict(source='iCloud', transcript=text, content_hash=hashlib.sha256(text.encode()).hexdigest(),
                  quality_status='passed', ingest_state='transcribed')
    values.update(extra)
    db.execute('INSERT INTO transcripts (' + ','.join(values) + ') VALUES (' + ','.join('?' for _ in values) + ')', list(values.values()))
    return dict(db.execute('SELECT * FROM transcripts ORDER BY id DESC LIMIT 1').fetchone())


def test_payload_preserves_text_without_private_fields(db):
    row = memo(db, audio_path='/private/audio.m4a')
    assert hasattr(ledger, 'build_drop_payload'), 'Drop payload builder is missing'
    payload = ledger.build_drop_payload(row, 'installation-test', True, False)
    metadata, text = payload.decode().split('\n\n', 1)
    assert text == 'Hello 🌍\n<!channel> literal'
    assert json.loads(metadata)['recorded_at'] is None
    assert json.loads(metadata)['historical'] is True
    assert b'/private' not in payload


def test_repeated_queue_is_frozen_and_rollback_atomic(db):
    assert hasattr(ledger, 'queue_drop_delivery'), 'Drop outbox is missing'
    row = memo(db)
    payload = ledger.build_drop_payload(row, 'installation-test', True, False)
    ledger.queue_drop_delivery(db, row['id'], payload)
    ledger.queue_drop_delivery(db, row['id'], payload)
    assert db.execute('SELECT count(*) FROM drop_deliveries').fetchone()[0] == 1
    db.rollback()
    assert db.execute('SELECT count(*) FROM drop_deliveries').fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM transcripts').fetchone()[0] == 0


def test_expired_send_is_uncertain_and_stale_claim_cannot_finish(db):
    assert hasattr(ledger, 'claim_drop_delivery'), 'Drop claim support is missing'
    row = memo(db)
    ledger.queue_drop_delivery(db, row['id'], ledger.build_drop_payload(row, 'installation-test', False, True))
    db.commit()
    claim = ledger.claim_drop_delivery(now=100, lease_seconds=60)
    assert claim['status'] == 'sending'
    assert ledger.claim_drop_delivery(now=161) is None
    assert db.execute('SELECT status FROM drop_deliveries').fetchone()[0] == 'uncertain'
    assert not ledger.finish_drop_delivery(claim, 'accepted', now=162)


def test_queue_rejects_placeholder_and_nonmemo(db):
    assert hasattr(ledger, 'build_drop_payload'), 'Drop payload builder is missing'
    for row in [dict(source='Google Tasks', transcript='words'),
                dict(source='iCloud', transcript='(migrated — original transcript not preserved)'),
                dict(source='iCloud', transcript='', quality_status='passed')]:
        with pytest.raises(ValueError):
            ledger.build_drop_payload(row, 'installation-test', True, False)


def test_writer_connection_has_full_durability(db):
    assert db.execute('PRAGMA synchronous').fetchone()[0] == 2
    assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1


def test_cutover_atomically_changes_only_new_voice_memo_owner(db):
    assert hasattr(ledger, 'set_drop_cutover'), 'Persistent delivery ownership is missing'
    old = memo(db, text='old memo')
    db.commit()
    ledger.set_drop_cutover(db)
    db.commit()
    row_id = ledger._insert_transcript_transaction(content_hash='new', source='iCloud',
        transcript='new memo', quality_status='passed', ingest_state='transcribed',
        recorded_at='2026-09-22T00:00:00Z', maya_delivery_eligible=True)
    assert row_id
    assert db.execute('SELECT count(*) FROM drop_deliveries').fetchone()[0] == 1
    assert db.execute('SELECT count(*) FROM slack_deliveries WHERE transcript_row_id=?',(row_id,)).fetchone()[0] == 0
    assert db.execute('SELECT maya_delivery_eligible FROM transcripts WHERE id=?',(row_id,)).fetchone()[0] == 0
    ledger.queue_slack_delivery(old['id'])
    assert db.execute('SELECT count(*) FROM slack_deliveries WHERE transcript_row_id=?',(old['id'],)).fetchone()[0] == 1


def test_disabled_policy_keeps_existing_delivery(db):
    row_id = ledger._insert_transcript_transaction(content_hash='before', source='iCloud',
        transcript='new memo', quality_status='passed', ingest_state='transcribed')
    assert db.execute('SELECT count(*) FROM drop_deliveries').fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM slack_deliveries WHERE transcript_row_id=?',(row_id,)).fetchone()[0] == 1


def test_local_only_insertion_does_not_export_after_cutover(db):
    assert hasattr(ledger, 'set_drop_cutover'), 'Persistent delivery ownership is missing'
    ledger.set_drop_cutover(db)
    db.commit()
    ledger._insert_transcript_transaction(content_hash='local', source='iCloud',
        transcript='historical words', quality_status='passed', ingest_state='transcribed',
        routing_suppressed=True, routing_suppression_reason='historical_local_only',
        enqueue_slack=False)
    assert db.execute('SELECT count(*) FROM drop_deliveries').fetchone()[0] == 0


def test_needs_review_after_cutover_has_only_drop_notification(db):
    ledger.set_drop_cutover(db)
    db.commit()
    row_id = ledger._insert_transcript_transaction(content_hash='review', source='iCloud',
        transcript='possibly inaccurate words', quality_status='needs_review', ingest_state='needs_review', quality_detail='repetition')
    assert db.execute('SELECT count(*) FROM drop_deliveries').fetchone()[0] == 1
    assert db.execute('SELECT count(*) FROM quality_failure_slack_deliveries WHERE transcript_row_id=?',(row_id,)).fetchone()[0] == 0
