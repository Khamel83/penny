# Penny handoff

This is the assistant-facing operating contract for Penny Phase A. It describes
the repository contract, not a claim that a particular Mac is currently
deployed. Confirm the exact source revision and runtime state before reporting
readiness.

## System shape

The durable path is:

```text
Apple capture -> local staging -> SQLite receipt -> offline MLX -> local routing
             -> Maya reasoning/policy -> Hermes -> provider receipts
```

Voice Memos is the Phase A compatibility source. Its private database is read
only and unsupported as a storage API; a manual Share/Finder export remains the
fallback. JPR is a Phase B pilot and must not be treated as active until its
capture matrix passes.

Penny's local SQLite database is canonical. Audio-bearing rows may have
immutable local archive objects and a same-basename `.md` transcript plus `.json`
manifest. Text-only, Maya, and Tasks rows may instead be `not_applicable` with
`no_raw_audio`. The iCloud Drive `Penny Archive` folder mirrors complete trios
only. A versioned homelab backup is independent of iCloud and is verified in a
scratch directory.
Apple Notes and Reminders are projections with durable effect keys and
read-after-write receipts.

The routing boundaries are deliberately separate: **local routing** is the
fallback and user-facing Apple projection; **independent Slack** delivery is a
durable outbox; **independent Maya v2** delivery is a separately acknowledged
outbox with bounded retries and `dead_letter` state. A receipt in one boundary is
not evidence of success in another.

## Doctor contract

`venv/bin/python scripts/penny_doctor.py` is the readiness entry point. It probes
SQLite integrity/foreign keys/schema, discovery cursor and retry state, archive
metadata, offline model verification, Apple-effect receipts, Slack/Maya
outboxes, backup verification receipt, launchd/health freshness, and ingress
configuration. It never reads transcript or audio bodies, contacts a provider,
reads TCC databases, repairs state, or prints raw paths, URLs, secrets, errors,
or process identifiers.

- exit `0`: all required components ready
- exit `1`: degraded (including an explicitly disabled optional Maya route)
- exit `2`: unready or unknown required state
- `/health`: liveness only, `200`
- `/ready`: `200` for ready/degraded, `503` for unready

The source revision is meaningful only when it is bound to the checked-out or
deployed runtime revision. A template, generated status line, or process presence is
not deployment proof.

## Durable state and retry rules

An ingest is acknowledged only after a typed persistence result is `inserted` or
`duplicate`. Voice Memos discovery advances the SQLite
`source_watermarks.last_discovered_id` cursor only after a durable
`voice_memo_ingest` upsert. Processing failures remain in that table with
retryable/backoff state or `failed_terminal`; there is no separate completion
watermark. Incomplete or changing audio remains `awaiting_file`/retryable until
the source is fully materialized; a terminal source row remains `failed_terminal`.
Retryable work uses bounded exponential backoff. Archive and Apple-effect
failures use quarantine; Maya terminal delivery uses `dead_letter`.

Apple effects persist a deterministic key before attempting the side effect and
record provider identifiers plus a read-back receipt. An ambiguous timeout is
reconciled before another attempt. Slack and Maya delivery state is monotonic;
late failures cannot reopen a sent row.

## Operator evidence

For one capture, collect metadata in this order:

1. canonical SQLite row and source receipt;
2. archive trio and manifest/hash status;
3. local Notes/Reminders receipt, if applicable;
4. independent Slack outbox acknowledgement;
5. independent Maya v2 acknowledgement or bounded failure;
6. most recent verified backup set and catalog binding.

Use the launchd-owned `watcher.system.log` only as diagnostic context. Log text,
process presence, and a successful HTTP request do not replace a durable receipt.
Do not tail logs as a health check and do not paste transcript content into an
incident report.

## Safe recovery posture

Recovery is additive and evidence-preserving:

- run Doctor and inspect bounded reason codes;
- preserve staged objects, SQLite rows, outboxes, receipts, and dead letters;
- repair configuration or permissions through the normal macOS/operator path;
- use a verified backup only in a scratch restore first;
- stop writers before a planned restore, then re-run read-only integrity,
  archive, and backup checks before resuming;
- disable a failed new adapter and return to the known-good Voice Memos + MLX
  path while preserving all evidence.

Never delete or replace Apple's Voice Memos database, Penny's SQLite database,
archive objects, outboxes, or backup sets as a troubleshooting shortcut. Never
replay, send, share, purchase, deploy, or change credentials from a health check.

## Transitional gaps

Tracked/runtime webhook templates must converge to loopback or an explicitly
protected non-loopback bind; Doctor treats an unprotected bind as unready.
The callback uses `PENNY_WEBHOOK_SECRET`; Hermes uses the dedicated
`PENNY_HERMES_WEBHOOK_SECRET`. Selected provider/task/webhook logs use bounded
fields and redacted exception classes; this does not retroactively clean every
historical log artifact.

## Future gates

Phase B requires JPR installation and permission approval, at least 20 synthetic
captures, five physical Watch canaries, zero loss/duplicates, and complete
source-to-receipt traces. Maya must replace the transitional direct OpenRouter
classification path before that dependency is removed. macOS 27, Apple Speech,
EventKit, and MacWhisper remain shadow/challenger work until their separate gates
pass.

## Canonical references

- [README](README.md)
- [Reliability](docs/reliability.md)
- [Mac mini deployment](docs/macmini-deployment.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Approved design](docs/superpowers/specs/2026-08-09-penny-august-2026-design.md)
- [Phase A plan](docs/superpowers/plans/2026-08-09-penny-phase-a-hardening.md)
