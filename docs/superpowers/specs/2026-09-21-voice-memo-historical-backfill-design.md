# Voice Memo Historical Backfill Design

## Purpose

Recover the historical Apple Voice Memos records that Penny never indexed,
retain every source record in the canonical local SQLite ledger, and
transcribe every safely available audio file through the existing offline
pipeline. The first pass is local-only: it may create Penny-owned local
archive receipts, but it must not create or send Slack, Maya, Notes, Reminders,
Hermes, or GitHub effects.

The current live source evidence is:

- Apple `ZCLOUDRECORDING`: 315 records.
- Penny `voice_memo_ingest`: 143 records.
- Current Apple records absent from the Penny ledger: 173.
- Absent records with a regular audio file at the source path: 172.
- Absent records with no usable source path: 1.

The existing discovery cursor is monotonic and must remain so. The backfill
must never lower the cursor, rewrite Apple's database, or infer that a source
record is complete merely because its metadata was indexed.

## Scope and non-goals

In scope:

1. Enumerate all current Apple Voice Memos source rows, independent of the
   incremental `Z_PK > watermark` query.
2. Upsert source metadata before attempting file access or transcription.
3. Safely stage, hash, transcribe, quality-check, and locally archive available
   audio using the existing pipeline.
4. Preserve explicit durable states for missing, changing, malformed,
   oversized, failed, duplicate, and quality-review records.
5. Make the pass resumable and bounded by a command-line batch limit.
6. Report source-to-ledger coverage through a metadata-only backfill report and
   watcher/Doctor health counters.

Out of scope for this pass:

- Lowering or resetting `source_watermarks`.
- Replaying or sending historical Slack, Maya, Notes, Reminders, Hermes, or
  GitHub actions.
- Repairing Apple CloudKit, Voice Memos permissions, or source synchronization.
- Deleting stale Penny rows or source files.
- Claiming that a transcript is semantically correct when the quality policy
  marks it `needs_review`.

## Approaches considered

### Lower the watermark and run the watcher

Rejected. It couples historical recovery to the live incremental cursor,
replays current records, and makes it difficult to distinguish a source
coverage gap from ordinary retry behavior.

### Scan old `.m4a` files only

Rejected. It cannot represent a source row whose path is missing, does not
preserve Apple source metadata before processing, and cannot prove that every
source record was considered.

### Dedicated source-enumeration backfill using existing processing primitives

Recommended. It keeps Apple read-only, reuses the established safe-path,
staging, hashing, transcription, archive, and ledger functions, and adds only
the durable policy and coverage seams needed for a historical pass.

## Design

### Source enumeration and checkpointing

Add a read-only source query that returns all `ZCLOUDRECORDING` rows ordered by
`Z_PK`. The backfill command processes ascending primary keys in bounded
batches. Each invocation may enumerate the source again; completed ledger rows
are idempotently skipped, while unlinked retryable rows remain eligible for
processing.

The normal `voice_memos` watermark remains an incremental-discovery receipt.
The backfill does not move it backward. After a durable metadata upsert, it
may advance the existing watermark monotonically to the highest enumerated
primary key, which is safe because all lower source rows have been durably
represented even if their audio still needs retry.

The command emits metadata-only JSON: counts, bounded states, and numeric
identifiers or ranges when needed for operator reconciliation. It never emits
recording labels, paths, transcript bodies, audio hashes, provider responses,
or secrets.

### Local-only processing policy

Add an explicit `routing_suppressed` transcript field with an additive SQLite
migration. A local-only backfill transcript is inserted with:

- `enqueue_slack=False`;
- `maya_delivery_eligible=False`;
- `routing_suppressed=1` and reason `historical_local_only`;
- no call to `classify_and_route` or any Apple/Hermes/GitHub effect adapter.

The normal pending-route query excludes suppressed rows. This is durable policy
rather than an in-memory flag, so a watcher restart cannot later route the
historical corpus accidentally. Existing canonical duplicates are linked
idempotently without creating a new downstream delivery. Existing delivery
receipts are not deleted or changed.

Quality-review Slack notifications are also disabled for this command. The
quality state remains in SQLite and the local archive receipt remains eligible
for reconciliation. A future, explicit operator action may release selected
rows to normal routing; that release is not part of this change.

### Source and audio outcomes

For every source row, metadata is persisted before processing. Available audio
uses the existing no-symlink, in-root, stable-copy path and existing content
hash deduplication. A missing or empty path remains visible as an explicit
waiting/failed state. A transcription or persistence error uses the existing
bounded retry and terminal-state rules. A duplicate content hash links the
source row to the existing canonical transcript without creating a second
transcript body.

The backfill reports these boundaries separately:

1. source rows enumerated;
2. source rows represented in `voice_memo_ingest`;
3. audio files safely staged;
4. canonical transcript rows linked;
5. quality-passed and quality-review rows;
6. waiting, retryable, terminal, and unavailable rows;
7. local archive receipts and pending archive work.

### Coverage health

Extend the watcher health receipt with metadata-only source coverage counters
for current source-record count, ledger-record count, and the unindexed gap.
Doctor reads those exact receipt fields. A source coverage gap is reported as a
coverage reason, independently from source daemon responsiveness,
transcription readiness, archive state, and downstream provider receipts.

The command's exact unmatched-primary-key report is the authoritative
operator-facing reconciliation for a backfill run; the recurring health file
is a bounded freshness/counter signal, not proof that CloudKit has no future
records.

## Files and interfaces

- `transcript_log.py`
  - add the additive `routing_suppressed` and reason columns;
  - exclude suppressed rows from `get_pending`;
  - expose metadata-only voice-memo coverage counts.
- `watcher.py`
  - add all-source enumeration;
  - thread local-only processing through audio/transcript persistence;
  - extend the health receipt with coverage counters;
  - retain the normal incremental watcher behavior by default.
- `scripts/backfill_voice_memos.py`
  - provide a bounded, resumable local-only operator command;
  - initialize the canonical database, enumerate source rows, process the
    selected batch, and print metadata-only JSON.
- `doctor.py`
  - read and expose the new coverage fields without reading Apple or transcript
    bodies.
- `tests/test_transcript_log.py`, `tests/test_watcher.py`,
  `tests/test_doctor.py`, and a focused backfill test module
  - pin migration, suppression, all-source enumeration, idempotent reruns,
    missing-file visibility, coverage receipt, and metadata-only output.
- `README.md`, `docs/reliability.md`, and the operator troubleshooting docs
  - document the command, local-only boundary, resumability, and completion
    evidence.

## Acceptance criteria

1. A test source database containing records below the live watermark is fully
   enumerated and represented without changing the watermark backward.
2. A rerun creates no duplicate transcript rows and no Slack, Maya, Apple,
   Hermes, or GitHub delivery rows for local-only records.
3. A missing-path source record remains visible with an explicit retryable or
   terminal state.
4. A transcript produced by the backfill is linked to its source row, has a
   local archive receipt queued or published, and is excluded from normal
   routing until explicitly released.
5. Health and Doctor expose source/ledger coverage counters without private
   content or paths.
6. The full repository test suite, trust check, `git diff --check`, and a live
   metadata-only backfill report pass before the change is merged or deployed.
7. No historical downstream delivery occurs as part of implementation or
   verification.
