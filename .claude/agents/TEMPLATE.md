# Agent Template

Use this template when creating new native sub-agents for ONE_SHOT.

---

## Template

```markdown
---
name: agent-name
description: Brief description. Use proactively when user says 'trigger1', 'trigger2'.
tools: Read, Grep, Glob, Bash
model: sonnet
permissionMode: default
---

You are an expert [role] specializing in [domain].

## When To Use

- User says "[trigger phrase 1]"
- User says "[trigger phrase 2]"
- [Situation requiring isolated context]
- [Task that would pollute main conversation]

## Workflow

### 1. [Initial Assessment]

[What to check first]

### 2. [Core Analysis]

[Main work to perform]

### 3. [Result Summary]

[How to report findings back]

## Checklist

- [ ] [Step 1]
- [ ] [Step 2]
- [ ] [Step 3]

## Output Format

Return findings in this structure:
- **Summary**: Brief overview
- **Details**: Specific findings with file paths
- **Recommendations**: Actionable next steps

## Anti-Patterns

- Don't [common mistake]
- Avoid [inefficient approach]
```

---

## Configuration Fields

| Field | Required | Values | Description |
|-------|----------|--------|-------------|
| `name` | Yes | kebab-case | Unique identifier |
| `description` | Yes | string | When to use + trigger phrases |
| `tools` | No | comma-separated | Tools available (inherits all if omitted) |
| `model` | No | sonnet, haiku, opus, inherit | Model to use (default: sonnet) |
| `permissionMode` | No | default, acceptEdits, bypassPermissions | How to handle permissions |
| `skills` | No | comma-separated | Skills to auto-load |

---

## Model Selection Guide

| Model | Use When | Cost | Speed |
|-------|----------|------|-------|
| **haiku** | Fast lookups, simple tasks, background work | Low | Fast |
| **sonnet** | Complex reasoning, multi-step analysis | Medium | Medium |
| **opus** | Critical decisions, comprehensive review | High | Slower |
| **inherit** | Match main conversation model | Varies | Varies |

---

## Permission Modes

| Mode | Behavior | Use When |
|------|----------|----------|
| `default` | Asks for permission | Security-sensitive operations |
| `acceptEdits` | Auto-approve file changes | Background automation |
| `bypassPermissions` | No permission prompts | Trusted automation |

---

## Tool Selection Guide

**Read-only agents** (research, audit):
```
tools: Read, Grep, Glob
```

**Research agents** (exploration):
```
tools: Read, Grep, Glob, WebFetch, WebSearch
```

**Execution agents** (background work):
```
tools: Bash, Read, Write, Edit
```

**Full access** (inherit all):
```
# Omit tools field entirely
```

---

## Checklist for New Agents

- [ ] Unique name (not overlapping with skills or existing agents)
- [ ] Clear trigger phrases in description
- [ ] Include "Use proactively" if auto-invocation desired
- [ ] Appropriate model selected
- [ ] Minimal tool set (only what's needed)
- [ ] Permission mode considered
- [ ] Workflow documented
- [ ] Output format specified
- [ ] Added to INDEX.md
- [ ] Added to AGENTS.md agent_router
- [ ] Added to oneshot.sh AGENTS array

---

## Differences from Skills

| Aspect | Skills | Agents |
|--------|--------|--------|
| Context | Shared with main | Isolated window |
| Field | `allowed-tools:` | `tools:` |
| Model | Not configurable | `model:` field |
| Permissions | Not configurable | `permissionMode:` |
| Resumable | Via handoff files | Via `agentId` |
| Invocation | Synchronous | Task tool |
