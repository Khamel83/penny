## iCloud transcript view — deployment checkpoint October 26, 2026

- [x] Merge PR146 and deploy exact `b4181aa` through the documented clean-main
  procedure. Follow-up reports current; watcher running and `/ready` ready.
- [x] Verify baseline paths preserved: 345 unique transcript IDs + INDEX.md,
  zero duplicates/non-Markdown files; index hash recorded privately and in evidence.
- [ ] Complete byte/hash snapshot reconciliation: File Provider reads timed out;
  counts and index hash alone do not prove completion.
- [ ] Observe an ordinary new passed transcript after private baseline ID796,
  verify automatic Markdown bytes and index entry. Keep
  https://github.com/Khamel83/penny/issues/136 open; no fabricated recording.
[Deployment receipt, limits and next check](docs/icloud-view-deployment-20261026.md).

## Stalled Voice Memos sync — October 24, 2026 local

- [x] Recover memos stuck off the Mac since the October 22 10:11 reboot.
  `voicememod` (PID 843) was alive but imported nothing; `CloudRecordings.db`
  was unchanged since 10:12. Killing it at 18:40 synced 5 recordings (Oct 22
  11:57 through Oct 24 17:52); watcher began processing PK 462+ at 18:41.
- [x] Merge and deploy the watcher idle-sync recycle (restart `voicememod`
  when the sync DB is idle 3 h, at most once per 3 h). Merged in
  https://github.com/Khamel83/penny/pull/141; `deploy_penny.py --apply`
  activated `0ee8f38` on all five labels at 18:47 PDT; `/ready` overall ready.
  First live recycle not yet observed (needs 3 idle hours).
- [x] Classifier model blocked: `google/gemini-2.5-flash-lite` has no allowed
  OpenRouter provider on this account. Owner approved any cheap model. Now
  `openai/gpt-4.1-nano` with OpenRouter `models` fallback to
  `meta-llama/llama-3.1-8b-instruct`; live call via the blocked model fell back
  to gpt-4.1-nano. G2K not used: Penny's contract keeps transcripts off G2K.
  Owner then chose `~deepseek/deepseek-v4-flash-latest` (alias; resolved to
  `deepseek-v4-flash-0731` on October 24) with reasoning disabled, keeping the
  same fallback list.

## Shared ASR hang recovery — issue #138

- [x] Complete local deadline observability and keeper stale-job recovery for
  https://github.com/Khamel83/penny/issues/138. Existing 900-second/2×duration
  deadline retained; warning and epoch start/monotonic age added. Review fix
  explicitly enables scoped warning capture despite suite-wide logging
  suppression; 37 focused tests pass with that suppression seeded. Loopback
  HTTP smoke verifies the warning, hung-worker termination/503 and replacement
  success/200. Evidence and recheck command: [handoff](HANDOFF.md).
- [ ] Deploy reviewed supervisor and keeper, force a safe synthetic hang, and
  independently verify MinusPod resumes and Kuma `atlas.mac-asr` records the
  failure. Not performed by the worktree-only worker.

## Shared ASR TCC containment — October 19, 2026 local

- [x] Diagnose the failed `com.penny.shared-whisper` start. A private launchd
  projection captured `Fatal Python error: Failed to import encodings module`
  and `InterruptedError: [Errno 4] Interrupted system call`; unified logs show
  955 `kTCCServiceSystemPolicyRemovableVolumes` watchdog events across 101 PIDs
  in the fixed 20:17:00–20:29:38 PDT window.
- [x] Contain the respawn loop by booting out only the keeper and shared ASR
  labels. Original plist hashes, data, source, model, providers, TCC state and
  the four peer labels were preserved; local and tailnet health remain DOWN by
  design. [Incident receipt and re-enable gate](docs/asr-tcc-containment-20261019.md).
- [ ] Owner-only gate: resolve the supported macOS removable-volume
  authorization/runtime condition, then bootstrap the unchanged original ASR
  plist, verify stable health/no respawn, bootstrap the keeper, and verify its
  scheduled run plus Kuma heartbeat. Do not claim recovery before those facts.

## Health investigation — October 18, 2026 local

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


- [x] Verify retained issue #110 source candidate locally: guarded Drop skip,
  metadata-only `skipped_count`, and unresolved attempt evidence/replay protection.
  71 Drop/Doctor/export tests passed after authorized default integration;
  synthetic SQLite smoke verified the uncertain-to-skipped readiness boundary
  without real delivery.
  [Evidence and remaining gates](docs/research/g2k-issue-110.md).
- [x] Resolve PR #145's merge with authorized default
  `5b7665981baafcb8c39b36f2222e20a6b196b22b`; preserve both runtime history and
  guarded-skip source. Leave the resolved merge staged, without committing.
- [ ] Publish the integrated issue #110 candidate through the orchestrator for
  native CI and trusted exact-head review. Commit/publication, reviewed merge,
  deployment, natural receipts and downstream recovery remain separate gates. Keep
  https://github.com/Khamel83/penny/issues/110 open with
  `g2k:acceptance-pending`. Refs #110.

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
