import importlib
import importlib.util
import hashlib
import json
import uuid

import pytest
import transcript_log as ledger
from test_drop_outbox import db, memo


def test_runtime_configuration_defaults_disabled(monkeypatch):
    import config
    assert hasattr(config, 'DropConfig'), 'Drop runtime configuration is missing'
    cfg = config.DropConfig()
    assert cfg.enabled is False
    assert cfg.ingest_token == ''


def test_health_is_unready_for_uncertain_handoff(db):
    import doctor
    from types import SimpleNamespace
    assert hasattr(doctor, '_default_probe_drop'), 'Drop health probe is missing'
    row = memo(db)
    ledger.queue_drop_delivery(db, row['id'], ledger.build_drop_payload(row, 'installation-test', False, True))
    db.execute("UPDATE drop_deliveries SET status='uncertain'")
    db.commit()
    result = doctor._default_probe_drop(SimpleNamespace(drop=SimpleNamespace(enabled=True,ingest_token='test')))
    assert result['state'] == 'unready'
    assert result['uncertain_count'] == 1
    assert 'Hello' not in json.dumps(result)


def adapter():
    assert importlib.util.find_spec('drop_delivery'), 'Drop HTTP adapter is missing'
    return importlib.import_module('drop_delivery')


def receipt(payload, **kw):
    result = dict(ok=True, status='stored', queue_state='reconcile_pending', retryable=True,
                  drop_id=str(uuid.uuid4()), sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload))
    result.update(kw)
    return result


def test_stored_reconcile_pending_is_accepted():
    mod = adapter()
    assert mod.validate_receipt(receipt(b'text'), b'text')
    assert not mod.validate_receipt(receipt(b'text', sha256='0'*64), b'text')
    assert not mod.validate_receipt(receipt(b'text', size_bytes=9), b'text')
    assert not mod.validate_receipt(receipt(b'text', drop_id='bad'), b'text')


@pytest.mark.parametrize('response,expected', [
    ({'ok': False, 'status':'rejected', 'reason':'unauthorized','retryable':False}, 'failed'),
    ({'ok': False, 'status':'not_stored', 'reason':'body_unreadable','retryable':True}, 'pending'),
    ({'ok': True, 'status':'stored'}, 'uncertain'),
    (TimeoutError(), 'uncertain'),
])
def test_receipts_drive_durable_state(db, response, expected):
    mod = adapter()
    row = memo(db)
    ledger.queue_drop_delivery(db, row['id'], ledger.build_drop_payload(row, 'installation-test', False, True))
    db.commit()
    def send(*args):
        if isinstance(response, Exception): raise response
        return response
    mod.process_pending_drop_deliveries(token='test', send=send)
    got = db.execute('SELECT status,next_attempt_at FROM drop_deliveries').fetchone()
    assert got['status'] == expected
    if expected == 'pending': assert got['next_attempt_at'] > 0
    assert db.execute('SELECT count(*) FROM transcripts').fetchone()[0] == 1


def test_valid_receipt_is_never_resubmitted(db):
    mod = adapter()
    row = memo(db)
    ledger.queue_drop_delivery(db, row['id'], ledger.build_drop_payload(row, 'installation-test', False, True))
    db.commit()
    delivered = []
    def send(payload, headers, token):
        delivered.append(payload)
        assert headers['X-Drop-Client'] == 'penny'
        assert headers['X-Drop-Hints'].isascii()
        return receipt(payload)
    assert mod.process_pending_drop_deliveries(token='test', send=send) == 1
    assert mod.process_pending_drop_deliveries(token='test', send=send) == 0
    assert len(delivered) == 1


def test_missing_token_never_claims(db):
    mod = adapter()
    row = memo(db)
    ledger.queue_drop_delivery(db, row['id'], ledger.build_drop_payload(row, 'installation-test', False, True))
    db.commit()
    assert mod.process_pending_drop_deliveries(token='') == 0
    assert db.execute('SELECT attempt_count FROM drop_deliveries').fetchone()[0] == 0


def test_rate_limit_is_durable_and_honors_long_delay(db):
    from urllib.error import HTTPError
    import time
    mod = adapter()
    row = memo(db)
    ledger.queue_drop_delivery(db, row['id'], ledger.build_drop_payload(row, 'installation-test', False, True))
    db.commit()
    def send(*args):
        raise HTTPError('https://drop.khamel.com/ingest/drop',429,'limited',{'Retry-After':'7200'},None)
    mod.process_pending_drop_deliveries(token='test',send=send)
    row = db.execute('SELECT status,next_attempt_at FROM drop_deliveries').fetchone()
    assert row['status'] == 'pending'
    assert row['next_attempt_at'] >= time.time()+7195


def test_reconcile_requires_one_exact_archived_payload(db):
    mod = adapter()
    row = memo(db)
    payload = ledger.build_drop_payload(row, 'installation-test', False, True)
    ledger.queue_drop_delivery(db, row['id'], payload)
    db.commit()
    claim = dict(db.execute('SELECT * FROM drop_deliveries').fetchone())
    item = dict(drop_id=str(uuid.uuid4()),sha256=hashlib.sha256(payload).hexdigest(),client='penny')
    class Client:
        def items(self, after): return dict(items=[item],has_more=False,next_after=1)
        def content(self, drop_id): return payload
    assert mod.reconcile_drop_delivery(claim, Client())['drop_id'] == item['drop_id']
    class Duplicate(Client):
        def items(self, after): return dict(items=[item,item],has_more=False,next_after=2)
    with pytest.raises(ValueError, match='duplicate'):
        mod.reconcile_drop_delivery(claim, Duplicate())
