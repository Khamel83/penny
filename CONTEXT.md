## Retry-retention recovery — October 16, 2026 UTC

[#112](https://github.com/Khamel83/penny/issues/112) remains useful: SSD
relocation is already done, but retry retention is absent from default source.
A metadata-only audit found 222 retry directories / 10,058,528,230 bytes on the
mounted SSD: 161 terminal, 60 pending-review and one invalid receipt. No raw
capture or model payload was opened into the review. The suspended G2K compact
bundle/patch was hash-verified and reproduced exact candidate tree6670b56e;
its original bytes, failures, attempts, native holds and manifest are preserved.
Executor handoff is recorded under RepoLock in #112 comment6212285354.

The recovered source adds the SSD default and terminal-audio/14-day retention.
It now protects every pending, unknown, malformed or incomplete state, fresh
receipts in old directories and symlink boundaries; missing SSD fails closed.
Full pytest passed836tests/two skips/60subtests in31.17s before the final
symlink-entry preservation regression; current34focused retry/server tests pass. Review5545710932
found a missing directory fsync before audio release and symlink-ancestor gap;
both are corrected with regressions. Review5545766004 also found equivalent
path spelling could bypass mount checks; nonphysical paths now fail before
creation/save, with absent-mount alias regressions. Review5545803745 found
expiry still removed symlink entries; those terminal directories now stay, with
a red-then-green regression. New exact-head review/CI/merge are pending.
Source, installation and an ordinary retry receipt remain separate gates.
No historical prune, migration, ASR reload, ledger mutation or replay occurred.
The complete existing retry tree now has a hash-verified, durable, write-protected
local SSD backup:443files/10,058,528,230bytes, tree SHA256
`02dea867cc8d93f2d3ed2f803b756657574d7c491dbb9a550414bf475a38efff`.
Fresh source/backup checks remain required before activation; the primary
runtime/keeper and Doctor acceptance below are preserved.

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
Retry retention remains open in [#112](https://github.com/Khamel83/penny/issues/112).

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

Source commit `f045c72898d2bdba2621b5fc62fa0c83e369cae3` (PR #100) merged the
natural-acceptance documentation. Recent commits `f9c7fc6` and `3b61a9a`
labeled ledger timestamps precisely and verified natural Parakeet voice notes
with active Maya delivery.
<!-- janitor:end:recent -->
