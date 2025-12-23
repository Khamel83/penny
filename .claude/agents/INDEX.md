# Agents Index

Native Claude Code sub-agents for ONE_SHOT (4 total).

## Quick Reference

| Agent | Trigger | Purpose | Model |
|-------|---------|---------|-------|
| security-auditor | "security audit", "vulnerabilities" | Isolated OWASP/secrets review | sonnet |
| deep-research | "explore", "find all", "analyze" | Long codebase research | haiku |
| background-worker | "background", "parallel" | Non-blocking task execution | haiku |
| multi-agent-coordinator | "coordinate", "multiple agents" | Orchestrate agent teams | sonnet |

---

## Skills vs Agents

**Use Skills When:**
- Quick, synchronous tasks
- Need immediate conversation context
- Tight coupling with main thread
- Simple workflows

**Use Agents When:**
- Long research (don't pollute main context)
- Parallel execution needed
- Task takes >30 seconds
- Deep exploration of codebase
- Security-sensitive isolated review

---

## Agent Details

### security-auditor
- **Model**: sonnet (complex reasoning)
- **Tools**: Read, Grep, Glob, Bash
- **Purpose**: Isolated security review for OWASP top 10, secrets detection, auth vulnerabilities
- **Invocation**: "Run security-auditor agent on this code"

### deep-research
- **Model**: haiku (fast, low-latency)
- **Tools**: Read, Grep, Glob, WebFetch, WebSearch
- **Purpose**: Long codebase exploration without context pollution
- **Invocation**: "Use deep-research agent to find all authentication handlers"

### background-worker
- **Model**: haiku (fast)
- **Tools**: Bash, Read, Write
- **Permission**: acceptEdits (auto-approve file changes)
- **Purpose**: Run long tasks (tests, builds, deployments) in background
- **Invocation**: "Run tests in background with background-worker agent"

### multi-agent-coordinator
- **Model**: sonnet (complex orchestration)
- **Tools**: Read, Grep, Glob, Bash
- **Purpose**: Coordinate multiple agents for complex tasks
- **Invocation**: "Use multi-agent-coordinator to explore auth, API, and database layers in parallel"

---

## Routing

Agents are routed based on pattern matching:

```yaml
agent_router:
  - pattern: "security|audit|vulnerabilities|OWASP"
    agent: security-auditor

  - pattern: "explore|find all|analyze patterns|deep dive"
    agent: deep-research

  - pattern: "background|parallel|long task"
    agent: background-worker

  - pattern: "coordinate|multiple agents|parallel agents"
    agent: multi-agent-coordinator
```

---

## Agent Chains

Common workflows composing multiple agents:

```
Security Review:
  deep-research → security-auditor → code-reviewer (skill)

Large Codebase Analysis:
  multi-agent-coordinator → [deep-research x3] → summary

Background CI:
  background-worker (tests) + background-worker (build) → report
```

---

## Creating New Agents

See `TEMPLATE.md` for the agent creation template.

**Key differences from skills:**
- Agents use `tools:` (not `allowed-tools:`)
- Agents support `model:` field (sonnet, haiku, opus, inherit)
- Agents support `permissionMode:` (default, acceptEdits, bypassPermissions)
- Agents get isolated context windows
- Agents can be resumed via `agentId`
