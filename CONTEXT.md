# Penny current context

## Current storage decision and state — October 9

Owner requires Penny-owned data on the 2 TB SSD. Actual state and checkout are
now `/Volumes/2TB_SSD/AI/Penny/state` and `/Volumes/2TB_SSD/penny-runtime`; old
home paths are compatibility symlinks. Future mirror writes, caches and scratch
are SSD-backed. All five Penny jobs check the mounted volume UUID and keep
system logs on SSD. Four continuous services run; scheduled backup is idle. Original Python launcher
identity is retained for watcher/webhook/tasks; fresh Voice Memos access passes.
SQLite integrity, archive, backup and transcription checks pass. `/ready`
remains 503 for the same pre-existing uncertain Drop effect. No downstream
receipt was manufactured. [Verification](docs/ssd-storage-20261009.md). Source record: [PR113](https://github.com/Khamel83/penny/pull/113) merged
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
asked not to spend forever. Keep the original safe; skip-versus-retry preference
is pending and no resend was made. Current Drop status reports all five pieces and
four consumers healthy. Filed [Drop158](https://github.com/Khamel83/drop/issues/158) for exact R2
sidecar/raw readback and receipt-bound, duplicate-safe recovery. No resend,
provider effect, ledger mutation or source-runtime change was made.

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
