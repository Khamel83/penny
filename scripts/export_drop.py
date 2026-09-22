#!/usr/bin/env python3
"""Explicit quiet historical export. Default is read-only inventory."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import transcript_log as ledger


def export_drop(dry_run=True, limit=50):
    if limit < 1:
        raise ValueError('positive_limit_required')
    conn = sqlite3.connect(f'file:{ledger.TRANSCRIPT_DB_PATH}?mode=ro',uri=True) if dry_run else ledger._get_conn()
    conn.row_factory = sqlite3.Row
    try:
        if not dry_run:
            conn.execute('BEGIN IMMEDIATE')
        producer = conn.execute('SELECT producer_id FROM drop_policy WHERE singleton=1').fetchone()[0]
        report = dict(eligible=0,queued=0,already_queued=0,excluded=0,live_owned=0)
        for row in conn.execute("SELECT * FROM transcripts WHERE source='iCloud' ORDER BY id").fetchall():
            if ledger._drop_owns(conn,row['id']):
                report['live_owned'] += 1
                continue
            try:
                payload = ledger.build_drop_payload(row,producer,True,False)
            except ValueError:
                report['excluded'] += 1
                continue
            report['eligible'] += 1
            meta = json.loads(payload.split(b'\n\n',1)[0])
            identity = 'penny:{producer_id}:{transcript_id}:{transcript_sha256}'.format(**meta)
            if conn.execute('SELECT 1 FROM drop_deliveries WHERE identity=?',(identity,)).fetchone():
                report['already_queued'] += 1
                continue
            if not dry_run and report['queued'] < limit:
                ledger.queue_drop_delivery(conn,row['id'],payload)
                report['queued'] += 1
        if not dry_run:
            conn.commit()
        return report
    finally:
        conn.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply',action='store_true')
    p.add_argument('--limit',type=int,default=50)
    p.add_argument('--activate',action='store_true',help='Assign future voice memos to Drop; requires --apply')
    p.add_argument('--drain',action='store_true',help='Send queued records; requires --apply and runtime token')
    p.add_argument('--reconcile',action='store_true',help='Reconcile uncertain records; requires --apply')
    args = p.parse_args()
    if (args.activate or args.drain or args.reconcile) and not args.apply:
        p.error('operation requires --apply')
    if args.activate:
        conn=ledger._get_conn()
        try:
            result=ledger.set_drop_cutover(conn)
            conn.commit()
            print(json.dumps({'enabled':True,'cutoff_id':result['cutoff_id']}))
        finally: conn.close()
    elif args.drain:
        import os
        from drop_delivery import process_pending_drop_deliveries
        token=os.environ.get('PENNY_DROP_TOKEN','')
        if not token: raise RuntimeError('drop_token_missing')
        print(json.dumps({'accepted':process_pending_drop_deliveries(args.limit,token=token)}))
    elif args.reconcile:
        from drop_delivery import reconcile_pending_drop
        print(json.dumps({'reconciled':reconcile_pending_drop(args.limit)}))
    else:
        print(json.dumps(export_drop(not args.apply,args.limit)))


if __name__=='__main__':
    try: main()
    except Exception as exc:
        print(json.dumps({'error':type(exc).__name__}),file=sys.stderr)
        sys.exit(1)
