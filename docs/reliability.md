# Penny reliability contract

This document defines what Penny can prove. A running process, a launchd
template, a log line, or an HTTP response is not proof of durable storage or a
downstream effect.

## Evidence layers

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
Apple storage API. It distinguishes no-new-memo, source query failure, denied
container access, malformed metadata, and incomplete audio. Discovery and
completion watermarks are separate. A source watermark never advances merely
because a capture was observed; completion advances only after canonical storage
and the configured processing handoff succeed.

An audio file is copied into Penny-owned local staging, checked for a stable
size/signature, and hashed. A source that changes during copying is retried;
partial materialization is quarantined. Retryable failures use bounded backoff
and a terminal attempt/age limit. Terminal rows remain visible as quarantine or
dead-letter state and require an operator decision.

## Archive and iCloud mirror

Each canonical row eventually has one immutable local object and a complete
`Penny Archive` mirror trio:

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

## Doctor and service objectives

The Doctor is read-only and metadata-only. It probes SQLite, Voice Memos source
watermarks/retries, archive counters, local model/offline state, Apple receipts,
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
only. Secrets are dedicated per boundary and runtime-only. No operational log,
Doctor report, test, or deployment artifact may contain transcript bodies,
audio bytes, credentials, provider URLs, or raw exception text.

## Recovery principles

Preserve evidence. Fix configuration, permissions, or a bounded retry state;
use a scratch restore for backup validation; disable a failed new adapter and
resume the known-good Voice Memos + MLX route. Never delete or replace Apple's
Voice Memos database, Penny's SQLite database, archive objects, outboxes, or
backup sets as a shortcut. Do not replay or send an external action from a
health check.
