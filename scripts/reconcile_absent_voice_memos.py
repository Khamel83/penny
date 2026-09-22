#!/usr/bin/env python3
"""Classify proven absent historical sources, preserving terminal failure metadata."""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import logging
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import transcript_log
import watcher


def reconcile(*, apply=False):
    # Strict enumeration must succeed; a permissions/query failure is not absence.
    present = {int(row['Z_PK']) for row in watcher.get_all_recordings()}
    roots = watcher._voice_memo_roots()
    if roots is None:
        raise RuntimeError('audio_source_unavailable')
    with closing(transcript_log._get_conn()) as conn:
        candidates = [dict(row) for row in conn.execute(
            "SELECT recording_pk, raw_path, audio_path, label FROM voice_memo_ingest "
            "WHERE status = 'failed_terminal' AND transcript_row_id IS NULL "
            "AND error_message = 'file_not_downloaded'"
        )]
    absent = []
    for row in candidates:
        pk = int(row['recording_pk'])
        if pk in present:
            continue
        raw = Path(str(row['raw_path'] or ''))
        if not row['raw_path'] or raw.is_absolute() or '..' in raw.parts:
            continue
        known = [roots[0] / raw]
        if row['audio_path']:
            known.append(Path(row['audio_path']))
        any_present = False
        for candidate in known:
            try:
                candidate.lstat()
                any_present = True
            except FileNotFoundError:
                pass
            # Other I/O errors propagate: unreadable is not absent.
        if any_present:
            continue
        if row['label']:
            # Enumerating names is enough to refuse classification. Do not
            # collapse unsafe/broken/unreadable aliases into missing audio.
            with os.scandir(roots[0]) as entries:
                if any(entry.name.endswith('.m4a') and
                       watcher._recording_alias_matches(entry.name, str(row['label']))
                       for entry in entries):
                    continue
        absent.append(pk)
    changed = sum(transcript_log.mark_voice_memo_source_absent(pk) for pk in absent) if apply else 0
    return {'source_records': len(present), 'absent_recording_pks': absent,
            'classified_count': changed, 'applied': apply}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        print(json.dumps(reconcile(apply=args.apply), sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({'error_class': type(exc).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
