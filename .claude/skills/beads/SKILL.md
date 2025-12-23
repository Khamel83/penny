---
name: beads
description: "Git-backed persistent task tracking with dependencies. Use when user says 'beads', 'ready tasks', 'dependencies', 'blockers', or needs cross-session memory."
allowed-tools: Bash, Read, Write, Edit, Glob
---

# Beads Task Tracker

You are an expert at using beads for persistent, git-backed task management with dependency tracking.

## When To Use

- User says "beads", "ready tasks", "what's next", "next task"
- User needs cross-session task persistence
- User wants dependency tracking between tasks
- Multi-agent coordination is needed
- Before/after handoffs to sync persistent state
- User says "blockers", "blocked by", "dependencies"

## Inputs

- Task descriptions and priorities
- Dependency relationships between tasks
- Status updates (open, in_progress, closed)

## Outputs

- Persisted tasks in `.beads/` directory
- Ready task lists (unblocked work)
- Dependency graphs
- Synced state with git

## Why Beads (Not Just TODO.md)

| Aspect | TODO.md | Beads |
|--------|---------|-------|
| Persistence | Session | Git-backed |
| Dependencies | None | Full graph |
| Multi-agent | Conflicts | Hash IDs |
| Ready detection | Manual | `bd ready` |
| Survives /clear | No | Yes |
| Survives session | No | Yes |

**Rule**: Use TODO.md for immediate visibility. Use beads for persistent state.

## Workflow

### 1. Session Start

```bash
# Pull latest state
bd sync

# See what's ready (no blockers)
bd ready --json

# Pick highest priority task
bd update <id> --status in_progress --json
```

Update TODO.md with current task for visibility.

### 2. During Work

**Create new tasks discovered during work:**
```bash
bd create "Task title" -p 1 -t task --json
```

**Add dependencies when tasks block each other:**
```bash
bd dep add <child-id> <parent-id> --type blocks
```

**Complete tasks:**
```bash
bd close <id> --reason "Completed" --json
```

### 3. Session End

```bash
# CRITICAL: Push all changes before ending
bd sync
```

Create handoff if needed - beads state persists regardless.

## Core Commands

### Check Ready Tasks
```bash
bd ready --json
```
Returns tasks with no open blockers. Start here each session.

### Create Tasks
```bash
bd create "Task title" -p 1 -t task --json
bd create "Bug description" -p 0 -t bug --json
bd create "Feature request" -p 2 -t feature --json
bd create "Epic name" -t epic --json
```

Priority: 0=critical, 1=high, 2=normal, 3=low, 4=backlog

### Manage Dependencies
```bash
# Child blocked until parent closes
bd dep add <child-id> <parent-id> --type blocks

# View dependency tree
bd dep tree <id>
```

### Update Status
```bash
bd update <id> --status in_progress --json
bd update <id> --status open --json
bd close <id> --reason "Completed" --json
```

### View Tasks
```bash
bd show <id> --json
bd list --status open --json
bd list --status in_progress --json
```

### Sync (Critical!)
```bash
bd sync
```
Forces immediate export/commit/push. ALWAYS run before session end.

## Integration with TODO.md

Keep TODO.md in sync for immediate visibility:

```markdown
# TODO

## From Beads (bd ready)
- [ ] bd-a1b2: Implement auth endpoint (p1)
- [ ] bd-f4c3: Add login tests (p2)

## Session Tasks
- [ ] Current step: Write login handler
```

## Multi-Agent Coordination

Beads prevents conflicts via hash-based IDs (bd-xxxx format).

### Task Claiming
```bash
# Agent claims a task
bd update <id> --status in_progress --json
bd sync  # Others see the claim immediately
```

### Parallel Work
```bash
# Agent A creates bd-a1b2
# Agent B creates bd-f4c3
# No collision - different hash IDs
```

### Discovery Pattern
```bash
# Found sub-task during implementation
bd create "Sub-task" --deps parent:<parent-id> -p 2 --json
bd sync
```

### Agent Handover
```bash
# Agent A ending
bd close <id> --reason "Completed auth endpoint"
bd sync

# Agent B starting
bd sync
bd ready --json
```

## Handoff Integration

### Before create-handoff
```bash
bd sync  # Push all changes
```

Include in handoff document:
- In-progress tasks
- Ready tasks
- Blocked tasks with blockers

### After resume-handoff
```bash
bd sync  # Pull latest
bd ready --json  # See available work
```

## Common Patterns

### Breaking Down Work
```bash
# Create epic
bd create "User Authentication" -t epic --json
# Returns bd-a1b2

# Create child tasks
bd create "Login endpoint" --deps parent:bd-a1b2 -p 1 --json
bd create "Logout endpoint" --deps parent:bd-a1b2 -p 1 --json
bd create "Password reset" --deps parent:bd-a1b2 -p 2 --json
```

### Tracking Blockers
```bash
# Found a blocker
bd create "Need API key from user" -t blocker -p 0 --json
# Returns bd-x1y2

# Link current task as blocked
bd dep add <current-task> bd-x1y2 --type blocks
```

### Initialize in New Project
```bash
bd init --stealth  # Keeps .beads/ local to you
```

## Anti-Patterns

- Creating beads issues for trivial tasks (use TODO.md instead)
- Forgetting `bd sync` before session end
- Not using `--json` flag for structured output
- Creating dependencies on closed issues
- Over-engineering dependency graphs for simple work

## Beads vs Handoffs

| Need | Use |
|------|-----|
| Save session context | `create-handoff` |
| Track persistent tasks | `beads` |
| Resume after /clear | `resume-handoff` + `bd sync` |
| Multi-agent task handoff | `beads` with sync |

## Installation

Beads is optional but required for persistent features:

```bash
npm install -g @beads/bd
# or
brew install steveyegge/beads/bd
# or
go install github.com/steveyegge/beads/cmd/bd@latest
```

## Keywords

beads, tasks, ready, dependencies, blockers, persistent, cross-session, bd ready, bd create, bd sync, bd close, bd update, bd dep, multi-agent
