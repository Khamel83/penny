## Active synchronized task: Atlas/MinusPod shared-Whisper cutover

This Penny queue is synchronized with the Atlas execution authority at
`/Volumes/2TB_SSD/GitHub/atlas/.worktrees/minuspod-reliability-fix/docs/superpowers/plans/2026-09-17-shared-whisper-cutover-handover.md`.
The user authorized the live cutover. The Penny source is locally integrated
on `main` at `8e53c102065db2ebb9ce7ee7f56c562a4ee63180`.

- [x] Shared protocol, authenticated server, one-worker supervisor, worker
  isolation, Penny client, launchd template, and Doctor probe implemented.
- [x] Penny full suite: `602 passed, 2 skipped, 50 subtests passed`.
- [x] Merge the validated source into local Penny `main` without pushing.
- [x] Render and back up the `com.penny.shared-whisper` plist with the
  internal token supplied only through the local runtime configuration.
- [x] Capture source/runtime/process/memory evidence, replace the old
  `com.atlas.minuspod-whisper` owner on port 10311, and preserve rollback.
- [x] Verify authenticated MagicDNS health, one worker at most, pinned model
  identity, SSD temp state, and unchanged `com.wyoming.whisper`.
- [x] Keep Penny's quality retry path and Atlas's whole-chunk retry path
  separate from process liveness; record durable and downstream receipts in
  the synchronized Atlas cutover receipt.
- [x] Observe one current MinusPod episode through durable finalization: one
  post-cutover processing-history row completed at `2026-09-18T03:52:05Z`,
  with zero post-cutover Whisper-unreachable or generic worker-error rows.
- [x] Run the tracked non-private Penny canary against the local shared owner;
  it returned HTTP 200 with nonempty validated metadata and the pinned model.
- [ ] Continue observing the remaining repaired backlog; current queue is 27
  completed, 38 pending, 1 processing, and 9 known terminal failures.
- [x] Keep rollback artifacts ready and synchronize this TODO/HANDOFF with
  Atlas after this bounded task. A live Penny-preemption contention receipt
  remains explicitly unexercised because no real Penny capture arrived.
- [ ] Exercise rollback in a disposable or separately approved maintenance
  window; do not disturb the healthy production owner solely to create proof.

The stale Phase A items below are historical generated signals. They do not
override this active shared-Whisper cutover queue.

<!-- janitor:begin:todo -->
## TODO

- [ ] Confirm whether the Voice Memos sync daemon health scoping (`1e01fd4`), readiness exposure (`c8c5e9d`), missing-daemon recovery (`058adce`), and post-quality-policy recovery (`d194e9c`) fully cover remaining recovery paths.
- [ ] Verify reentrancy/race safety for quality review promotion (`1c1fe32`) and Phase A source and receipt handling (`0b92686`, `0bafa88`).
- [ ] Validate that Apple effect reconciliation is fail-closed in all paths (`d8298ac`) while the narrow natural no-emphasis allowance (`5f9609e`) does not weaken it.
- [ ] Confirm watcher operational log redaction (`a4e00a3`) and fresh source health evidence requirements (`b22adcc`) are complete across watchers.
- [ ] Check whether the three ai-review workflow updates (`e03f646`, `b8b6521`, `eb27440`) are cumulative, and whether the workflow is in its intended final state.
- [ ] Follow up on the foundational agent tooling standardization (`1627376`) to identify any remaining documentation or tooling gaps.
- [x] Define shared Whisper protocol and deploy killable service supervisor (`525456f`, `33a4843`).
- [x] Filter shared Whisper worker options and isolate tiny Wyoming from owner guard and Doctor blocker (`d0afcfc`, `cea41ff`, `8e53c10`).
- [x] Record shared Whisper live cutover state and separate source and receipt revisions (`7025c53`, `d7d9a0d`, `7cbf7ae`).
- [x] Implement `github_deliveries` ledger table, claim/mark functions, and lease recovery test coverage (`183d884`, `1715f5b`).
- [x] Route project notes to GitHub delivery outbox with Slack thread-reply signal and Doctor triage probe (`73c75c7`, `6ddec6c`, `db78378`, `2201ea3`, `7c57e9f`, `1cd2526`, `fc4bc18`).
- [x] Rate-limit and drain GitHub delivery outbox in watcher ingest pass (`b0cf690`, `fbb6700`, `9c0ee29`).
- [ ] Exercise live Penny-preemption contention against the shared Whisper service when a real Penny capture arrives.
- [ ] Validate runtime `GH_TOKEN` substitution in launchd watcher configuration to avoid breaking `gh auth` (`81811a8`, `5444181`).
- [ ] Exercise shared Whisper rollback in an approved maintenance window without disturbing the healthy production owner.
- [ ] Monitor observation and completion of remaining backlog items in the shared Whisper cutover queue.
<!-- janitor:end:todo -->
