Apple launchd correction (October 1): first activation registered all six labels, but the pilot and optional capture correctly refused startup because launchd PATH excludes /usr/sbin. Bind volume identity checks to /usr/sbin/diskutil rather than relying on shell PATH. Canonical Whisper remained healthy; cohort not yet loaded. Re-deploy corrected source and verify fresh receipts before seeding.

Apple pilot review fixes (October 1): live snapshot disk work now runs in at most two daemon admission threads; overflow is refused without waiting. Only committed queue rows prove durability. Subprocess launch/register is synchronized with shutdown, including signal re-entry. Regression tests cover stalled storage and shutdown races. Deployment remains pending.

## Apple pilot in flight — October 1, 2026

The owner approved a real Apple workflow pilot. Work is isolated in `pilot/apple-speech-20261001`, started from fetched default `origin/main` `c1b0b1d`; production checkout's dirty documents remain preserved. Implemented modern native Apple CLI, bounded private queue, two sessions, real-request shadow hook, cohort seeder and source-bound deploy script. Focused tests and trust check pass; an 84.46-second generated recording completed through the pilot ledger and private result file. This is development execution, not launchd activation.

Next: review/merge exact source, preserve dirty production files, deploy using `venv/bin/python scripts/deploy_apple_pilot.py --apply`, seed the bounded 32 Penny + eight historical Atlas cohort, and verify fresh installed receipts and natural live Atlas/Penny admission. Current canonical row 769 stays held. Production response remains Whisper while Apple is evaluated. No pilot text may be replayed or delivered. See `docs/apple-speech-pilot.md` for private status commands, bounds and rollback.

## Shared Whisper memory deployment — September 30, 2026

PR #62 merged and deployed `63591bed`; all five labels activated. Post-request footprint fell from 2.3 GiB to 1.7 GiB on identical generated speech with identical transcript hashes; four varying-length requests also retained 1.7 GiB. See `docs/research/2026-09-30-shared-whisper-live-memory-receipt.md`. Natural application completion and multi-day busy-workload stability remain unproven. Internal simulator deletion remains blocked by protected assets; 14.8 GiB is still present, with Recovery the next coordinated step. Only the external 8.9 GiB cache was removed. Existing dirty Mac files were restored byte-for-byte after deployment.

# Shared Whisper RAM checkpoint — September 30, 2026

Isolated branch starts at fetched origin/main `4fe4f54`. The existing Mac checkout and its dirty documentation remain preserved. Cache limit/cleanup source and regression are implemented; focused tests pass. Deployment and real memory reduction are pending. Next: exact-head PR checks, merge, installed-source deployment, serial local canary and process footprint measurement. Internal simulator deletion is blocked by macOS restricted assets despite administrator authentication; do not claim reclaimed internal space.

# Penny handoff

## Verified runtime alignment — September 30, 2026 UTC

The approved infrastructure health work deployed reviewed remote main
`ce48505f1f2e81a924443e5cf878e41dd761fb46` with
`venv/bin/python scripts/deploy_penny.py --apply`. Trust checks and verified
backup passed; all five installed launchd labels report that revision. The
follow-up deployment check reports current. Private deployment receipt/plist
backups are under `~/.penny/deployments/20260930T061905Z`. Existing dirty
LLM-OVERVIEW.md and untracked CLAUDE.md were privately copied and stashed
temporarily, then restored with identical SHA-256 hashes; the stash is retained.
At 06:20 UTC, `/ready` reported the deployed revision and overall degraded.
This closes runtime revision drift, not application degradation or downstream
delivery. Homelab is implementing bounded monitoring from existing OCI Doctor
receipts. Next: verify natural 09:00 UTC receipt and truthful monitoring of
degradation; keep private transcript quality and historical items separate.

## Current checkpoint — Voice Memo recovery and OCI health — September 29, 2026

PR #57 merged at `61f88908`; the Mac checkout fast-forwarded to that main
without changing its unrelated dirty `LLM-OVERVIEW.md` or untracked
`CLAUDE.md`. The watcher-only launchd reload reports revision `61f88908`
and a private receipt under `~/.penny/deployments/20260929T184354Z-watcher-only/`.
Source verification was 91 watcher/historical tests with 10 subtests, Ruff,
the hosted Python 3.11/3.12 checks, exact-head reviewer pass, and the
installed-source trust check (491 tests, two skipped).

Exact Voice Memo PK 440, about 93 minutes, had a terminal failure after a
whole-file shared-Whisper request and retries. A first local-only recovery
attempt used a shell without the installed Whisper token and failed with a
protocol error; the token mismatch was then confirmed from the installed
launchd environment. It did not create a transcript or downstream row. With
the installed watcher
environment, a second scoped local-only pass completed 19 private 300-second
checkpoints and linked transcript row 769. Fifteen chunks failed the
consecutive-token-repetition quality rule, so row 769 remains `needs_review`
with routing suppressed. The archive is published and valid with receipt
`64f18bc8`; a fresh installed backup includes max transcript ID 769 and 517
rows. No Drop, Slack, quality-alert or Maya delivery was queued for that row.
No audio or transcript text was printed or sent.

Mac Doctor now exits 1 `degraded`, with services, transcription, backup and
archive ready and zero current Voice Memo terminal failures. OCI's supervised
`penny-health.service` ended success/exit 0 with mode-0600 receipt
`20260929T185944.154146+0000-3527be8927474e7a90f06c7fb3c2ec58.json`,
also `degraded`. Historical absences, Apple quarantine and old Maya dead
letters remain visible; this is not an all-ready claim. The obsolete GitHub
`health-check.yml` was removed by PR #58, merged as `873f5be7` after exact-head
review and hosted Python 3.11/3.12 CI; merged-main CI also passed. Historical
queued Health Check run 36589491752 and AI Review run 36491923787 were
canceled. The Mac source checkout fast-forwarded to that merge without changing
its dirty `LLM-OVERVIEW.md` or untracked `CLAUDE.md`; the watcher process was
not reloaded for this workflow-only change. Next: verify the first natural OCI
timer after recovery and keep row 769 private for quality review. Resolve the
remaining historical Doctor degradation separately.

## OCI review and Mac Doctor checkpoint — 2026-09-29

This branch removes the legacy `AI Review` workflow that requested the
retired `oci-ts` runner. The separate OCI PR reviewer passed Penny PR #53 at
its exact head. The old issue-triage job has no replacement proof.

OCI's live `macmini` and `macmini-ts` SSH aliases now target the current Mac
MagicDNS name; the verified host key matched the Mac and both aliases logged
in. A direct OCI-to-Mac invocation of the workflow's read-only Doctor command
ran, but returned `overall=unready`, `source_revision=unknown`, services
`launchd_unavailable`, and Voice Memos `terminal_failure`. GitHub scheduled
run 36457387408 remains queued on `self-hosted, oci-dev` with no matching
public runner. Next: move the scheduled check to a safe OCI-owned path, fix
Doctor readiness separately, and prove a natural receipt.

## Production closeout — 2026-09-22

The current Voice Memo path is local capture -> SQLite -> local shared Whisper
-> durable Drop handoff -> independent Slack delivery and Maya store-only storage.
See [Drop operations](docs/drop-delivery.md) for ownership, historical import,
real-memo proof, and downstream recovery. Legacy routing below applies to other
inputs and pre-cutover rows, not new Drop-owned Voice Memos.

Capture-health implementation `b9c3158802beafb174a2807b8515ac0f096759cd`
was pushed and verified in all five launchd services. The full suite at that
release passed 678 tests and 53 subtests, with two skipped. Documentation-only
closeout commits may follow; compare remote main and installed revisions with
`venv/bin/python scripts/deploy_penny.py` before making a fresh runtime claim.

At 2026-09-22T17:15:49Z, watcher, transcription, SQLite, archive, backup and Drop
were ready, with zero current terminal capture failures, zero source coverage
gap and zero pending/failed/uncertain Drop deliveries. Overall readiness was
degraded: two historical capture failures, one Apple quarantine and nine legacy
direct-Maya dead letters remain preserved. These are not new Drop delivery failures.
See [capture health](docs/capture-health.md); retain the fixed reporting boundary.

The available historical-text import and real-memo delivery gate are complete.
Missing audio, excluded placeholders and non-passed quality labels are not
recovered merely by indexing or importing them. Optional test permutations remain
listed in [release decisions](docs/drop-release-decisions.md), not as blockers to
normal capture. No new feature work or replay is required for this closeout.

Private evidence remains local in `~/.penny/capture-health-release-2026-09-22.json`
and `~/.penny/real-memo-762-verification-2026-09-22.json`. Recheck live health for
future incidents; this is a dated result, not a guarantee against future outages.

## Current Mac backup placement — 2026-09-22

[SSD backup placement](docs/ssd-backup-placement.md) records the owner-approved migration, installed mount-identity guard, matching export/webhook environment, fresh restore/remote proof, and retired internal staging. Preserve that placement in future plist rendering. The ledger and live audio were not moved; overall readiness remains separate from the passing backup checks.


## Historical synchronized shared-Whisper cutover — 2026-09-17

The following records that cutover's observations; its revision, test counts,
queue counts and readiness do not describe the current release above.

This is the Penny side of the Atlas handover plan:
`/Volumes/2TB_SSD/GitHub/atlas/.worktrees/minuspod-reliability-fix/docs/superpowers/plans/2026-09-17-shared-whisper-cutover-handover.md`.

- Source checkout: local `main`.
- Application source SHA: `f6e531d7919d19e61b7a65d73f5073e39a23e4e3`.
- Synchronized documentation commit: `d7d9a0d2c0818832b4ad193bcf8b953f1cffc1c3`.
- Source implementation: `shared_whisper/{protocol,client,server,supervisor,worker}.py`;
  `transcript_quality.py` calls the shared client and no longer owns MLX.
- Focused shared-Whisper verification: `16 passed`; Ruff and compileall passed.
  The full Penny suite is `602 passed, 2 skipped, 1 failed`; the remaining
  failure is the unrelated malformed RFC3339 timestamp contract test.
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
-  current queue state at the last read was 55 completed, 22 pending, and 1
  processing, with 2 historical terminal failures. The episode active during
  the Penny restart completed durably; it was not published with a missing
  Whisper chunk and has 2 review markers.
- Shared-Whisper word timestamps are now disabled by default; an explicit
  request still enables them. After restart the live Penny health response was
  authenticated and idle with `worker_count=1`, `worker_pid` present, and the
  supervisor's physical footprint was 33.3M with no loaded model workers.
- Atlas commit `91ce1f08` makes shared-mode chunk transcription fail closed
  (`max_failed_chunks=0`) and fixes the shared-worker assignment so it cannot
  be overwritten by the stock pool assignment. Homelab image `2.96.24` is
  deployed and the container source was checked for the exact patch.
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

The legacy durable path (other inputs and pre-cutover captures) is:

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
