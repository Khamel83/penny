# Voice Memos Sync Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Penny recover and truthfully report the missing Voice Memos sync daemon that caused three recordings to remain invisible until the user opened the app.

**Architecture:** Add one bounded daemon probe/recovery seam to `watcher.py`, project the evidence through the existing health receipt, and consume it in Doctor readiness. Keep Apple's database read-only and preserve the existing app responsiveness state machine.

**Tech Stack:** Python 3.11, launchd/`launchctl`, pytest/unittest, SQLite read-only source evidence.

## Global Constraints

- Never write to Apple's Voice Memos database or create a synthetic personal recording.
- Never print recording names, transcript bodies, credentials, or private identifiers.
- Use `launchctl kickstart` without `-k`; never kill a responsive sync daemon.
- Do not foreground Voice Memos as part of this repair.
- Follow RED-GREEN TDD and keep the live checkout untouched until review passes.

---

### Task 1: Sync daemon recovery and watcher health

**Files:**
- Modify: `watcher.py`
- Test: `tests/test_watcher.py`

**Interfaces:**
- Produces: `_voicememos_sync_daemon_running() -> bool`
- Produces: watcher health field `voicememod_running:0|1`

- [ ] **Step 1: Write failing tests**

Add tests proving a responsive app with no `voicememod` invokes exactly
`launchctl kickstart gui/<uid>/com.apple.voicememod` before the existing
background open, while an already-running daemon does not invoke kickstart.
Add health tests proving `voicememod_running:0` forces `watcher_ok:0` and `1`
permits the existing healthy case.

- [ ] **Step 2: Verify RED**

Run:
`PYTHONPATH=. /Users/macmini/penny/venv/bin/python -m pytest -q tests/test_watcher.py -k 'voicememod or sync_is_refreshed or health_check'`

Expected: failures because the daemon probe and receipt field do not exist.

- [ ] **Step 3: Implement the minimal recovery**

Use `pgrep -x voicememod` for the probe. When absent, run
`launchctl kickstart gui/{os.getuid()}/com.apple.voicememod` with bounded timeout,
captured output, and class/exit-only logging. Preserve `open -g -a VoiceMemos`.
Add the bounded health field and require it for `watcher_ok`.

- [ ] **Step 4: Verify GREEN**

Run the Task 1 focused command and then
`PYTHONPATH=. /Users/macmini/penny/venv/bin/python -m pytest -q tests/test_watcher.py`.

Expected: all watcher tests pass.

### Task 2: Doctor readiness projection

**Files:**
- Modify: `doctor.py`
- Test: `tests/test_doctor.py`

**Interfaces:**
- Consumes: watcher health field `voicememod_running`
- Produces: `source_unavailable` when daemon evidence is false or missing

- [ ] **Step 1: Write failing tests**

Extend ready fixtures with `voicememod_running=True`. Add a test whose otherwise
healthy watcher receipt has `voicememod_running:0`; assert both `voice_memos` and
`services` infer `source_unavailable`.

- [ ] **Step 2: Verify RED**

Run:
`PYTHONPATH=. /Users/macmini/penny/venv/bin/python -m pytest -q tests/test_doctor.py -k 'source or voicememo'`

Expected: failure because Doctor ignores the daemon flag.

- [ ] **Step 3: Implement the projection**

Add `voicememod_running` to safe/required detail keys, read it from the watcher
health file in both probes, and require it alongside responsiveness/database
evidence in `voice_memos` and `services` inference.

- [ ] **Step 4: Verify GREEN**

Run the Task 2 focused command and then
`PYTHONPATH=. /Users/macmini/penny/venv/bin/python -m pytest -q tests/test_doctor.py`.

Expected: all Doctor tests pass.

### Task 3: Full verification and review

**Files:**
- Verify all changed files and repository tests.

- [ ] **Step 1: Run complete gates**

Run the focused suites, full `pytest -q`, `scripts/trust_check.py`, targeted Ruff,
PyCompile, and `git diff --check` with the repository venv.

- [ ] **Step 2: Independent review**

Review the frozen diff for command safety, fail-closed health semantics, secret
hygiene, and regression coverage. Correct all Critical/Important findings.

- [ ] **Step 3: Commit explicit paths**

Commit only the design/plan, `watcher.py`, `doctor.py`, and their tests. Verify a
clean worktree and exact commit paths.
