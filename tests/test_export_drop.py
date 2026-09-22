import importlib
import importlib.util
import json
import pytest
import transcript_log as ledger
from test_drop_outbox import db, memo


def exporter():
    assert importlib.util.find_spec('scripts.export_drop'), 'Historical Drop exporter missing'
    return importlib.import_module('scripts.export_drop').export_drop


def test_export_is_dry_run_and_then_idempotent_quiet(db):
    run = exporter()
    memo(db)
    db.commit()
    assert run()['eligible'] == 1
    assert db.execute('SELECT count(*) FROM drop_deliveries').fetchone()[0] == 0
    assert run(dry_run=False)['queued'] == 1
    payload = db.execute('SELECT payload FROM drop_deliveries').fetchone()[0]
    metadata = json.loads(payload.split(b'\n\n',1)[0])
    assert metadata['historical'] is True
    assert metadata['notify_slack'] is False
    assert run(dry_run=False)['queued'] == 0


def test_export_retains_review_flags_and_excludes_placeholder(db):
    run = exporter()
    memo(db, text='uncertain words', quality_status='needs_review')
    memo(db, text='(migrated — original transcript not preserved)', quality_detail='migrated_placeholder')
    memo(db, text='a task', source='Google Tasks')
    db.commit()
    assert run(dry_run=False)['queued'] == 1
    payload = db.execute('SELECT payload FROM drop_deliveries').fetchone()[0]
    assert json.loads(payload.split(b'\n\n',1)[0])['quality_status'] == 'needs_review'


def test_export_never_relabels_new_live_delivery(db):
    run = exporter()
    ledger.set_drop_cutover(db)
    db.commit()
    ledger._insert_transcript_transaction(content_hash='live',source='iCloud',transcript='live memo',quality_status='passed')
    assert run(dry_run=False)['queued'] == 0
    payload = db.execute('SELECT payload FROM drop_deliveries').fetchone()[0]
    assert json.loads(payload.split(b'\n\n',1)[0])['historical'] is False
