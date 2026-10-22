## Session handoff — October 21, 2026: iCloud cleanup complete locally

Owner-requested Sync/Penny Archive deletion is complete; local absence rechecked
at handoff. Existing SSD recordings remain outside iCloud. Historical offline
coverage was not verified before the owner explicitly ordered cloud deletion;
do not claim every deleted historical recording has an offline copy. Do not
recreate or recover the retired cloud tree without a new owner request.

Sync/Penny Transcripts contains 345 transcripts plus INDEX.md (346 Markdown
files, 2061967 bytes). Snapshot copy/hash readback passed. Automatic updates
remain unimplemented; owning issue https://github.com/Khamel83/penny/issues/136
was created and independently read back. No worker execution or deployment is
claimed. Next bounded job is incremental text-only export through existing Penny
delivery machinery, followed by an actual new-transcript delivery check.

Maya shared folder is about13KB; Trojanhorse shared folder about12KB. The old
93.3GB logical archive was Penny conflict/history material. Work-Mac deletion
sync and iCloud quota reclamation are not verified. Existing prepared Maya/Trojan
jobs remain inactive; this cleanup did not resume their deployment. Keep all
protected runtime/source edits and existing setup gates intact. Private deletion
and Markdown-copy receipts remain under
/Volumes/2TB_SSD/AI/Penny/verification/20261021-icloud-legacy-inventory/.

## Text-only iCloud view and owner-requested cloud retirement — October 21

Verified Sync/Maya contains only 12573 logical bytes (two small Markdown files,
a synthetic EML, two empty status logs and Finder metadata); Sync/Trojanhorse
contains 12062 bytes. These shared folders are not the large private Maya corpus.
Created Sync/Penny Transcripts with 345 existing SSD-mirror Markdown transcripts
and INDEX.md: 1988899 transcript bytes plus 73068 index bytes. Every copied
transcript has SHA-256 readback verification. No audio/JSON copied. This is a
one-time text snapshot, not automatic delivery and not work-approved Trojan data.
Private receipt: /Volumes/2TB_SSD/AI/Penny/verification/20261021-icloud-legacy-inventory/markdown-export.private.json.

Owner explicitly requested immediate removal of Sync/Penny Archive after the
unverified historical offline coverage was explained, then reconfirmed keeping
the existing SSD material. Cloud deletion completed at 2026-10-21T20:28:28Z; local target absence was
verified. Current SSD archive and text snapshot are preserved. This supersedes the earlier preservation-before-
removal next step for this specific legacy folder. Do not start duplicate
hydration/export/recovery. Cross-device disappearance is not verified.

https://github.com/Khamel83/penny/issues/136 records the bounded automatic
Markdown-only export requirement. Its subsequent comment records the owner's
immediate deletion direction. Open eligible catalog issue, no active PR observed;
worker execution has not been proven. No source/runtime deployment or job
activation was performed. Prepared Maya/Trojan jobs remain inactive.
Next: keep issue136 open until actual incremental Markdown delivery is deployed
and demonstrated. Local deletion does not prove work-Mac sync or cloud quota
reclamation. Existing owner work
and pending setup gates remain intact.

## Health investigation — October 18, 2026 local

## Legacy iCloud Penny Archive identified — October21

Owner wants raw audio outside iCloud. The old Sync/Penny Archive was Penny's
historical audio/Markdown/JSON mirror. October9 storage migration moved future
writes to SSD; loaded watcher/webhook environments now independently confirm
object root /Volumes/2TB_SSD/AI/Penny/state/archive/objects and mirror root
/Volumes/2TB_SSD/AI/Penny/archive-mirror. Current readiness reports archive ready
(345 published, zero pending/failed) and backup verified. No config or service
change is needed to keep new raw audio outside iCloud.

Legacy cloud inventory:183119 files/93290058034 logical bytes. Ordinary year
folders hold503 audio files (~3.08GB); hidden .penny-conflicts holds60536 audio
files (~89.99GB audio,90.21GB including metadata). All61039 audio files are
cloud-only placeholders. Latest ordinary audio mtime October9; conflict audio
September22. Do not call this logical size current local disk usage. SSD objects
currently contain347 audio files (~1.75GB); this does not prove all historical
cloud originals are preserved there. No automatic deletion/deduplication is safe
from these counts alone. Internal disk has ~13GiB free; no bulk hydration started.

Creator: Penny's archive publication/conflict-preservation machinery, not Maya's
new work-note jobs. Future layout: raw audio/archive on SSD/backups; useful text
notes may live under shared iCloud Sync. Legacy cloud retirement remains pending
an offline copy and byte verification; no audio downloaded, moved or deleted in
this bounded diagnosis. Metadata-only inventory and its SHA/summary are at
/Volumes/2TB_SSD/AI/Penny/verification/20261021-icloud-legacy-inventory/ (private). Preserve existing history and runtime edits.
Next: use that pinned inventory for a bounded offline export before any cloud
removal; do not restart Penny, replay captures or reopen global historical gaps.

- [x] Diagnose installed and external Penny health; verify no current unready
  component, preserve historical holds and attempt bounded local recovery.
  Source135 audio is corrupt in both available copies; failed attempt rolled
  back without new downstream rows. [Evidence](docs/health-audit-20261018.md).
- ~~Recover missing/corrupt history and replay legacy Maya dead letters~~ —
  owner retired this work October18; preserve old data and receipts.
- [x] Deploy exact-record acknowledgement of reviewed history; installed
  readiness and OCI are ready, Homelab API healthy, Kuma leaves23/24 UP.
  New/changed failures still alert. [Evidence](docs/health-audit-20261018.md).
- [x] Verify parent Kuma22's ordinary UP heartbeat and both child checks:
  all three saved UP at06:25:46/47UTC; parent reports all children up.
  [Acceptance](docs/health-audit-20261018.md).

## Parakeet repetition timing — October 16, 2026 UTC

- [x] Complete [#111](https://github.com/Khamel83/penny/issues/111) from its
  retained candidate. [PR126](https://github.com/Khamel83/penny/pull/126) merged
  64d32534 after exact trusted PASS and both native hosted checks;92focused,
  848full/two skips/60subtests and497trust/two skips pass. The exact two modules
  are installed with ASR/watcher/webhook refresh and independent source/peer/
  health/readiness verification. Its original fifth criterion is the PR body's
  post-deploy archive instruction, already supplied; actual archive execution
  and a future ordinary inference were not completion requirements. The active
  Atlas quality hold and all recording/receipt/backup bytes remain intact.
  [Acceptance, private receipts and guarded native closure](HANDOFF.md).

## Retry retention — October 16, 2026 UTC

- [x] Reassess [#112](https://github.com/Khamel83/penny/issues/112), preserve its
  retained source and correct unsafe pending/unknown expiry, durability and
  symlink/mount boundaries. [PR122](https://github.com/Khamel83/penny/pull/122)
  merged85900798 after exact trusted PASS and both native checks;837pytest and
  497trust tests passed (two skips each).
- [x] Verify complete local SSD backup before scoped helper installation/idle
  ASR reload; check exact bytes, loaded source, unchanged callers/peers and
  installed synthetic terminal/pending behavior. [Receipt and rollback](HANDOFF.md).
- [x] Accept [#112](https://github.com/Khamel83/penny/issues/112) against its
  original four test criteria: SSD-root placement, terminal audio release with
  receipt preservation, pending-review protection, and passing existing tests.
  [PR122](https://github.com/Khamel83/penny/pull/122) and the installed probe satisfy
  these checks; installation is independently
  verified above. A future ordinary retry remains unobserved, but was not an
  original completion requirement. Remove the extra acceptance hold; observe
  normal use without replay or historical batch prune.

## Doctor reporting completed — October 16, 2026 UTC

- [x] Finish [PR115](https://github.com/Khamel83/penny/pull/115) skip-count
  source publication while preserving keeper acceptance and correcting the
  earlier investigation/recovery chronology. Exact-head trusted PASS and both
  hosted Python checks passed; normal merge c9b0368a is verified.
- [x] Install exact merged Doctor bytes and reload only the webhook after a
  fresh verified SSD/Homelab backup. Local and OCI-via-existing-SSH `/ready`
  return HTTP200, zero unready, Drop pending/failed/uncertain=0 and skipped=1;
  ASR PID and other production files/plists are preserved. First-attempt safe
  restoration and the accepted bounded-warmup attempt are retained with
  independent readback. [Receipt, limits and rollback](HANDOFF.md).

# Penny TODO

## Shared ASR keeper — October 16, 2026

- [x] Finish [PR119](https://github.com/Khamel83/penny/pull/119): private
  directory strikes, tolerant health parsing, truthful recovery reporting and
  timed-agent CI contract. Exact-head trusted PASS, native CI and independent
  Janitor merge receipt verified; merged `6330b398` keeper-only bytes installed
  with SSD rollback receipt and unchanged ASR daemon PID. Initial and first
  ordinary scheduled runs exited 0; local and Homelab health pass. Real outage/reboot recovery is unexercised.
  [Evidence](docs/shared-whisper-keeper-20261016.md).

## Immediate SSD relocation — October 9

- [x] Remove Penny-owned state, archive, models, logs, cache, scratch and actual
  runtime checkout/environment from the internal disk; verify copied bytes,
  SQLite integrity, restored services and fresh Voice Memos source access. Internal free space is 26 GiB.
  [Evidence](docs/ssd-storage-20261009.md),
  [PR113](https://github.com/Khamel83/penny/pull/113).
Retry retention is tracked in the current #112 checkpoint above. Relocation is
complete; this earlier storage operation did not implement retention.
- [x] Retire note 779's Drop delivery at the owner's request; keep audio,
  transcript, frozen payload and original failure receipt locally.
  `/ready` HTTP 200, Drop uncertain=0 and skipped=1.
  [Evidence](docs/drop-owner-skip-779-20261010.md),
  [Drop158](https://github.com/Khamel83/drop/issues/158).

Updated October 4, 2026; natural-capture evidence below supersedes the October 2 input gates. This is Penny's active queue. Older dated
checklists are superseded; their evidence remains in the
[previous TODO](https://github.com/Khamel83/penny/blob/6ccf2286a2c6af1919e43b4eaba72465f8eb614b/TODO.md) and linked operational documents.

## Completed

- [x] Select, integrate and deploy one shared Parakeet primary with serial,
  bounded Whisper fallback and idle unloading. Preserve actual backend identity,
  timing validation, durable quality holds and protected recordings. Reviewed
  Penny/consumer activation and rollback evidence:
  [shared ASR hardening](docs/asr-hardening-20261002.md),
  [runtime contract](docs/shared-parakeet.md). Apple background pilot stays off.
- [x] Repair capped routing selection and the real queued Note. [PR94](https://github.com/Khamel83/penny/pull/94),
  [PR95](https://github.com/Khamel83/penny/pull/95) and
  [PR96](https://github.com/Khamel83/penny/pull/96) are merged; correction source
  `6ccf2286a2c6af1919e43b4eaba72465f8eb614b` is installed in the three callers.
  Exactly one Note was created; full content/target readback reconciled attempt
  seven. The ordinary watcher routed canonical row 770 and Voice Memo 443 at
  19:36:51 UTC. No transcript or delivery replay. [Procedure/evidence](docs/capped-note-repair.md).
- [x] Pass final local source checks: 765 tests passed, 2 skipped, 60 subtests;
  trust check 497 tests, 2 skipped, PASS. Both PR96 hosted Python 3.11/3.12 checks
  passed. This supersedes the old missing-format-extra full-suite failure.
- [x] Verify installed `/ready` returns HTTP 200 with no unready component;
  capture, archive, backup, shared ASR and delivery queues are ready. Historical
  quarantine, nine Maya dead letters, two old missing-audio failures and one
  unavailable memo remain visible as degraded. [Current state](CONTEXT.md).
- [x] Install reusable Apple app skills and verify Notes/Reminders access.
  Preserve the corrected exact-folder Notes readback in the skill reference.
  [PR91](https://github.com/Khamel83/penny/pull/91),
  [Reminders recovery](docs/reminders-recovery-20261002.md).
- [x] Retire unmatched legacy GitHub review/health runners (commits `3068fe0`,
  `35a4c83`); hosted-only workflow guard is enforced by the trust check. OCI's
  natural 09:00 UTC Penny observer recorded the actual Apple failure; its
  supervised 19:37 UTC check recorded recovery to degraded. Timer remains active.
  Observer environment limits are explicit in [INFRA.md](INFRA.md).
- [x] Preserve explicit local-routing, independent Slack and independent Maya v2
  evidence boundaries in the condensed handoff; keep the documentation contract
  enforced by existing tests.
- [x] Consolidate duplicate and obsolete TODO/CONTEXT/HANDOFF checkpoints;
  keep current evidence and genuine input gates separate from historical plans.

## Natural-capture acceptance completed October 4

- [x] **P01 — New post-Parakeet Penny recording.** Ordinary captures 772–774
  from October 2–3 all used pinned Parakeet, passed quality and routed. Local
  audio hashes, archive publication receipts, matching Drop archive hashes,
  independent Slack sent receipts and Maya store-only source-event receipts
  are verified. [Evidence and limits](docs/natural-parakeet-acceptance-20261004.md).
- ~~**P02 — Wait for a new direct Maya v2 input.**~~ This is not the active
  voice-note route: new iCloud captures are Drop-owned and intentionally direct
  Maya-ineligible. All three already have Maya receipts through Drop. Retain
  direct-v2 acceptance only if that separate path is explicitly exercised;
  preserve its nine historical dead letters.

No input-gated implementation or acceptance task remains for the normal Penny
voice-note path. Observe long-term stability during ordinary use; no new bulk
benchmark or manufactured capture is required.

## Deliberately retired or outside this queue

- ~~Apple primary adoption / further bulk model benchmarks~~ — owner chose
  Parakeet with selective Whisper; [issue70](https://github.com/Khamel83/penny/issues/70)
  is closed as not planned. Existing research and paused pilot artifacts remain.
- ~~Protected Apple Events service kickstart~~ — invalid under enabled SIP;
  working Notes/Reminders access and receipt reconciliation replaced it. Keep
  SIP and privacy grants intact.
- ~~Repeat production rollback solely for evidence~~ — reviewed rollback artifacts and
  bounded switch-back canaries are retained. A disruptive full rollback rehearsal
  remains unexercised and is deferred to a real maintenance need.
- Atlas publication/backlog and held podcast excerpts belong to Atlas; their
  older checkpoints do not reopen a Penny implementation task.
- Another project's first Apple-skill operation needs that project's actual
  request/caller/target. No unrelated project was used to manufacture acceptance.
- Finder window timeout and protected simulator cleanup are outside Penny's
  capture/Notes/Reminders path. No Calendar/Mail/Messages adapter is claimed.
- Held row 769 and synthetic quarantine row 493 are intentional preserved states,
  not requests to retranscribe, replay or erase evidence.
<!-- janitor:begin:todo -->
Active work queue is canonical in repository `TODO.md` (all open tasks outside Janitor block are resolved or completed; see handwritten queue and docs/REPO_PLAN.md).
<!-- janitor:end:todo -->

## Owning repository plan

Use [the ordered reconciliation](docs/REPO_PLAN.md) and [coordinator #116](https://github.com/Khamel83/penny/issues/116). It maps every observed open source record. Existing incomplete acceptance and holds remain in force.
## Fleet CI cancellation - source checkpoint (October 16, 2026)

- [x] `.github/workflows/test.yml` has a prepared PR-only concurrency cancellation change on `feat/fleet-ci-cancellation-20261016`; native CI, review, and normal merge remain pending. No runtime change is claimed. Done (model-matched): https://github.com/Khamel83/penny/pull/129
