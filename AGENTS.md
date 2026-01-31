<!-- FOR CLAUDE - NOT FOR HUMANS -->
<!-- Humans: See README.md for setup, INDEX.md for skill reference -->

# ONE_SHOT v8

> **UPDATE CHECK**: Run: `curl -sL https://raw.githubusercontent.com/Khamel83/oneshot/master/upgrade-v8.sh | bash`

> **v8 = ULTRA-COMPRESSED** - 2k system tokens (down from 20k). All prose → JSON.

> **Context is the scarce resource.** Delegate aggressively, parallelize always, write state to disk.

---

## SKILL ROUTER (15 Core Skills)

```yaml
skill_router:
  # Entry
  - pattern: "new project|build me|help me|/interview|/front-door"
    skill: front-door

  # Interview Depth Overrides
  - pattern: "/full-interview|full interview mode"
    skill: full-interview
    note: "Forces all 13+ questions, no bypass"

  - pattern: "/quick-interview|quick interview mode"
    skill: quick-interview
    note: "Only Q1, Q2, Q6, Q12 with smart defaults"

  - pattern: "/smart-interview|reset interview"
    skill: smart-interview
    note: "Reset to auto-detect depth (default)"

  # Autonomous (headless mode)
  - pattern: "autonomous|headless|background|overnight|just build it"
    skill: autonomous-builder

  # Planning
  - pattern: "plan|design|how should|what's the approach"
    skill: create-plan

  - pattern: "implement|execute|build it|run the plan"
    skill: implement-plan

  # Task Tracking (persistent)
  - pattern: "beads|ready tasks|what's next|next task|blockers|dependencies"
    skill: beads

  # Quality
  - pattern: "bug|error|fix|debug|broken|not working"
    skill: debugger

  - pattern: "review|check code|is this safe|pr review"
    skill: code-reviewer

  # Lessons Learned (NEW)
  - pattern: "oops|save this mistake|remember this|lessons learned|/lessons"
    skill: oops

  # Parallel Execution (NEW in v7.4)
  - pattern: "validate|check everything|run all checks|pre-commit"
    skill: parallel-validator

  - pattern: "rename across|update all|batch|bulk|mass update"
    skill: batch-processor

  # Context Management
  - pattern: "handoff|save context|before clear|context low"
    skill: create-handoff

  - pattern: "resume|continue|pick up|from handoff"
    skill: resume-handoff

  # Recovery & Thinking
  - pattern: "stuck|looping|confused|start over"
    skill: failure-recovery

  - pattern: "think|ultrathink|super think|mega think"
    skill: thinking-modes

  # Secrets
  - pattern: "secrets|env|credentials|api key"
    skill: secrets-vault-manager

  # Skills Discovery
  - pattern: "browse skills|skillsmp|find skills|skill marketplace"
    skill: skillsmp-browser

  # Maintenance
  - pattern: "/update|update oneshot|upgrade oneshot|check version"
    skill: auto-updater
```

**All other skills**: Available on-demand via `/skill-name` or explicit request. See INDEX.md.

---

## AUTO-DELEGATION (v7.4)

**CRITICAL**: These fire AUTOMATICALLY without user request.

```yaml
auto_delegation:
  # File count triggers (>5 files → delegate)
  - signal: "Glob/Grep returning >5 files"
    action: "Spawn Explore agent, return summary only"

  # Duration triggers (>15s → background)
  - signal: "npm|pytest|docker|build command"
    action: "run_in_background: true"

  # Security triggers (auto-audit)
  - signal: "Editing auth/secrets/credentials files"
    action: "Spawn security-auditor in background"

  # Context triggers (pre-emptive)
  - signal: "Context >30% + complex task"
    action: "Delegate exploration to subagent"
  - signal: "Context >50%"
    action: "Create handoff, delegate remaining"
```

**Key change from v7.3:** Bias toward delegation. Don't wait for user to say "background".

---

## RESILIENT EXECUTION (v7.4)

**All long-running work runs in tmux** - survives terminal disconnect.

```yaml
resilience:
  # Default: All builds use tmux
  - command: "oneshot-build"
    mode: tmux_session
    heartbeat: 30s
    checkpoint: 5m

  # Aggressive state sync
  - trigger: "task status change"
    action: "bd sync immediately"
  - trigger: "file committed"
    action: "bd sync"
  - trigger: "every 5 minutes"
    action: "checkpoint commit + bd sync"

  # Recovery
  - on_disconnect: "work continues in tmux"
  - on_reconnect: "tmux attach -t oneshot-*"
  - on_crash: "bd sync && bd ready to resume"
```

**Key principle:** If terminal dies, work continues. If work dies, state is recoverable.

---

## CONTEXT MANAGEMENT

### Task Groups (3-5 tasks each)
```
Plan has N tasks → Create beads tasks with dependencies
Execute one group → bd update status → Check context
If context > 50% → Pause, bd sync, suggest /compact
After /compact → bd ready shows exactly what's next
```

### Beads = Persistent State
All task progress tracked via beads (survives /clear, /compact, sessions):
```bash
bd ready --json     # What's next?
bd update <id> --status in_progress
bd close <id> --reason "commit: abc123"
bd sync             # Always sync before session end
```

### Pre-Implementation Flow
```
If context > 30% before implement-plan:
  → bd sync (save current state)
  → Suggest /compact first
```

---

## FILE HIERARCHY

| Priority | File | Purpose |
|----------|------|---------|
| 1 | CLAUDE.md | Project-specific rules |
| 2 | AGENTS.md | This file (skill routing) |
| 3 | `.beads/` | Persistent task state (bd ready) |
| 4 | TODO.md | Session visibility |

---

## THINKING MODES

| Trigger | Depth |
|---------|-------|
| "think" | Quick check |
| "think hard" | Trade-offs |
| "ultrathink" | Architecture |
| "super think" | System design |
| "mega think" | Strategic |

---

## PHILOSOPHY

> "It's harder to read code than to write it." — Joel Spolsky

**NEVER rewrite from scratch.** Extend, refactor, use existing solutions.

**USER TIME IS PRECIOUS. AGENT COMPUTE IS CHEAP.**
Ask ALL questions UPFRONT. Get ALL info BEFORE coding.

---

## RESET

Say `(ONE_SHOT)` to re-anchor to these rules.

---

**Version**: 8.0 | **System Tokens**: ~2k (down from 20k) | **Core Skills**: 10 | **Context**: Ultra-compressed JSON
