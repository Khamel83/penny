---
name: oneshot-core
description: "The $0 AI Build System. Handles triage, questions, PRD generation, and autonomous build execution. Use when starting new projects, when user says 'utilize agents.md', 'new project', 'build me', 'create', or '(ONE_SHOT)'."
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# ONE_SHOT Core

You are executing the ONE_SHOT build system - a methodology for autonomous project development.

## Prime Directive

USER TIME IS PRECIOUS. AGENT COMPUTE IS CHEAP.
Ask ALL questions UPFRONT. Get ALL info BEFORE coding.
User walks away after: "PRD approved. Execute autonomous build."

## When To Use

- User says "new project", "build me", "create", "start fresh"
- User says "utilize agents.md" or "(ONE_SHOT)"
- TRIAGE intent = build_new
- Empty or minimal repository detected

## Triage (First 30 Seconds)

Before doing ANYTHING, classify the user's intent:

| Intent | Signals | Action |
|--------|---------|--------|
| **build_new** | "new project", "build me", "create" | Full ONE_SHOT flow |
| **fix_existing** | "broken", "bug", "error" | Use `debugger` skill |
| **continue_work** | "continue", "resume" | Use `resume-handoff` skill |
| **modify_existing** | "add feature", "change" | Scope check → mini-PRD |
| **understand** | "explain", "how does" | Research only |
| **quick_task** | "just", "quickly" | Micro mode |

**Triage Output:**
```
Intent: [type] | Scope: [micro/small/medium/large] | Flow: [Full/Mini/Direct/Research]
Next: [specific next step]
```

## Thinking Depth by Phase

| Phase | Default | Ultrathink When |
|-------|---------|-----------------|
| Triage | Standard | Unclear intent, mixed signals |
| Questions | Standard | User gives conflicting answers |
| PRD Generation | Ultrathink | Always - architecture matters |
| Build Loop | Standard | Hard stop triggers |
| Handoff | Ultrathink | Always - context preservation |

## Mode Selection (Q0)

| Mode | Trigger | Questions | Output |
|------|---------|-----------|--------|
| **Micro** | <100 lines, "quick script" | Q1, Q11 only | Single file |
| **Tiny** | Single CLI, no services | Skip web/AI | CLI/script |
| **Normal** | CLI or simple web/API | Full questions | Standard project |
| **Heavy** | Multi-service, AI agents | Full + AI questions | Multi-service |

## Core Questions (Ask UPFRONT in ONE Message)

| ID | Key | Required | Smart Default |
|----|-----|----------|---------------|
| **Q0** | Mode | Yes | - |
| **Q1** | What are you building? | Yes | - |
| **Q2** | What problem does this solve? | Yes | - |
| Q2.5 | Reality check | If non-default | - |
| Q3 | Philosophy (3-6 bullets) | If non-default | "Simplicity first" |
| **Q4** | Features (3-7 items) | Yes | - |
| Q5 | Non-goals | If non-default | - |
| **Q6** | Project type (CLI/Web/API/etc) | Yes | - |
| Q7 | Data shape (examples) | If non-default | From Q1 context |
| Q8 | Data scale (A/B/C) | If non-default | A (Small) |
| Q9 | Storage (files/SQLite/Postgres) | If non-default | SQLite |
| Q10 | Dependencies | If non-default | "You decide" |
| Q11 | Interface shape | If non-default | From Q6 |
| **Q12** | Done criteria / v1 scope | Yes | - |
| Q13 | Naming | If non-default | From Q1 |

**Project Types (Q6):**
- A. CLI Tool
- B. Python Library
- C. Web Application
- D. Data Pipeline
- E. Background Service
- F. AI-Powered Web App
- G. Static / Landing Page

## Build Loop

After "PRD approved. Execute autonomous build.":

```
for each task in PRD:
  1. implement(task)
  2. test(task)        # Auto-run tests
  3. if fails: fix → retry (max 3)
  4. commit(task)      # Conventional commits
  5. update TODO.md    # ALWAYS
```

## Hard Stops (Require Explicit Approval)

- Storage upgrade (files → SQLite → Postgres)
- Auth method changes
- Production deployment changes
- External API integration
- Data deletion operations
- Schema migrations

**Action:** STOP → Present prompt → Wait for approval → Log decision

## Project Invariants

Every ONE_SHOT project MUST have:
- `README.md` - one-line description, current tier, upgrade trigger, quick start (≤5 commands)
- `TODO.md` - task tracking (kanban-style: Backlog/In Progress/Done ✓)
- `LLM-OVERVIEW.md` - complete project context for any LLM
- `PRD.md` - approved requirements document
- `scripts/` - setup.sh, start.sh, stop.sh, status.sh
- `/health` endpoint (if service) with /metrics
- Storage tier documented with upgrade trigger
- No PostgreSQL without explicit approval for small/medium data

## Storage Progression

| Tier | When | Records | Upgrade Trigger |
|------|------|---------|-----------------|
| Files (YAML/JSON) | Default | <1K | Need querying |
| SQLite | Most projects | <100K | Multi-user or heavy writes |
| PostgreSQL | Only when needed | 100K+ | Explicit approval required |

## Deployment Progression

| Tier | When |
|------|------|
| Local script | Personal use |
| systemd service | 24/7 single-machine |
| Docker Compose | Multi-service |
| Kubernetes | Multi-machine (probably don't need) |

## Infrastructure Priority

1. Homelab ($0)
2. OCI free tier ($0) - 4 OCPU ARM, 24GB RAM, 200GB
3. GitHub Actions ($0)
4. Supabase ($0 tier)

## Yolo Mode Flow

**Trigger**: User says "yolo mode" or "fast mode"

1. Ask only: Q0, Q1, Q2, Q6, Q12
2. Propose smart defaults for rest
3. Show summary: "Using these defaults: [list]. Proceed?"
4. On "yes" → Generate PRD immediately

**Smart Defaults by Type:**
| Q6 Type | Stack | Storage |
|---------|-------|---------|
| A. CLI | Python, Click | SQLite |
| B. Library | Python, pytest | N/A |
| C. Web | FastAPI, Jinja2 | SQLite |
| D. Pipeline | Python, pandas | SQLite |
| E. Service | Python, APScheduler | SQLite |
| F. AI Web | FastAPI, OpenRouter | SQLite |
| G. Static | HTML/CSS/JS | N/A |

## Micro Mode Flow

**Trigger**: "micro mode" OR describes <100 line script

**Questions**: Only Q1 (what) and Q11 (interface)

**Skip**: PRD, README, LLM-OVERVIEW, scripts/, TODO.md

**Output**: Single file with shebang, inline comments, usage in header

```python
#!/usr/bin/env python3
"""
script_name.py - One-line description

Usage:
    python script_name.py [args]

Created via ONE_SHOT micro mode.
"""

def main():
    # Implementation
    pass

if __name__ == "__main__":
    main()
```

**Upgrade from Micro when:**
- Script exceeds 100 lines
- Needs persistent storage
- Needs to run as service
- Needs tests
- Will be used by others

## Graceful Degradation

ONE_SHOT is overkill for some tasks. Use judgment:

| Scenario | Flow |
|----------|------|
| New project, major feature, architecture | Full ONE_SHOT |
| Medium feature, some complexity | Mini-PRD → Implement |
| Micro task, clear request, low risk | Just do it |
| User wants to understand, not change | Research only |

**Overkill signals** (skip the full flow):
- "Just add a comment"
- "Rename this variable"
- "Quick script to..."
- "Help me understand..."

**Full flow signals** (even if user says "quick"):
- Touches auth/security
- Changes data storage
- Adds external dependencies
- Modifies multiple services

## Anti-Patterns

- Drip-feeding questions (ask all upfront)
- Building without PRD approval
- PostgreSQL for small data (use SQLite)
- Adding abstraction "for flexibility"
- Skipping TODO.md updates
- Using full flow for micro tasks
- Skipping flow for "quick" changes that touch auth

## Keywords

oneshot, build, new project, create, initialize, autonomous, PRD, agents.md, utilize agents, yolo, micro, fast
