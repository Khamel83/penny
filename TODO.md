## Official-reference comparison complete — October 1, 2026

Owner authorized a bounded three-episode public reference check; the background cohort remains paused. Identical audio was recognized once per engine. Apple was about 5x faster, but normalized reference disagreement was 8.23% versus pinned shared Whisper 5.56%, higher for Apple on all three excerpts. Cosmetic/stutter sensitivity did not reverse the ranking; published text is edited and not independently adjudicated ground truth. No blanket switch: the requested accuracy condition is not met. Total Apple model RAM/energy remains unmeasured, and speaker labels/names/TTS are separate capabilities. Report: docs/research/2026-10-01-apple-reference-results.md. Next: adjudicate consequential existing disagreements or a separately authorized domain experiment; do not restart bulk recognition. GitHub #70 owns the conditional adoption gate. The research utility ran on the Mac; primary runtime and all delivery ownership are unchanged.

## Bounded public reference comparison — October 1, 2026

Owner authorized a few official-transcript comparisons and conditional Apple adoption if accuracy and resource acceptance support it. The background cohort remains paused. Isolated worktree research/apple-reference-check-20261001 starts from fetched e997211. Three first-party Lex audio/reference pairs are verified; scoring distinguishes transcript agreement from adjudicated accuracy. Artifacts stay local under /Volumes/2TB_SSD/penny-asr-reference-20261001. Next: prepare identical short clips, run deployed Apple binary and pinned shared Whisper as low-priority backfill, quantify reference edits and resource limits, then document the decision. Canonical capture/delivery remains unchanged.

## Apple pilot paused by owner — October 1, 2026

All 32 held Penny recordings completed (43.2 hours), plus seven historical Atlas and ten natural Atlas inputs. Owner stopped further recognition. Sidecar is unloaded, autostart plist retained with .paused suffix, live capture disabled and normal five-label runtime verified at ec0f51a. All canonical Penny baseline text/status pairs remain unchanged. Binary repetition flags are not accuracy measurements: Apple repeated-run token share was 0.285% versus Whisper 0.725%, and severe runs were fewer. No first-party or independent reference comparison has been performed. Next is evaluation of existing outputs against references and flagged context, not more transcription; issue #70 owns the conditional primary gate. See docs/apple-pilot-live-receipt-20261001.md.

Apple launchd correction resolved (October 1): PR #69 binds diskutil to /usr/sbin. Corrected source ec0f51a activated all six labels, fresh pilot health and optional live capture. All 40 historical cohort inputs were admitted without errors, and natural Atlas requests have produced private Apple/Whisper comparison receipts. The first activation failure did not affect canonical Whisper. See docs/apple-pilot-live-receipt-20261001.md for acceptance facts.

Apple pilot review fixes (October 1): live snapshot disk work now runs in at most two daemon admission threads; overflow is refused without waiting. Only committed queue rows prove durability. Subprocess launch/register is synchronized with shutdown, including signal re-entry. Regression tests cover stalled storage and shutdown races. Corrected activation and real cohort admission are verified; recognition-quality acceptance remains open.

## Apple workflow pilot — October 1, 2026

- [x] Inventory actual work: 32 quality-held Penny recordings with local audio; Atlas live queue two pending/two processing; 264 retained Atlas files are a historical corpus, not live backlog.
- [x] Implement opt-in real-request shadow capture, private bounded queue, two Apple sessions, native modern API, deadlines and source-bound deployment. Focused tests and trust check pass; real generated-audio pilot receipt completed locally.
- [x] Review and merge PR #68 plus launchd correction #69; deploy ec0f51a to all six labels, admit all 32 held Penny plus eight historical Atlas recordings, and verify fresh health and natural Atlas shadow completion. No canonical replacement or candidate delivery. See docs/apple-pilot-live-receipt-20261001.md.
- [x] Run bounded official-reference check with three public Lex clips; evidence and limits are in docs/research/2026-10-01-apple-reference-results.md.
- [ ] Adjudicate consequential reference disagreements / verify broader domain and total resource gate before conditional primary ownership (#70). Bulk recognition remains paused.
- [ ] Validate representative transcript quality, Atlas timing semantics and sustained total system memory before primary Apple ownership. See `docs/apple-speech-pilot.md`.

## Shared Whisper memory acceptance — September 30, 2026

- [x] Identify Penny ownership and implement unchanged-model cache retention fix with regression coverage.
- [x] Merge PR #62 and deploy `63591bed`; authenticated generated-speech canaries show stable 1.7 GiB post-request footprint and identical short-canary text hashes.
- [ ] Observe a natural Atlas/Penny completion and sustained busy-workload memory; no multi-day stability claim yet.
- [ ] Complete approved simulator deletion through Apple management path; protected internal assets remain.

## Current Voice Memo recovery — September 29, 2026

- [x] Merge and deploy the long live memo chunk path. PR #57 merged at `61f88908`; the installed Mac watcher reports that exact revision. Focused and hosted tests passed.
- [x] Recover exact failed Voice Memo PK 440 locally. Transcript row 769 is linked, routing suppressed, archived and included in a verified backup; there are zero Drop, Slack, quality-alert, or Maya delivery rows for it. Mac Doctor is `degraded`, with no current terminal source failure; supervised OCI Doctor receipt is also `degraded` and its service succeeds.
- [ ] Keep transcript row 769 in private `needs_review`: 15 of 19 chunks triggered consecutive-token repetition. Do not send it downstream on source recovery alone. Verify the next natural OCI health timer after this recovery.
- [x] Retire the queued public-repository `oci-dev` GitHub health workflow. PR #58 merged as `873f5be7` after hosted Python 3.11/3.12 CI and exact-head review; the merged-main CI passed. Historical queued Health Check run 36589491752 and AI Review run 36491923787 were canceled. The separate next natural OCI timer and Doctor readiness gates remain open above.

## Active synchronized task: Atlas/MinusPod shared-Whisper cutover

This Penny queue is synchronized with the Atlas execution authority at
`/Volumes/2TB_SSD/GitHub/atlas/.worktrees/minuspod-reliability-fix/docs/superpowers/plans/2026-09-17-shared-whisper-cutover-handover.md`.
The user authorized the live cutover. The Penny source is locally integrated
on `main` at `f6e531d7919d19e61b7a65d73f5073e39a23e4e3`.

- [x] Shared protocol, authenticated server, one-worker supervisor, worker
  isolation, Penny client, launchd template, and Doctor probe implemented.
- [x] Focused shared-Whisper suite after the timestamp change: `16 passed`,
  Ruff clean, and `python3 -m compileall -q shared_whisper` passed.
- [ ] Penny full suite is not fully green: `602 passed, 2 skipped, 1 failed`.
  The remaining failure is the pre-existing malformed RFC3339 timestamp
  contract test (`TranscriptContractTests.test_checked_maya_schema_uses_full_json_schema_and_format_validation`).
- [x] Merge the validated source into local Penny `main` without pushing.
- [x] Render and back up the `com.penny.shared-whisper` plist with the
  internal token supplied only through the local runtime configuration.
- [x] Capture source/runtime/process/memory evidence, replace the old
  `com.atlas.minuspod-whisper` owner on port 10311, and preserve rollback.
- [x] Verify authenticated MagicDNS health, one worker at most, pinned model
  identity, SSD temp state, and unchanged `com.wyoming.whisper`.
- [x] Disable shared-Whisper word timestamps by default; explicit
  `word_timestamps=true` remains supported. Live idle memory after restart:
  33.3M physical footprint with zero loaded model workers.
- [x] Keep Penny's quality retry path and Atlas's whole-chunk retry path
  separate from process liveness; record durable and downstream receipts in
  the synchronized Atlas cutover receipt.
- [x] Observe one current MinusPod episode through durable finalization: one
  post-cutover processing-history row completed at `2026-09-18T03:52:05Z`,
  with zero post-cutover Whisper-unreachable or generic worker-error rows.
- [x] Run the tracked non-private Penny canary against the local shared owner;
  it returned HTTP 200 with nonempty validated metadata and the pinned model.
- [ ] Continue observing the remaining repaired backlog; the live queue at
  2026-09-18T19:31 PDT was 55 completed, 22 pending, and 1 processing. The
  episode interrupted during restart completed durably with 2 review markers.
- [x] Atlas overlay `91ce1f08` makes shared-Whisper chunk failures fail closed
  instead of returning a partial transcript; Homelab image `2.96.24` is
  built and deployed, with the patched source verified in the container.
- [x] Keep rollback artifacts ready and synchronize this TODO/HANDOFF with
  Atlas after this bounded task. A live Penny-preemption contention receipt
  remains explicitly unexercised because no real Penny capture arrived.
- [ ] Exercise rollback in a disposable or separately approved maintenance
  window; do not disturb the healthy production owner solely to create proof.

The stale Phase A items below are historical generated signals. They do not
override this active shared-Whisper cutover queue.

<!-- janitor:begin:todo -->
## Shared Whisper memory acceptance — September 30, 2026

- [x] Identify Penny ownership and implement unchanged-model cache retention fix with regression coverage.
- [x] Merge PR #62 and deploy `63591bed23f86347a3cf73d7db27a395d9d49836`; authenticated generated-speech canaries show stable 1.7 GiB post-request footprint and identical short-canary text hashes.
- [ ] Observe a natural Atlas/Penny completion and sustained busy-workload memory; no multi-day stability claim yet.
- [ ] Complete approved simulator deletion through the Apple management path; 14.8 GiB remains behind protected internal assets. Recovery is the next coordinated step.

## Current Voice Memo recovery — September 29, 2026

- [x] Merge and deploy the long live memo chunk path. PR #57 merged at `61f88908d7693fbac4c4c11fd48ffef2bdf0384f`; the installed Mac watcher reports that exact revision. Focused and hosted tests passed.
- [x] Recover exact failed Voice Memo PK 440 locally. Transcript row 769 is linked, routing suppressed, archived and included in a verified backup; there are zero Drop, Slack, quality-alert, or Maya delivery rows for it. Mac Doctor is `degraded`, with no current terminal source failure; supervised OCI Doctor receipt is also `degraded` and its service succeeds.
- [ ] Keep transcript row 769 in private `needs_review`: 15 of 19 chunks triggered consecutive-token repetition. Do not send it downstream on source recovery alone. Verify the next natural OCI health timer after this recovery.
- [x] Retire the queued public-repository `oci-dev` GitHub health workflow. PR #58 merged as `873f5be7efded2210339198fd3ae1aaf61f29e6a` after hosted Python 3.11/3.12 CI and exact-head review; the merged-main CI passed. Historical queued Health Check run 36589491752 and AI Review run 36491923787 were canceled.

## Active synchronized task: Atlas/MinusPod shared-Whisper cutover

This Penny queue is synchronized with the Atlas execution authority at
`/Volumes/2TB_SSD/GitHub/atlas/.worktrees/minuspod-reliability-fix/docs/superpowers/plans/2026-09-17-shared-whisper-cutover-handover.md`.
The user authorized the live cutover. The Penny source is locally integrated
on `main` at `f6e531d7919d19e61b7a65d73f5073e39a23e4e3`.

- [x] Shared protocol, authenticated server, one-worker supervisor, worker isolation, Penny client, launchd template, and Doctor probe implemented.
- [x] Focused shared-Whisper suite after the timestamp change: `16 passed`, Ruff clean, and `python3 -m compileall -q shared_whisper` passed.
- [ ] Penny full suite is not fully green: `602 passed, 2 skipped, 1 failed`. The remaining failure is the pre-existing malformed RFC3339 timestamp contract test (`TranscriptContractTests.test_checked_maya_schema_uses_full_json_schema_and_format_validation`).
- [x] Merge the validated source into local Penny `main` without pushing.
- [x] Render and back up the `com.penny.shared-whisper` plist with the internal token supplied only through the local runtime configuration.
- [x] Capture source/runtime/process/memory evidence, replace the old `com.atlas.minuspod-whisper` owner on port 10311, and preserve rollback.
- [x] Verify authenticated MagicDNS health, one worker at most, pinned model identity, SSD temp state, and unchanged `com.wyoming.whisper`.
- [x] Disable shared-Whisper word timestamps by default; explicit `word_timestamps=true` remains supported. Live idle memory after restart: 33.3M physical footprint with zero loaded model workers.
- [x] Keep Penny's quality retry path and Atlas's whole-chunk retry path separate from process liveness; record durable and downstream receipts in the synchronized Atlas cutover receipt.
- [x] Observe one current MinusPod episode through durable finalization: one post-cutover processing-history row completed at `2026-09-18T03:52:05Z`, with zero post-cutover Whisper-unreachable or generic worker-error rows.
- [x] Run the tracked non-private Penny canary against the local shared owner; it returned HTTP 200 with nonempty validated metadata and the pinned model.
- [ ] Continue observing the remaining repaired backlog; the live queue at `2026-09-18T19:31 PDT` was 55 completed, 22 pending, and 1 processing. The episode interrupted during restart completed durably with 2 review markers.
- [x] Atlas overlay `91ce1f08` makes shared-Whisper chunk failures fail closed instead of returning a partial transcript; Homelab image `2.96.24` is built and deployed, with the patched source verified in the container.
- [x] Keep rollback artifacts ready and synchronize this TODO/HANDOFF with Atlas after this bounded task. A live Penny-preemption contention receipt remains explicitly unexercised because no real Penny capture arrived.
- [ ] Exercise rollback in a disposable or separately approved maintenance window; do not disturb the healthy production owner solely to create proof.

The stale Phase A items below are historical generated signals. They do not override this active shared-Whisper cutover queue.

## OCI GitHub worker path — 2026-09-29

- [x] Retire the queued legacy `oci-ts` AI Review workflow after exact-head review. The separate OCI reviewer handled Penny PR #53, and PR #54 merged the retirement as `37f338e355b9ee05983b3d46f12ec9e9270df6e7`.
- [x] Retire the unmatched public-repository `oci-dev` health workflow. PR #58 merged as `873f5be7efded2210339198fd3ae1aaf61f29e6a`; the queued GitHub runs were canceled. The OCI `macmini` SSH alias is verified separately.
- [x] Align native runtime with reviewed main `ce48505f1f2e81a924443e5cf878e41dd761fb46`: controlled deployment, verified backup, five loaded revisions and follow-up current check passed September 30. `/ready` reports the same revision and remains degraded.
- [ ] Restore and prove the natural OCI Doctor schedule. A direct OCI-to-Mac Doctor run previously returned `unready` (`launchd_unavailable`, Voice Memos `terminal_failure`); later supervised OCI Doctor evidence was degraded but successful. Do not call the path healthy without the next natural timer receipt.
- [ ] Verify Homelab's corrected Penny monitoring observes real Doctor/readiness degradation and the next natural OCI Doctor receipt; source alignment alone does not close health or downstream delivery acceptance.
<!-- janitor:end:todo -->
## OCI GitHub worker path — 2026-09-29

- [ ] Retire the queued legacy `oci-ts` AI Review workflow after exact-head
  review. The separate OCI reviewer handled Penny PR #53; the old lane is
  retired. Its issue-triage job has no replacement receipt here.
- [ ] Move the scheduled Mac Doctor check off its unmatched public-repository
  `oci-dev` runner label. OCI's SSH alias now reaches the Mac with a verified
  host key, but GitHub run 36457387408 remains queued. A direct OCI-to-Mac
  Doctor run returned `unready` (`launchd_unavailable`, Voice Memos
  `terminal_failure`); restore the Doctor path and prove a natural schedule
  before calling it healthy.
- [x] Align native runtime with reviewed main `ce48505f`: controlled deployment,
  verified backup, five loaded revisions and follow-up current check passed
  September 30. `/ready` reports the same revision and remains degraded.
- [ ] Verify Homelab's corrected Penny monitoring observes real Doctor/readiness
  degradation and the next natural OCI Doctor receipt; source alignment alone
  does not close health or downstream delivery acceptance.
