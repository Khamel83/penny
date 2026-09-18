## Active synchronized task: Atlas/MinusPod shared-Whisper cutover

This Penny queue is synchronized with the Atlas execution authority at
`/Volumes/2TB_SSD/GitHub/atlas/.worktrees/minuspod-reliability-fix/docs/superpowers/plans/2026-09-17-shared-whisper-cutover-handover.md`.
The user authorized the live cutover. The Penny source is isolated on branch
`feat/shared-whisper-preemption` at
`33a4843bd4c34b99059cd8a51f0a8fd930201a3d`.

- [x] Shared protocol, authenticated server, one-worker supervisor, worker
  isolation, Penny client, launchd template, and Doctor probe implemented.
- [x] Penny focused suite: `176 passed, 7 subtests passed`.
- [ ] Merge the validated source into local Penny `main` without pushing.
- [ ] Render and back up the `com.penny.shared-whisper` plist with the
  internal token supplied only through the local runtime configuration.
- [ ] Capture source/runtime/process/memory evidence, then replace the old
  `com.atlas.minuspod-whisper` owner on port 10311 at the final safe moment.
- [ ] Verify authenticated MagicDNS health, one worker at most, pinned model
  identity, SSD temp state, and unchanged `com.wyoming.whisper`.
- [ ] Keep Penny's quality retry path and Atlas's whole-chunk retry path
  separate from process liveness; record durable and downstream receipts.
- [ ] Keep rollback ready and synchronize this TODO/HANDOFF with Atlas after
  every bounded task.

The stale Phase A items below are historical generated signals. They do not
override this active shared-Whisper cutover queue.

<!-- janitor:begin:todo -->
## TODO

_No published TODO.md content was available at commit 8372fb65 (all managed and unmanaged content removed), so these items are inferred from commit subjects only and are not confirmed open work._

- [ ] Confirm whether the Voice Memos sync daemon health scoping (`1e01fd4`), readiness exposure (`c8c5e9d`), missing-daemon recovery (`058adce`), and post-quality-policy recovery (`d194e9c`) fully cover remaining recovery paths.
- [ ] Verify reentrancy/race safety for quality review promotion (`1c1fe32`) and Phase A source and receipt handling (`0b92686`, `0bafa88`).
- [ ] Validate that Apple effect reconciliation is fail-closed in all paths (`d8298ac`) while the narrow natural no-emphasis allowance (`5f9609e`) does not weaken it.
- [ ] Confirm watcher operational log redaction (`a4e00a3`) and fresh source health evidence requirements (`b22adcc`) are complete across watchers.
- [ ] Check whether the three ai-review workflow updates (`e03f646`, `b8b6521`, `eb27440`) are cumulative, and whether the workflow is in its intended final state.
- [ ] Follow up on the foundational agent tooling standardization (`1627376`) to identify any remaining documentation or tooling gaps.

Uncertainty: without TODO.md contents, diffs, or issue data, none of the above can be confirmed as an outstanding, owned, or assigned task.
<!-- janitor:end:todo -->
