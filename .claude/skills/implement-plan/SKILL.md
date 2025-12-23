---
name: implement-plan
description: "Execute an approved implementation plan. Use when user says 'implement plan', 'execute plan', or references a plan file."
allowed-tools: Read, Glob, Grep, Write, Edit, Bash, Task
---

# Implement Plan

You are an expert at executing structured implementation plans systematically. You follow plans precisely while adapting to discoveries during implementation.

## When To Use

- User says "implement plan" or "/implement_plan"
- User says "execute plan" or "run the plan"
- User references a plan file with "@thoughts/shared/plans/..."
- After a plan has been approved

## Inputs

- Path to approved plan file (e.g., `thoughts/shared/plans/YYYY-MM-DD-description.md`)
- Plan must have Status: Approved

## Outputs

- Implemented features per plan
- Updated TODO.md with progress
- Commits after each significant step
- Plan file updated to reflect progress

## Pre-Implementation Checklist

Before starting:

1. **Read the plan completely**
2. **Verify Status is "Approved"**
3. **Check all decisions are filled in** (no "_pending_" entries)
4. **Identify dependencies** - are they met?
5. **Understand success criteria**

If any decisions are pending, STOP and ask user to complete them.

## Workflow

### Phase 1: Setup

```markdown
1. Read plan file completely
2. Parse implementation steps into TODO.md format
3. Identify first actionable step
4. Announce: "Starting implementation of [Plan Title]"
```

### Phase 2: Execute (Build Loop)

For each implementation step:

```
1. Mark step as in_progress in TODO.md
2. Implement the step
3. Test the implementation
4. Commit with message: "feat([scope]): [description] - implements step X.Y"
5. Mark step as completed in TODO.md
6. Update plan file with progress
7. Move to next step
```

### Phase 3: Verification

After all steps complete:

```
1. Run full test suite
2. Verify all success criteria met
3. Update plan Status to "Completed"
4. Create summary of what was implemented
```

## Progress Tracking

Update both files during implementation:

### TODO.md Format
```markdown
## In Progress
- [ ] Step 2.1: Implementing user model

## Completed
- [x] Step 1.1: Created project structure
- [x] Step 1.2: Set up dependencies

## Blocked
- [ ] Step 3.1: Waiting on API key (needs user input)
```

### Plan File Updates
```markdown
## Implementation Steps

### Phase 1: Setup [COMPLETED]
- [x] Step 1.1 (commit: abc123)
- [x] Step 1.2 (commit: def456)

### Phase 2: Core Features [IN PROGRESS]
- [x] Step 2.1 (commit: ghi789)
- [ ] Step 2.2 <- CURRENT
```

## Commit Message Format

```
type(scope): description - implements step X.Y

Types: feat, fix, refactor, test, docs, chore
Scope: component or area affected
Step reference: links back to plan
```

Examples:
```
feat(auth): add user login endpoint - implements step 2.1
test(auth): add unit tests for login - implements step 2.2
fix(auth): handle invalid tokens - implements step 2.3
```

## Handling Issues

### Unexpected Complexity
1. Document the issue in plan file under "Implementation Notes"
2. If blocking, create handoff and ask for guidance
3. Don't deviate significantly from plan without approval

### Missing Requirements
1. Note what's missing
2. Add to "Decisions Needed" section
3. Pause that step, continue with others if possible
4. Ask user for input

### Test Failures
1. Fix immediately if simple
2. Document if complex
3. Don't proceed past failing tests

## Context Management

When context is running low (< 10% remaining):

1. Complete current step if close to done
2. Update plan with exact progress
3. Use `/create_handoff` to preserve context
4. After `/clear`, use `/resume_handoff` to continue

## Integration with OneShot

- Follow ONE_SHOT build loop: implement -> test -> commit -> update TODO.md
- Respect hard stops (storage, auth, deployment)
- Use appropriate thinking modes for complex decisions
- Create handoff before context exhaustion

## Keywords

implement plan, execute plan, run plan, start implementation, follow plan, plan file, approved plan
