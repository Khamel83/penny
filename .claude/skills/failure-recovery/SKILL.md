---
name: failure-recovery
description: "Recovery protocols for stuck agents, context exhaustion, build failures, and confusion. Use when agent is looping, responses degrading, builds failing repeatedly, or user says 'you're stuck' or 'start over'."
allowed-tools: Read, Bash, Glob, Grep
---

# Failure Recovery

Recovery protocols when things go wrong. Don't panic - follow these systematic approaches.

## When To Use

- Agent is looping or repeating the same action
- Responses are getting shorter or missing context
- Build/tests failing repeatedly (3+ times)
- User says "you're stuck", "start over", "lost", "confused"
- Project state feels inconsistent

---

## Build Failure Recovery

**Trigger**: Tests fail, build errors, runtime crashes

```yaml
recovery_build_failure:
  step_1_isolate:
    - "pytest tests/ -x --tb=short"  # Stop at first failure
    - "git diff HEAD~1"              # What changed?

  step_2_rollback_test:
    - "git stash"
    - "git checkout HEAD~1"
    - "pytest tests/"                # Verify it works

  step_3_bisect_if_needed:
    - "git bisect start"
    - "git bisect bad HEAD"
    - "git bisect good [last-good-commit]"

  step_4_fix:
    rule: "Fix the bug, don't refactor"
    avoid: "No cleanup, no improvements, just fix"

  step_5_verify:
    - "pytest tests/"
    - "git stash pop"  # If we stashed changes
```

**Key principle**: Smallest change that fixes the issue. Do NOT refactor while debugging.

---

## Agent Confusion Recovery

**Trigger**: Looping, contradicting self, asking already-answered questions

```yaml
recovery_agent_confusion:
  symptoms:
    - "Repeating same action without progress"
    - "Contradicting previous statements"
    - "Asking questions already answered"
    - "Making changes that break previously working code"

  step_1_restate:
    action: |
      STOP. Let's reset.
      Current phase: [Phase X]
      Current task: [Task Y]
      Last successful action: [What worked]

  step_2_narrow_focus:
    action: |
      Focus only on: [single file]
      Specific change: [exact change needed]
      Do not touch other files.

  step_3_verify_understanding:
    action: |
      Before proceeding, confirm:
      1. What file are we changing?
      2. What exact change?
      3. Why this change?

  step_4_checkpoint:
    action: "Update TODO.md before continuing"
```

---

## Context Window Exhaustion

**Trigger**: Responses getting shorter, missing earlier context, forgetting decisions

```yaml
recovery_context_exhaustion:
  symptoms:
    - "Responses noticeably shorter"
    - "Forgetting earlier decisions"
    - "Re-asking questions already answered"
    - "Missing important context from earlier"

  prevention:
    - "Use TODO.md for task state"
    - "Keep LLM-OVERVIEW.md updated"
    - "Don't paste entire files unnecessarily"
    - "Reference file:line instead of copying code"

  recovery:
    step_1_handoff:
      action: "Generate handoff state document"
      template: |
        ## HANDOFF STATE
        **Project**: [name]
        **Timestamp**: [now]

        ### Completed
        - [list from TODO.md Done section]

        ### In Progress
        - [current task + status]

        ### Next Action (BE SPECIFIC)
        1. Open file: [exact path]
        2. Find: [function/line]
        3. Do: [exact change]

        ### Critical Context
        - [decisions made]
        - [blockers encountered]

    step_2_new_session:
      action: |
        Start new session. Read in order:
        1. LLM-OVERVIEW.md
        2. TODO.md
        3. Handoff document
        Confirm understanding before proceeding.
```

---

## "I'm Lost" Recovery

**Trigger**: Request doesn't match any category, project state unclear, contradictory context

```yaml
recovery_lost:
  symptoms:
    - "User request doesn't fit normal patterns"
    - "Project state is inconsistent"
    - "Previous context missing or contradictory"
    - "Agent unsure what to do next"

  recovery_protocol:
    step_1: "STOP. Don't guess or hallucinate."

    step_2_ask_user:
      action: |
        I want to make sure I help you correctly. Can you tell me:
        1. What's the end goal you're trying to achieve?
        2. Is this a new project, existing project, or continuation?
        3. What's the most important thing to get right?

    step_3: "Based on answers, re-run triage"

  anti_patterns:
    - "DO NOT pretend to understand when confused"
    - "DO NOT make up context that wasn't provided"
    - "DO NOT assume - ask"
```

---

## Dependency Hell Recovery

**Trigger**: Package conflicts, version mismatches, environment issues

```yaml
recovery_dependency_hell:
  step_1_isolate:
    - "python -m venv .venv-clean"
    - "source .venv-clean/bin/activate"

  step_2_minimal_install:
    - "pip install [core-deps-only]"
    - "Test if basic functionality works"

  step_3_add_incrementally:
    - "Add deps one at a time"
    - "Test after each addition"
    - "Stop when you find the conflict"

  step_4_pin_versions:
    - "pip freeze > requirements.lock"
    - "Document what versions work"
```

---

## Recovery Decision Tree

```
Problem detected
    ├─ Build/test failure?     → Build Failure Recovery
    ├─ Agent acting weird?     → Agent Confusion Recovery
    ├─ Responses degrading?    → Context Window Exhaustion
    ├─ Package conflicts?      → Dependency Hell Recovery
    ├─ Completely lost?        → "I'm Lost" Recovery
    └─ Unknown?                → Generate handoff, start fresh session
```

---

## Anti-Patterns

**During recovery, AVOID:**
- Refactoring while debugging
- Making multiple changes at once
- Guessing at solutions without verification
- Continuing when confused
- Skipping verification steps

**ALWAYS:**
- Make one change at a time
- Verify after each change
- Update TODO.md with current state
- Ask user when genuinely stuck

## Keywords

stuck, looping, confused, lost, broken, failing, recovery, reset, start over, context exhaustion, dependency hell, build failure
