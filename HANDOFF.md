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

Penny's local SQLite database is canonical. Immutable local archive objects hold
original audio and a same-basename `.md` transcript plus `.json` manifest. The
iCloud Drive `Penny Archive` folder mirrors complete trios only. A versioned
homelab backup is independent of iCloud and is verified in a scratch directory.
Apple Notes and Reminders are projections with durable effect keys and
read-after-write receipts.

The routing boundaries are deliberately separate: **local routing** is the
fallback and user-facing Apple projection; **independent Slack** delivery is a
durable outbox; **independent Maya v2** delivery is a separately acknowledged
outbox with bounded retries and dead-letter state. A receipt in one boundary is
not evidence of success in another.

## Doctor contract

`venv/bin/python scripts/penny_doctor.py` is the readiness entry point. It probes
SQLite integrity/foreign keys/schema, source watermark and retry state, archive
metadata, offline model verification, Apple-effect receipts, Slack/Maya
outboxes, backup verification receipt, launchd/health freshness, and ingress
configuration. It never reads transcript or audio bodies, contacts a provider,
reads TCC databases, repairs state, or prints raw paths, URLs, secrets, errors,
or PIDs.

- exit `0`: all required components ready
- exit `1`: degraded (including an explicitly disabled optional Maya route)
- exit `2`: unready or unknown required state
- `/health`: liveness only, `200`
- `/ready`: `200` for ready/degraded, `503` for unready

The source revision is meaningful only when it is bound to the checked-out or
deployed runtime revision. A template, generated status line, or process PID is
not deployment proof.

## Durable state and retry rules

An ingest is acknowledged only after a typed persistence result is `inserted` or
`duplicate`. A database failure is retryable and never routes or advances the
Voice Memos completion watermark. Incomplete audio is quarantined until the
source is fully materialized. Retryable work uses bounded exponential backoff;
terminal work is visible as quarantine or dead-letter state.

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

Never delete or reset Apple's Voice Memos database, Penny's SQLite database,
archive objects, outboxes, or backup sets as a troubleshooting shortcut. Never
replay, send, share, purchase, deploy, or change credentials from a health check.

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
