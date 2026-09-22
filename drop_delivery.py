"""Penny's bounded text handoff. Drop owns everything after stored acceptance."""
from __future__ import annotations

import hashlib
import json
import os
import random
import time
import uuid
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError
from urllib.request import Request, HTTPRedirectHandler, build_opener

import transcript_log as ledger

INTAKE = 'https://drop.khamel.com/ingest/drop'
READ_API = 'http://oci-dev.deer-panga.ts.net:8791'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def submit_payload(payload, headers, token, opener=None):
    opener = opener or build_opener(NoRedirect())
    request = Request(INTAKE, data=payload, method='POST',
                      headers={**headers, 'Authorization': 'Bearer ' + token})
    with opener.open(request, timeout=10) as response:
        return json.loads(response.read(65536))


def validate_receipt(receipt, payload):
    try:
        uuid.UUID(receipt['drop_id'])
        return (receipt['ok'] is True and receipt['status'] == 'stored'
                and receipt['sha256'] == hashlib.sha256(payload).hexdigest()
                and type(receipt['size_bytes']) is int and receipt['size_bytes'] == len(payload))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def payload_headers(payload):
    m = json.loads(payload.split(b'\n\n', 1)[0])
    hints = {key: m[key] for key in ('producer_id', 'transcript_id', 'transcript_sha256',
                                    'historical', 'notify_slack', 'quality_status', 'schema')}
    hints['producer'] = 'penny'
    return {'Content-Type': 'text/plain; charset=utf-8', 'Accept': 'application/json',
            'X-Drop-Kind': 'text', 'X-Drop-Client': 'penny',
            'X-Filename': f"penny-{m['transcript_id']}-{m['transcript_sha256'][:12]}.txt",
            'X-Drop-Hints': json.dumps(hints, ensure_ascii=True, separators=(',', ':'))}


def process_pending_drop_deliveries(limit=1, *, token=None, send=None):
    if token is None:
        from config import get_config
        cfg = get_config().drop
        if not cfg.enabled:
            return 0
        token = cfg.ingest_token
    if not token:
        return 0
    delivered = 0
    send = send or submit_payload
    for _ in range(max(0, min(limit, 50))):
        claim = ledger.claim_drop_delivery()
        if not claim:
            break
        payload = bytes(claim['payload'])
        try:
            response = send(payload, payload_headers(payload), token)
            if validate_receipt(response, payload):
                # Store only bounded receipt fields, never a provider response blob.
                receipt = {key: response.get(key) for key in ('drop_id', 'sha256', 'size_bytes', 'queue_state')}
                delivered += int(ledger.finish_drop_delivery(claim, 'accepted', receipt=receipt))
            elif isinstance(response, dict) and response.get('ok') is False and response.get('status') in {'rejected', 'not_stored'}:
                if response.get('status') == 'not_stored' and response.get('reason') not in {'body_unreadable', 'metadata_failed'}:
                    receipt = None
                    try:
                        receipt = {'drop_id':str(uuid.UUID(response['drop_id']))}
                    except (KeyError,ValueError,TypeError,AttributeError):
                        pass
                    ledger.finish_drop_delivery(claim,'uncertain',receipt=receipt,error_code='storage_uncertain')
                    continue
                retry = response.get('status') == 'not_stored' and response.get('retryable') is True
                retry = retry and claim['attempt_count'] < 20
                delay = min(1800, 30 * 2 ** min(claim['attempt_count'], 6)) + random.uniform(0, 10)
                ledger.finish_drop_delivery(claim, 'pending' if retry else 'failed',
                    next_attempt_at=time.time()+delay, error_code='intake_refused')
            else:
                ledger.finish_drop_delivery(claim, 'uncertain', error_code='receipt_invalid')
        except HTTPError as exc:
            if exc.code == 429:
                value = exc.headers.get('Retry-After', '60')
                try:
                    delay = max(1, int(value))
                except ValueError:
                    try:
                        delay = max(1, parsedate_to_datetime(value).timestamp()-time.time())
                    except (ValueError, TypeError, OverflowError):
                        delay = 60
                ledger.finish_drop_delivery(claim, 'pending', next_attempt_at=time.time()+delay, error_code='rate_limited')
            else:
                ledger.finish_drop_delivery(claim, 'uncertain', error_code='http_uncertain')
        except (OSError, ValueError, TypeError):
            ledger.finish_drop_delivery(claim, 'uncertain', error_code='transport_uncertain')
    return delivered


class DropReader:
    def __init__(self, timeout=10):
        self.opener = build_opener(NoRedirect())
        self.deadline = time.monotonic() + timeout

    def get(self, path):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('reconciliation_budget')
        req = Request(READ_API + path, headers={'X-Drop-Consumer': 'penny-reconcile'})
        with self.opener.open(req, timeout=remaining) as response:
            return response.read(10*1024*1024+1)

    def items(self, after):
        return json.loads(self.get(f'/v1/drops?client=penny&limit=200&after={after}'))

    def content(self, drop_id):
        uuid.UUID(drop_id)
        return self.get(f'/v1/drops/{drop_id}/content')


def reconcile_drop_delivery(claim, client):
    matches, after = [], 0
    while True:
        page = client.items(after)
        for item in page['items']:
            if item.get('client') == 'penny' and item.get('sha256') == claim['payload_sha256']:
                data = client.content(item['drop_id'])
                if data == bytes(claim['payload']):
                    matches.append({key: item.get(key) for key in ('drop_id', 'sha256', 'sequence_id', 'archived_at')})
        if not page['has_more']:
            break
        next_after = page['next_after']
        if next_after <= after:
            raise ValueError('invalid_cursor')
        after = next_after
    if len(matches) > 1:
        raise ValueError('duplicate_archived_identity')
    return matches[0] if matches else None


def reconcile_pending_drop(limit=1):
    """Read-only network reconciliation followed by a guarded local receipt write."""
    conn = ledger._get_conn()
    try:
        rows = conn.execute("SELECT * FROM drop_deliveries WHERE status='uncertain' AND next_attempt_at<=? ORDER BY next_attempt_at,id LIMIT ?", (time.time(),limit)).fetchall()
        count = 0
        for row in rows:
            # Commit scheduling before network work so a timeout cannot monopolize the queue.
            conn.execute("UPDATE drop_deliveries SET next_attempt_at=? WHERE id=? AND status='uncertain'",(time.time()+300,row['id']))
            conn.commit()
            try:
                receipt = reconcile_drop_delivery(dict(row), DropReader())
            except ValueError as exc:
                if str(exc) == 'duplicate_archived_identity':
                    conn.execute("UPDATE drop_deliveries SET status='failed',error_code='duplicate_archived_identity' WHERE id=? AND status='uncertain'",(row['id'],))
                    conn.commit()
                    continue
                raise
            if receipt:
                conn.execute("UPDATE drop_deliveries SET status='accepted', archive_receipt=?, accepted_at=?, error_code=NULL WHERE id=? AND status='uncertain'",
                             (json.dumps(receipt), time.time(), row['id']))
                conn.commit()
                count += 1
        return count
    finally:
        conn.close()
