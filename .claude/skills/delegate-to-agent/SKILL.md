---
name: delegate-to-agent
description: "Intelligently delegate to native sub-agents for isolated context work. Use when user says 'background', 'parallel', 'deep dive', 'isolated', or when task would pollute main context."
allowed-tools: Task
---

# Delegate to Agent

You are an intelligent router that decides when to delegate tasks to native sub-agents vs handling them in the main conversation.

## When To Use

- User explicitly requests "background", "parallel", or "isolated" execution
- Task involves reading 10+ files (would pollute context)
- Security audit requiring isolation
- Long-running operations (tests, builds)
- Complex multi-area exploration
- User says "deep dive" or "thorough exploration"

## When NOT to Use

- Simple, quick tasks
- Tasks requiring immediate feedback
- Tasks needing main conversation context
- Single file operations
- User wants to see progress in real-time

## Decision Matrix

| Condition | Agent | Reason |
|-----------|-------|--------|
| Security review | security-auditor | Isolated, thorough |
| Find all X across codebase | deep-research | Context-heavy |
| Run tests/build | background-worker | Long-running |
| Multiple exploration areas | multi-agent-coordinator | Parallel efficiency |
| Quick lookup | None (use skill) | Overhead not worth it |
| Need real-time feedback | None (use skill) | Agents return on completion |

## Agent Routing

### security-auditor
**Trigger phrases**: "security audit", "OWASP", "vulnerabilities", "secrets scan", "penetration test"
**Model**: sonnet (complex reasoning)
**Tools**: Read, Grep, Glob, Bash (read-only)

```
Delegate to security-auditor when:
- Pre-deployment security check needed
- Reviewing auth/data handling code
- Looking for hardcoded secrets
- OWASP compliance check
```

### deep-research
**Trigger phrases**: "explore", "find all", "how does X work", "trace", "understand codebase"
**Model**: haiku (fast, low-cost)
**Tools**: Read, Grep, Glob, WebFetch, WebSearch

```
Delegate to deep-research when:
- Understanding unfamiliar code
- Finding all usages of function/pattern
- Mapping dependencies
- Reading documentation
- Would read 10+ files
```

### background-worker
**Trigger phrases**: "run tests", "build", "background", "parallel", "don't wait"
**Model**: haiku (fast)
**Tools**: Bash, Read, Write
**Permission**: acceptEdits (auto-approve)

```
Delegate to background-worker when:
- Test suite takes >30 seconds
- Build processes
- Database migrations
- Any long-running script
```

### multi-agent-coordinator
**Trigger phrases**: "coordinate", "multiple agents", "parallel exploration", "divide and conquer"
**Model**: sonnet (orchestration logic)
**Tools**: Read, Grep, Glob, Bash

```
Delegate to multi-agent-coordinator when:
- Complex task benefits from parallelization
- Need to explore multiple areas simultaneously
- Task has independent subtasks
- Need specialized agents working together
```

## Workflow

### 1. Analyze Request

Determine if delegation is appropriate:
```
Questions:
- Will this read many files? → deep-research
- Is this security-sensitive? → security-auditor
- Will this take >30 seconds? → background-worker
- Can this be parallelized? → multi-agent-coordinator
- Is this quick/simple? → Don't delegate
```

### 2. Select Agent

Match request to most appropriate agent based on:
- Task type
- Expected duration
- Context sensitivity
- Parallelization potential

### 3. Formulate Prompt

Create clear, actionable prompt for the agent:
```markdown
## Task
[Clear description of what to do]

## Scope
[Files/directories to focus on]

## Expected Output
[What format to return results in]

## Constraints
[Any limitations or focuses]
```

### 4. Invoke Agent

Use Task tool to spawn agent:
```
Task:
  subagent_type: [agent-name]
  description: [short description]
  prompt: [detailed prompt]
  run_in_background: [true/false]
```

### 5. Handle Results

- Summarize agent findings for user
- Highlight key discoveries
- Recommend next steps

## Prompt Templates

### For deep-research
```
Explore the codebase to understand [topic].

Focus areas:
- [Area 1]
- [Area 2]

Return:
- Key findings with file paths
- Code patterns discovered
- Dependency relationships
- Recommendations
```

### For security-auditor
```
Perform security audit on [scope].

Check for:
- OWASP Top 10 vulnerabilities
- Hardcoded secrets
- Auth/authz issues
- Input validation

Return:
- Findings by severity
- Specific file:line locations
- Remediation recommendations
```

### For background-worker
```
Run [command/process].

Expected duration: [estimate]
Success criteria: [what indicates success]

Return:
- Exit status
- Key output (summarized)
- Any failures with details
```

### For multi-agent-coordinator
```
Coordinate exploration of [complex task].

Subtasks:
1. [Subtask 1] - can parallelize
2. [Subtask 2] - depends on 1
3. [Subtask 3] - can parallelize

Synthesize findings into unified report.
```

## Anti-Patterns

- Delegating trivial tasks (overhead exceeds benefit)
- Not providing enough context to agent
- Running agents when real-time feedback needed
- Over-parallelizing simple sequential tasks
- Not summarizing agent results for user

## Integration with Skills

Some tasks are better handled by skills:
- Quick code review → code-reviewer skill
- Simple debugging → debugger skill
- Single file edit → refactorer skill

**Rule of thumb**: If task can be done in <30 seconds with minimal file reads, use a skill instead.

## Keywords

delegate, background, parallel, isolated, sub-agent, spawn, coordinate, async, long-running
