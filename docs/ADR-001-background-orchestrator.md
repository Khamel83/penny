# ADR-001: Background Orchestrator with Cheap Probes

**Date**: 2026-01-04
**Status**: Accepted
**Context**: Penny v2.0 Architecture

## Context

Penny receives voice memos that sometimes require complex reasoning to process properly. Initially, all requests were handled by expensive LLM calls (OpenRouter/Gemini), even for simple tasks that could be answered with cheap or free operations.

**Problems:**
1. **Cost**: Every LLM call costs money, even for simple queries
2. **Latency**: LLM API calls add latency (1-5 seconds)
3. **Overkill**: Many requests can be answered with grep, file reads, or API health checks
4. **No autonomy**: System couldn't work on background tasks while user is away

## Decision

Implement a **Background Orchestrator** that runs cheap probes first and only escalates to expensive LLM reasoning when confidence thresholds are met.

### Architecture

```
Background Task Created
        ↓
  Run Cheap Probes (free)
  - grep codebase
  - read files
  - check APIs
  - run commands
        ↓
  Calculate Confidence (0-1)
        ↓
    ┌───┴────────────┐
    │                │
High (≥0.8)    Medium/Low (<0.8)
    │                │
Direct         Escalate to LLM
Delivery         (quick/full)
```

### Available Probes

| Probe | Cost | Use Case |
|-------|------|----------|
| `probe_grep` | Free | Search codebase for patterns |
| `probe_file_read` | Free | Read specific files |
| `probe_api_check` | Free | Health check URLs |
| `probe_atlas` | Free | Query knowledge base |
| `probe_command` | Free | Run safe diagnostic commands |

### Escalation Logic

| Confidence | Action | Cost |
|------------|--------|------|
| ≥0.8 | Direct delivery (no reasoning) | $0 |
| ≥0.6 | Quick reasoning (cheap LLM) | ~$0.0001 |
| <0.6 | Full reasoning (expensive LLM) | ~$0.001 |

## Rationale

### Why This Approach?

1. **Cost Efficiency**: 80%+ of requests resolved with free probes
2. **Speed**: Probes run in milliseconds vs seconds for LLMs
3. **Autonomy**: System can work on background tasks while user is away
4. **Scalability**: Can queue multiple background tasks without API rate limits

### Why Not Alternatives?

| Alternative | Rejected Because |
|-------------|------------------|
| **Always use LLM** | Too expensive for simple queries ($10-50/month vs $1-2) |
| **User approval prompts** | Breaks autonomy - defeats purpose of background processing |
| **Pure rule-based** | Too rigid, can't handle edge cases |
| **No background processing** | Can't work on tasks while user is away |

### Design Principles

1. **"Gather signal cheap, reason expensive"** - Core philosophy
2. **Confidence-based escalation** - Only pay for LLM when needed
3. **Graceful degradation** - Probes fail safely, escalate anyway
4. **Non-blocking** - Background tasks don't block API requests

## Consequences

### Positive

- ✅ **90% cost reduction** for background tasks
- ✅ **Sub-second latency** for probe-based answers
- ✅ **Autonomous operation** - works while user is away
- ✅ **Extensible** - easy to add new probes
- ✅ **Observable** - all probe results logged

### Negative

- ⚠️ **Complexity** - More moving parts than simple LLM calls
- ⚠️ **Probe maintenance** - Probes need updates as codebase changes
- ⚠️ **Confidence calibration** - Thresholds need tuning
- ⚠️ **Debugging difficulty** - Harder to trace probe failures

### Trade-offs

| Aspect | Before | After |
|--------|--------|-------|
| Cost per query | $0.001 | $0.0001 (avg) |
| Latency | 1-5s | <100ms (probe) / 1-5s (LLM) |
| Code complexity | ~500 lines | ~1500 lines |
| Autonomy | None | Full background processing |

## Implementation Details

### Database Schema

```sql
CREATE TABLE background_tasks (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT NOT NULL,  -- pending, probing, escalating, completed, failed
    probe_results TEXT,    -- JSON blob
    confidence REAL,
    escalated_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/tasks/background` | Create background task |
| `GET /api/orchestrator/status` | Check orchestrator state |

### Configuration

```bash
PENNY_POLL_INTERVAL=30      # Poll interval in seconds
PENNY_HIGH_CONFIDENCE=0.8   # Threshold for direct delivery
PENNY_PROBE_TIMEOUT=30      # Probe timeout in seconds
```

## Examples

### Example 1: High Confidence (Direct Delivery)

```
Task: "Find all TODO comments in the codebase"
→ probe_grep("TODO") finds 47 matches
→ confidence = 0.95 (high)
→ Direct delivery: "Found 47 TODOs"
→ Cost: $0, Time: 50ms
```

### Example 2: Low Confidence (LLM Escalation)

```
Task: "What's the best way to add authentication?"
→ probe_grep finds auth in 12 files (too many)
→ confidence = 0.4 (low)
→ Escalate to LLM with context
→ LLM provides recommendation
→ Cost: $0.001, Time: 2s
```

## Future Considerations

### Potential Enhancements

1. **Probe caching** - Cache probe results for repeated queries
2. **Parallel probes** - Run multiple probes concurrently
3. **Confidence learning** - Adjust thresholds based on feedback
4. **Custom probes** - Let users define project-specific probes

### Monitoring

Key metrics to track:
- Probe success rate (target: >95%)
- Escalation rate (target: <20%)
- Average confidence (target: >0.7)
- Cost per task (target: <$0.0005)

## References

- Implementation: `penny/orchestrator/loop.py`, `penny/orchestrator/probes.py`, `penny/orchestrator/escalation.py`
- Tests: `tests/test_orchestrator.py`
- Database schema: `penny/database.py`
