# Task 4: Voice Memo discovery retry

## Source-state design

`source_watermarks` is the discovery authority.  The `voice_memos` row stores
the largest durably registered `Z_PK`; it only advances after every earlier
row in the current batch upserted and committed.  The historic
`~/.penny/last_pk.txt` is seeded into SQLite once when that SQLite row is
absent, then is atomically replaced only as a compatibility mirror after a
successful SQLite advance.

`voice_memo_ingest` is the processing authority.  Unlinked failures carry a
bounded attempt count, safe error code, timestamp, and due time.  A retry
refreshes the current CloudRecordings row by primary key before processing.
Linked review/oversize rows and routed rows are terminal and cannot re-enter
transcription.  A processing failure never prevents discovery of later
durably registered rows, but an upsert failure stops the batch before it can
move past that source gap.

## TDD evidence

RED, before implementation:

```text
7 failed, 83 passed, 8 subtests passed
```

The failures were the missing watermark/retry interfaces and watcher retry
hook.  GREEN after implementation and edge-case coverage:

```text
93 passed, 8 subtests passed in 0.97s
```

Command:

```text
PENNY_INGEST_TOKEN=ingest-test-token /Users/macmini/penny/venv/bin/python -m pytest tests/test_transcript_log.py tests/test_watcher.py tests/test_sqlite_leak.py -q
```

`git diff --check` also passed.
