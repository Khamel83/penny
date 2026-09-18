# Penny handoff

## Active synchronized shared-Whisper cutover — 2026-09-17

This is the Penny side of the Atlas handover plan:
`/Volumes/2TB_SSD/GitHub/atlas/.worktrees/minuspod-reliability-fix/docs/superpowers/plans/2026-09-17-shared-whisper-cutover-handover.md`.

- Source checkout: local `main`.
- Source SHA: `8e53c102065db2ebb9ce7ee7f56c562a4ee63180`.
- Source implementation: `shared_whisper/{protocol,client,server,supervisor,worker}.py`;
  `transcript_quality.py` calls the shared client and no longer owns MLX.
- Full verification: `602 passed, 2 skipped, 50 subtests passed`.
- Runtime completed: plist render/backup, old-owner removal,
  `com.penny.shared-whisper` bootstrap, authenticated MagicDNS verification,
  one-worker/memory checks, and Homelab shared-client deployment.
- Current live owner is `com.penny.shared-whisper` on 10311. The tiny Wyoming
  service remains on 10300/10301 and is outside this change.
- The tracked non-private canary returned HTTP 200 with nonempty validated
  metadata, one segment, and the pinned model identity; transcript text was not
  retained. It left one idle worker within the configured TTL and no second
  large owner.
- One post-cutover Atlas episode completed durably at
  `2026-09-18T03:52:05Z` after six chunks in each transcription pass. The
  post-cutover receipt has zero `Whisper API unreachable` rows and zero generic
  `Failed to transcribe audio` rows. The queue then continued naturally;
  current state is 27 completed, 38 pending, 1 processing, and 9 terminal
  failures.
- Read-only Penny Doctor at 2026-09-18T03:57:15Z reports the shared-Whisper
  component `ready` with `service_ok=true`, `model_verified=true`,
  `old_large_owner_present=false`, `legacy_tiny_present=true`,
  `memory_pressure_ok=true`, and zero loaded workers after the final idle-only
  restart. Overall Doctor remains `unready`
  for independent pre-existing reasons: one Voice Memos terminal failure,
  shell transcription offline mode not set, watcher freshness, one Apple
  quarantine, and Maya dead letters. Those are not attributed to this
  cutover.
- No token, audio, transcript, model file, or private content belongs in this
  handoff. The synchronized Atlas receipt is
  `thoughts/shared/receipts/2026-09-18-shared-whisper-live-cutover.md`.
  Runtime status must be re-read before each claim.

The shared service is designed to keep one killable `large-v3-turbo` worker,
use a literal 30-second Atlas grace window, discard partial Atlas output, and
allow Penny to retry through its existing quality path. Source/test evidence
does not imply launchd registration, live authentication, durable completion,
or downstream delivery.

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
Retryable work uses bounded exponential backoff. Archive publication failures
remain pending through bounded retries and then become visibly `failed`;
published-mirror conflicts use recoverable conflict quarantine. Terminal or
conflicting Apple-effect failures use quarantine, ordinary failures remain
`failed`, and ambiguous timeouts remain `uncertain`. Maya terminal delivery
uses `dead_letter`.

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
