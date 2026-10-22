## Shared iCloud transcript view — October 21, 2026 source checkpoint

The owner asked for shared iCloud storage that stays tailored and text-only.
A one-time snapshot exists: 345 Markdown transcripts plus `INDEX.md`
(~2.06 MB) in iCloud Drive `Sync/Penny Transcripts`, copied from the SSD
mirror with a SHA-256 readback for every file. The separately retired
~93.3 GB legacy `Sync/Penny Archive` cloud tree stays deleted; this work
does not resurrect, hydrate, export, or recover it.

This source change makes that snapshot incrementally maintained instead of
manual. `transcript_view.py` renders one Markdown file per accepted
transcript plus one index, with stable filenames derived from the canonical
transcript row, compact provenance (canonical id, source, capture and ingest
time, transcript digest, audio digest, backend, model, quality status), and
no recording titles. `transcript_log.py` gains the additive
`transcript_view_publications` table: a row becomes eligible when its
local-mirror trio is published, so the view mirrors the accepted, archived
capture set — the same population the snapshot was copied from. Held and
migrated-placeholder rows are never queued, and
`queue_transcript_view_backlog` reconciles accepted, already-archived rows
that predate the view. `watcher.py` drains that outbox inside its existing
ingest pass; there is no new scheduler, no replay, and no invented text.

The shared view holds no audio, raw JSON envelopes, databases, models,
backups, or hidden conflict generations. Source recordings stay on the local
SSD, and `config.py` rejects a view root that nests the object store or the
local archive mirror.

Source state only: the change is unmerged and undeployed in this worktree.
Local suite: 523 tests with two pre-existing environment failures unrelated
to this change (`tests/test_apple_pilot.py` import form and a `jsonschema`
version difference in `tests/test_transcript_contract.py`); the 25 new view
and configuration tests pass. Trust-check phases 1-5 pass. No runtime,
iCloud, or downstream delivery effect is claimed here; see
[the shared transcript view contract](docs/transcript-view.md).

The shared-view configuration cannot be discarded silently: `Config` requires
the `transcript_view` field, the parsed TOML and `PENNY_TRANSCRIPT_VIEW_*`
values are passed into it, the default root is absolute, and a relative root
or a root that nests the archive object store or local mirror is rejected at
load time. The watcher also refuses a non-absolute root.

## Shared ASR TCC containment — October 19, 2026 local

The earlier green ASR checkpoint is superseded by a live, intentionally
contained outage. Launchd repeatedly started the shared service and it exited
after about 11 seconds. The private capture recorded Python's encodings import
interrupted on the SSD-backed runtime; matching unified-log evidence records
955 removable-volume TCC watchdog expiries across 101 PIDs from
20:17:00–20:29:38 PDT. The same environment stayed healthy in a 15-second
manual alternate-port run, separating the application from the launchd/TCC
boundary.

Only `com.penny.shared-whisper-keeper` and `com.penny.shared-whisper` were
booted out at about 20:31:33 PDT to stop the retry loop. Both are unloaded;
10311 and local/tailnet health are down intentionally. `export`, `tasks`,
`watcher` and `webhook` remain loaded. Original plist bytes and hashes,
existing dirty source, data, models, providers and privacy state are preserved.
[Full evidence, receipt and exact re-enable gate](docs/asr-tcc-containment-20261019.md).

The remaining blocker is owner-only macOS removable-volume authorization or a
supported runtime identity change. No TCC reset, security grant, SSD move,
source workaround, manual daemon or model/provider fallback is deployed.

## Penny health green — October 18, 2026 local / October 19 UTC

Owner retired historical recovery and approved acknowledgement of the reviewed
past failures. [PR132](https://github.com/Khamel83/penny/pull/132) merged8606b497
after exact-head trusted PASS, both hosted checks and independent Janitor receipt.
Final validation:852passed/two skipped/60subtests; trust497tests/two skipped.
Exact merged Doctor/helper/operator bytes are installed; only webhook reloaded.
Fresh SSD/Homelab backup20261019T061523Z verified. Current `/ready` and OCI's
projection both report ready at8606b497; Homelab API reports Penny healthy.

The acknowledgement preserves ledger history and exposes raw/acknowledged
counts: Maya9, old capture failures2, unavailable1, test quarantine1. New or
changed failures still alert. Existing history and canonical placeholder336
match the before-image. Watcher636/tasks638/ASR650 and protected modules/peer
plists were preserved. [Evidence, private receipt and rollback](docs/health-audit-20261018.md).

Kuma parent22 and declared-check23 have ordinary saved UP heartbeats at
06:25:46UTC; readiness24 is UP at06:25:47. Parent reports all children up.
All three are green; historical uptime rows remain. No threshold was relaxed.
Next: normal monitoring. Recheck `/ready`, OCI's existing8793projection and
Kuma's latest22/23/24heartbeats when investigating a future new failure. No
historical recovery, missing-content chase or replay remains in flight.
The same `.worktrees/health-repair` was reused for source and acceptance;
retain clean for safe reuse after accepted publication. No sibling checkout
or separate acceptance worktree was created.

## Parakeet timing accepted — October 16, 2026 11:12 UTC

[#111](https://github.com/Khamel83/penny/issues/111) is delivered by
[PR126](https://github.com/Khamel83/penny/pull/126): exact22904fa received trusted
PASS5546707424, both actual hosted Python3.11/3.12 jobs passed
[run38889557502](https://github.com/Khamel83/penny/actions/runs/38889557502), and
normal merge64d32534 has independent readback. Retained candidatea0bdf579 was
reused, with only invalid-start guards/regressions added. Local92focused,
848full/two skips/60subtests,497trust/two skips and62unchanged Whisper comparisons
pass; no fresh implementation or fixture weakening replaced the retained work.

Exact merged quality/server modules are installed, and only the three loaded
callers were refreshed. ASR/watcher/webhook PIDs67159/67194/67201 declare64d32534.
Independent11:12:52UTC readback verifies both module hashes, all56 protected
production Python files, Doctor3210731d/retryc568bd45, keeper, peer services,
original caller identity and primary HEAD65758e82. ASR health200/idle retains
pinned Parakeet; local readyHTTP200 has13components/zero unready, overall degraded.
The installed-code four-vector probe passes without a model call or data write.
[Receipts, preservation and next step](HANDOFF.md).

Acceptance is assessed against the original five criteria: timing/existing-suite
tests plus the PR description's post-deploy archive instruction. PR126 supplies
that instruction; executing the archive or observing another natural inference
was not required. The held recording/sidecar, retry receipt and verified112
backups remain unchanged; its current Parakeet hold is still active. Broader
Atlas quality work and ordinary serving quality remain separate and unclaimed.
After normal review/CI/merge of these records, close111 COMPLETED under fresh
native/peer/lease/source fences, removing only its resolved hold labels. No
owner action, audio replay, new archive task or production redeploy is added.

## Retry retention installed — October 16, 2026 09:52 UTC

[#112](https://github.com/Khamel83/penny/issues/112) source is delivered by
[PR122](https://github.com/Khamel83/penny/pull/122), merged85900798 after exact
b5ab29f trusted PASS5545840725. Both hosted Python checks passed native run
38881833594; Python3.11 verified837tests/two skips/60subtests plus497trust tests.
The preserved OCI candidate6670b56e was reused. Review-found durability,
mount-alias and symlink-preservation defects were corrected before acceptance;
original compact source, failures and attempt/grant history remain intact.

Only merged shared_whisper/retry_receipt.py was installed; idle-only ASR reload
accepted source85900798/PID58688. Caller PIDs, keeper/other launchd plists,
other production Python files and primary HEAD65758e82 were preserved. Current
intentional primary deltas are Doctor and retry_receipt.py. Independent ASR
health is HTTP200/idle with pinned Parakeet identity and no resident worker;
local `/ready` remains HTTP200, zero unready, Drop pending/failed/uncertain=0,
skipped=1 and webhook sourcec9b0368a. No inference or delivery was manufactured.

The installed helper's isolated synthetic probe releases terminal audio while
retaining its receipt and preserves old pending audio. Acceptance decision,
October16 10:13UTC: #112's original four criteria are tests, all satisfied by
PR122, passing native CI and the installed probe. The independently verified
installation completes that task. The extra wait for an ordinary retry is
removed; its future receipt remains unobserved and is routine monitoring, not
an owner decision or a reason to keep #112 held. All preexisting retry bytes
were verified into a durable,
write-protected local SSD snapshot before activation:449files/10,059,792,302bytes,
tree3e696430c186638e60d098a3ea701728717cdec0dc5f3121c2b69178f95c77e1.
The earlier443-file snapshot stays. No migration or historical batch prune ran.
[Private receipts, rollback and next check](HANDOFF.md).

## Current Doctor acceptance — October 16, 2026 UTC

[PR115](https://github.com/Khamel83/penny/pull/115) is merged as `c9b0368a`;
its Doctor skip counter is installed with the exact merged hash. Only the
webhook was reloaded, with source stamp c9b0368a and fresh PID30252. Local and
OCI-via-existing-SSH `/ready` pass HTTP200 with no unready components;
Drop pending/failed/uncertain=0 and skipped=1. The ASR daemon PID2025, keeper,
other launchd plists, 57 other production Python files and primary HEAD65758e82
are preserved. This is a component deployment, not a whole-checkout release.

A startup-probe race caused the first attempt to restore the previous bytes;
independent readiness verified restoration before a distinct bounded-warmup
attempt succeeded. Fresh SSD/Homelab backup verification and both private
receipts are retained; [current handoff](HANDOFF.md) records hashes and rollback.
61 focused tests, 497 trust tests/two skips, exact-head trusted PASS and both
hosted Python checks pass. No replay or ledger mutation occurred. Historical
October10 retirement evidence remains dated; #111, #112 and Infra-owned #110
acceptance retain their separate scope.

## Current shared ASR keeper checkpoint — October 16, 2026

PR119 is merged as `6330b398` after exact-head trusted PASS and Python3.11/3.12
native CI. Its independent Janitor merge receipt is verified. The exact merged
keeper template is installed and revision-stamped; only the keeper label was
reloaded, preserving the ASR daemon PID. Initial and first ordinary scheduled
runs exited 0 on the 120-second interval; local and Homelab health return pinned Parakeet with one idle worker.
The SSD before-image and deployment receipt support keeper-only rollback.
[Evidence and limits](docs/shared-whisper-keeper-20261016.md).

Penny `/ready` has no unready components; current Drop pending/failed/uncertain
counts are zero. These observations supersede older runtime snapshots below.
Historical source tasks and receipts remain; no downstream replay or real
outage/reboot canary was performed.

## Current repository-plan checkpoint — October 11, 2026

The owner requested one owning plan for every open TODO, issue and PR. [docs/REPO_PLAN.md](docs/REPO_PLAN.md) maps 2 unchecked source references and 6 open native records observed from `cfcae61fd36bb9ac0cf573d76d6f57493c59b536`. G2K is the executor; coordinator116 tracks project-owned acceptance. Previous source prose below is retained as dated evidence, not refreshed runtime attestation.

This source proposal requires trusted exact-head review, native CI and normal merge before audit117 is closed or finite sequencing is applied. Source, installation, ordinary receipt and downstream effect remain separate. Next: verify this PR’s current head and accepted native merge, then update the existing coordinator; resolve the explicitly listed next review/receipt/decision in plan order. No busy worker, host service, access policy or retry state was changed.

# Penny current context

## Current readiness — October 10 UTC

Owner approved intentionally skipping delivery of old quality-held note 779
while retaining it locally. Outbox row 335 is skipped, not accepted; payload,
audio, transcript and original failure receipt remain. `/ready` is HTTP 200
with zero unready components. Drop ready: pending=0, failed=0, uncertain=0,
skipped=1. Scoped Doctor skip-count visibility is installed; 51 focused tests
pass. [Evidence](docs/drop-owner-skip-779-20261010.md). Source publication of
this small reporting change is in [PR115](https://github.com/Khamel83/penny/pull/115);
live effect is verified.

## Current storage decision and state — October 9

Owner requires Penny-owned data on the 2 TB SSD. Actual state and checkout are
now `/Volumes/2TB_SSD/AI/Penny/state` and `/Volumes/2TB_SSD/penny-runtime`; old
home paths are compatibility symlinks. Future mirror writes, caches and scratch
are SSD-backed. All five Penny jobs check the mounted volume UUID and keep
system logs on SSD. Four continuous services run; scheduled backup is idle. Original Python launcher
identity is retained for watcher/webhook/tasks; fresh Voice Memos access passes.
The October9 storage checks passed SQLite integrity, archive, backup and
transcription. Later readiness update, October10UTC: `/ready` returned HTTP200
after the owner-directed skip of note779. No downstream receipt was manufactured. [Verification](docs/ssd-storage-20261009.md). Source record: [PR113](https://github.com/Khamel83/penny/pull/113) merged
as `5d63847073dd00ac874611a8b0273611277b520b`; scoped runtime installation
and old component stamps remain distinct.
Retry retention is accepted in the current [#112](https://github.com/Khamel83/penny/issues/112) checkpoint above.

Current capture acceptance verified October 4, 2026; the repair checkpoint below is dated October 2. Penny is the only repository in this task.
The owner authorized completion of Penny repairs and self-review/normal merge
when hosted review is delayed. Protected dirty runtime files remain intact.

## Drop handoff diagnosis — October 9 local / October 10 UTC

One uncertain item is transcript 779 (outbox 335), attempted October 8
04:04:04 UTC during the earlier R2 incident. The frozen 50,334-byte payload
is preserved in SSD SQLite. Its named Drop ID and payload hash have no OCI
archive receipt; both private metadata/content APIs return 404. That did
not alone prove absent R2 data. Subsequent installed OCI R2 readback found both
named objects absent, no matching ID at any date, and 1,062 event keys all
archived. Note 779 is 64 minutes and quality-held (`needs_review`); the owner
asked not to spend forever. Keep the original safe; owner selected keeping locally and skipping delivery;
no resend was made. Current Drop status reports all five pieces and
four consumers healthy. Filed [Drop158](https://github.com/Khamel83/drop/issues/158) for exact R2
sidecar/raw readback and receipt-bound, duplicate-safe recovery. During that
earlier diagnostic investigation, no resend, provider effect, ledger mutation
or source-runtime change was made. The later October10 owner-approved recovery
did change outbox335 from uncertain to skipped, installed the scoped Doctor
counter update and reloaded only the webhook; original content/failure evidence
remained and no archive acceptance was fabricated.
[Later recovery evidence](docs/drop-owner-skip-779-20261010.md).

## Decisions

Use one shared pinned Parakeet v3 primary, bounded Whisper second opinions and
serial model loading/unloading. Apple pilot remains disabled. Structural quality
checks can hold malformed/repetitive output; they do not reliably detect fluent
omissions or establish ground truth. Do not replay held recordings or old
external deliveries. [ASR contract](docs/shared-parakeet.md).

## Verified state

- Source: PR94–96 merged. Final repair merge is
  `6ccf2286a2c6af1919e43b4eaba72465f8eb614b`. Local suite: 765 passed, 2 skipped,
  60 subtests. Trust: 497 tests, 2 skipped, PASS. PR96 hosted Python checks passed.
- Runtime: exact reviewed Apple modules/operator script installed through a
  scoped update; watcher, webhook and tasks carry `6ccf2286`. Shared ASR and
  export retain `c341598c`. Root Git HEAD and owner edits were preserved; this
  is a component deployment, not a whole-checkout revision claim. [INFRA](INFRA.md).
- Provider: one Note exists for canonical row 770. Notes' advertised `container`
  getter failed after creation; folder-membership and full normalized text
  readback succeeded. Explicit reconciliation stored the existing provider ID
  at attempt seven. The failed/uncertain history remains in private receipts.
- Ordinary processing: watcher routed row 770 and Voice Memo 443 at 19:36:51 UTC.
  Their existing archive and accepted Drop receipt are unchanged; no direct
  Slack/Maya delivery was added. Downstream consumers were not replayed or
  independently reverified by this Note repair.
- Readiness: installed `/ready` returns HTTP 200/degraded, no unready component.
  Shared pinned Parakeet is idle with zero resident workers; model/offline/memory
  checks pass. Capture coverage gap and current terminal failures are zero.
  Archive, backup and delivery queues are ready.
- Historical exceptions remain visible: one synthetic Apple quarantine,
  nine Maya dead letters, two old missing-audio failures and one unavailable
  memo. Held row 769 is unchanged and routing-suppressed.
- Reusable Apple skills are installed; Notes/Reminders access was verified.
  The Notes reference now records exact-folder membership readback and preserves
  uncertainty after a failed post-create probe.

The condensed handoff retains explicit local-routing, independent Slack and
independent Maya v2 receipt boundaries. The existing documentation contract
caught their omitted wording in PR97; restoring it changes guidance only,
without modifying deployed code or provider state.

## Natural-capture acceptance — October 4

Penny received three ordinary Parakeet voice notes, rows 772–774, on October 2–3.
All passed quality and routed. Local audio hashes, archive publication, Drop
archive hashes, Slack sent receipts and live Maya store-only source-event
receipts match. [Exact evidence and limits](docs/natural-parakeet-acceptance-20261004.md).

P01 is complete. P02 was a misleading gate for this workflow: Drop ownership
intentionally suppresses direct Maya eligibility for new iCloud captures. These
three notes already reached Maya through Drop. The legacy direct-v2 route is
not newly accepted by this evidence, and no pending work or dead letter was
replayed. New direct-v2 verification is conditional on future explicit use of
that separate route. Normal Penny voice-note acceptance has no remaining input
gate. Long-term stability remains observation over ordinary use.

Previous dated checkpoints remain in the
[historical context](https://github.com/Khamel83/penny/blob/6ccf2286a2c6af1919e43b4eaba72465f8eb614b/CONTEXT.md).
<!-- janitor:begin:recent -->
- Source commit `65f25969086727e956fd89547a45a51bd901d1cb` (docs: record deployed Penny acknowledgement and green Kuma heartbeats, #133).
- Deployed acknowledgement of reviewed historical failures merged in PR #132 (`8606b497`); installed readiness, OCI projection, and Homelab API report healthy.
- Parent Kuma 22 and checks 23/24 verified green with ordinary UP heartbeats at 06:25:46/47 UTC.
- PR-only concurrency cancellation merged via PR #129 (`f5835ddf`).
- Parakeet repetition timing (#111) and retry retention (#112) accepted and verified deployed in PR #126 (`64d32534`) and PR #122 (`85900798`).
<!-- janitor:end:recent -->
## Fleet CI cancellation - source checkpoint (October 16, 2026)

`.github/workflows/test.yml` has a prepared source change on `feat/fleet-ci-cancellation-20261016` that coalesces superseded pull-request runs and leaves main, manual, release, and scheduled runs non-canceling. Native CI, review, and normal merge remain pending; no runtime change is claimed.
