# Penny reliability contract

This document defines what Penny can prove. A running process, a launchd
template, a log line, or an HTTP response is not proof of durable storage or a
downstream effect.

## Evidence layers

For captures assigned to Drop by the persistent cutover, the Penny Drop outbox
replaces new direct Slack/Maya intents. A validated stored intake receipt proves
durable edge staging, not archival or downstream delivery. Historical export is
an explicit text-only operation and suppresses Slack notifications. See
[Drop delivery](drop-delivery.md). Existing independent delivery receipts below
remain authoritative for pre-cutover captures.

For every capture, keep these layers independent:

1. source receipt and immutable local staging;
2. canonical SQLite persistence;
3. local MLX transcription and quality outcome;
4. local Notes/Reminders effect receipt;
5. independent Slack outbox receipt;
6. independent Maya v2 outbox receipt;
7. archive trio publication and backup verification.

Penny acknowledges an upload only after typed persistence returns `inserted` or
`duplicate`. `failed` is not an acknowledgement. All state transitions are
additive and retry-safe.

## Capture and Voice Memos retry

The Voice Memos reader is a read-only compatibility adapter, not a supported
Apple storage API. The Doctor does not inspect Apple's live source, TCC state,
container permission, or source schema. Those conditions remain watcher
diagnostics/manual Apple recovery, and an unobserved condition stays unknown.
The SQLite `source_watermarks.last_discovered_id` cursor advances only after a
durable `voice_memo_ingest` upsert. Processing failures remain in
`voice_memo_ingest` with retryable/backoff state or `failed_terminal`; there is
no separate completion watermark.

An audio file is copied into Penny-owned local staging, checked for a stable
size/signature, and hashed. A source that changes during copying is retried;
partial materialization remains `awaiting_file`/retryable, and a terminal source
row is `failed_terminal`. Temporary archive material is removed after a failed
copy. Archive publication failures remain pending through bounded retries and
then become visibly `failed`; migration/orphan rows and invalid published-mirror
material use recoverable quarantine. Terminal or conflicting Apple-effect
failures use quarantine, ordinary failures remain `failed`, and ambiguous
timeouts remain `uncertain`. Maya terminal delivery uses `dead_letter`.
Retryable failures use bounded backoff and a terminal attempt/age limit.

An operator may classify an old missing-file failure as `unavailable` with
`scripts/reconcile_absent_voice_memos.py --apply` after reviewing its default
dry run. The command requires a successful complete Apple inventory, absence
of that source row, and absence of its known audio paths. It never changes a
present source or a processing failure. The prior error, attempt count and
terminal timestamp remain in the ledger. Doctor reports these historical
absences as degraded with an explicit count; current capture failures remain
unready.

Apple source-to-audio lookup requires its exact bounded `ZPATH`. A matching
label or date prefix is not recording identity and must never substitute
another memo's audio. Pathless source rows stay indexed as missing audio;
standalone files can still be captured by the separate safe disk scan.

## Archive and iCloud mirror

Each audio-bearing canonical row may have one immutable local object and a
complete `Penny Archive` mirror trio. Text-only, Maya, and Tasks rows may be
`not_applicable` with `no_raw_audio` and do not receive an audio-bearing trio:

```text
<utc>__p<id>__<source>__<sha12>.<original-extension>
<utc>__p<id>__<source>__<sha12>.md
<utc>__p<id>__<source>__<sha12>.json
```

The audio retains its original bytes and extension. Markdown contains the
canonical transcript and compact provenance; JSON contains schema, identity,
timestamps, sizes, and hashes. Files are written to private temporary siblings
and renamed atomically; the manifest is last. Consumers accept the trio only
when all files exist and every hash matches. The mirror is rebuildable and is
not a database or disaster-recovery source.

## SQLite, effects, and outboxes

SQLite is the canonical operational record. Schema changes are additive and
serialized through `transcript_log.py`. Apple effects persist deterministic keys
before attempting AppleScript, then store provider identifiers and read-back
receipts. Permission failures and uncertain timeouts are explicit states.

Slack delivery is an independent durable outbox. It may be pending, retryable,
sent, or terminally failed without changing local routing or Maya state. Long
messages are deterministically chunked and each acknowledged chunk has durable
state.

Maya v2 delivery is a separate authenticated outbox. Only explicitly eligible,
quality-passed captures enter it. Attempts are capped at 20 and seven days;
leases/claims prevent two workers from sending the same row. A validated,
identity-matching receipt is required for `sent`; uncertain transport remains
reconcilable. Terminal rows are dead letters, not infinite retries.

Historical Voice Memo recovery is a separate local-only operation. The
backfill enumerates all current Apple source rows instead of trusting the
recurring watcher watermark, persists source metadata before processing, and
records an exact bounded report of source rows, ledger rows, unmatched source
ranges, transcript states, archive states, and downstream-effect counts. A
successful backfill batch does not prove that every audio file is available or
that every transcript passed quality review. Missing files remain explicit
retryable or terminal ledger state. The pass uses Penny's offline local
transcription backend; it does not call external/cloud providers or run Slack,
Maya, Apple, Notes, Reminders, Hermes, or GitHub outboxes. Any later external
delivery is a separate operation with a separate receipt.

## Backups and restore

The scheduled backup creates an immutable, versioned set containing a
transactionally consistent SQLite snapshot, fully materialized archive objects,
and a catalog of hashes and metadata. A scratch verifier checks catalog paths,
object hashes, SQLite integrity/schema/row count/max ID, and safe extras. The
latest verification receipt is written atomically with mode `0600` only after
local verification and remote catalog verification both succeed. A failed run
never advances the prior good receipt.

JSON transcript exports are readable aids only. Restore is staging-only: verify
the set and catalog in a scratch directory, stop writers, restore the whole
database, reconcile archive objects by canonical ID and full hashes, and rerun
Doctor before any external effect can resume. Retained sets are not deleted by
iCloud synchronization.

Mirror reconciliation recognizes macOS File Provider eviction markers. It
records validation as deferred without downloading the whole audio file or
quarantining the trio. Deferred validation is not current byte-verification;
the immutable Penny object and verified backup remain the recovery authority.

## Doctor and service objectives

See [capture health](capture-health.md) for the fixed historical-failure reporting
boundary and why an idle Apple sync daemon is diagnostic rather than an outage.
Current failures and stale/unreadable source evidence remain readiness failures.

The Doctor is read-only and metadata-only. It probes SQLite, Penny's Voice Memos
discovery cursor/retry/terminal metadata, archive counters, local model/offline state, Apple receipts,
Slack/Maya health, backup receipt, service freshness, and ingress policy. It
never reads transcript/audio bodies, calls Apple providers, contacts Slack/Maya,
reads TCC databases, or prints paths, URLs, secrets, raw errors, or process identifiers.

- exit `0`: ready;
- exit `1`: degraded; bounded backlog or disabled optional Maya may qualify;
- exit `2`: unready or unknown required state.

`/health` is liveness and always returns `200` when the webhook can answer.
`/ready` returns `200` for ready/degraded and `503` for unready. Health freshness
files and launchd registration are supporting signals, not downstream proof.
The launchd diagnostic file `watcher.system.log` may help explain a failure but
must never be used as the readiness source.

## Security and privacy

Raw audio stays within the approved Apple/Penny storage and backup boundary.
Transcription is local and offline. Only authenticated, policy-mediated Maya or
Hermes paths may receive transcript text; Slack quality receipts are metadata
only. The callback uses `PENNY_WEBHOOK_SECRET`; Hermes uses the dedicated
`PENNY_HERMES_WEBHOOK_SECRET`. Selected provider, Google Tasks, and webhook runtime logs use bounded
fields and redacted exception classes; this does not retroactively clean every
historical log artifact. Doctor output, tests, and deployment evidence remain
metadata-only.

## Recovery principles

Preserve evidence. Fix configuration, permissions, or a bounded retry state;
use a scratch restore for backup validation; disable a failed new adapter and
resume the known-good Voice Memos + MLX route. Never delete or replace Apple's
Voice Memos database, Penny's SQLite database, archive objects, outboxes, or
backup sets as a shortcut. Do not replay or send an external action from a
health check.
