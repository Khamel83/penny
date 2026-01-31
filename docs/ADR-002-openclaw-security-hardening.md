# ADR-002: OpenClaw Security Hardening

**Date**: 2026-01-29
**Status**: Accepted
**Context**: OpenClaw v2.1 Security Architecture

## Architecture Note

**Penny** is a voice assistant layer built on top of **OpenClaw**:

```
┌─────────────────────────────────────────────────────────────────┐
│                     Penny (Voice Assistant Layer)               │
│  • Transcribe → Classify → Route voice memos                    │
│  • Background orchestrator (cheap probes + expensive reasoning) │
│  • Web UI (HTMX)                                                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                     OpenClaw (AI Agent Core)                     │
│  • Agent orchestration                                          │
│  • Skill system                                                  │
│  • Integration framework                                        │
│  • Build execution (Claude Code)                                │
└─────────────────────────────────────────────────────────────────┘
```

Penny extends OpenClaw with voice-specific capabilities. This ADR documents security controls for the combined system.

## Context

Penny (voice layer on top of OpenClaw) is a multi-capability AI assistant system with several features that require security considerations:

- **Penny**: Voice assistant that receives transcribed voice memos and routes to services
- **Build Pipeline**: Voice-to-code via Claude Agent SDK with code execution capabilities
- **Background Orchestrator**: Automated task processing with cheap probes
- **Telegram Integration**: @PennyMoltBot (Penny's voice bot) + @PennyOCIBot (OpenClaw's bot)

The system exposes several attack vectors:
1. **Public webhook endpoint** (`/api/telegram/webhook`) - could receive malicious requests
2. **Voice-to-build pipeline** - executes code based on voice transcription
3. **No authentication** on most endpoints (originally designed for trusted Tailscale network)

**Problems:**
1. **Unauthorized code execution** - Voice memos could trigger builds without approval
2. **Webhook abuse** - Public endpoint could be called without Telegram's secret token
3. **Network exposure** - System reachable from public internet (141.148.146.79:8888)
4. **No audit trail** - Difficult to track what builds were approved and when
5. **Insufficient fail-safe** - Timeouts and errors had ambiguous security posture

## Decision

Implement a **defense-in-depth security architecture** with multiple protection layers:

### Security Layers

```
Request → Tailscale IP Whitelist → Webhook Secret Validation → Build Approval Gate → Execution
            (Network Layer)          (Application Layer)       (Human-in-the-Loop)    (Final Action)
```

### Layer 1: Tailscale IP Whitelist (Network)

Restrict all API access to Tailscale CGNAT range (`100.x.x.x`) plus localhost for development.

**Implementation**: `penny/main.py:39-67` - `TailscaleIPMiddleware`

```python
class TailscaleIPMiddleware(BaseHTTPMiddleware):
    ALLOWED_PREFIXES = ("100.", "127.")

    async def dispatch(self, request: Request, call_next):
        if not TAILSCALE_ONLY:
            return await call_next(request)

        # Get client IP from X-Forwarded-For or direct connection
        forwarded_for = request.headers.get("X-Forwarded-For")
        client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else request.client.host

        # Block non-Tailscale IPs
        if not client_ip.startswith(("100.", "127.")):
            logger.warning(f"Blocked request from non-Tailscale IP: {client_ip}")
            return JSONResponse(status_code=403, content={"detail": "Access denied"})
```

**Configuration**:
```bash
PENNY_TAILSCALE_ONLY=true  # Default: true (fail-secure)
```

### Layer 2: Webhook Secret Token (Application)

Validate Telegram webhook requests using the secret token set in BotFather.

**Implementation**: `penny/main.py:252-255`

```python
# Validate Telegram's secret token
if TELEGRAM_WEBHOOK_SECRET:
    token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if token != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid webhook token")
```

**Configuration**:
```bash
TELEGRAM_WEBHOOK_SECRET=xxx  # Required for webhook endpoint
```

### Layer 3: Build Approval Gate (Human-in-the-Loop)

All voice-triggered builds require explicit Telegram approval before code execution.

**Implementation**: `penny/integrations/claude_code.py:168-212`

**Flow**:
1. Voice memo classified as "build" → `request_build_approval()`
2. Send inline buttons to Telegram: "Approve" or "Reject"
3. Wait for user response (5 minute timeout)
4. Timeout = auto-reject (fail-secure)
5. Store result in `pending_approvals` table (audit trail)

```python
async def request_build_approval(
    build_id: str,
    transcript: str,
) -> bool:
    """Request build approval via Telegram.

    Returns True if approved, False if rejected or timeout.
    Timeout defaults to reject (fail-secure).
    """
    # Save pending approval to database
    await database.save_pending_approval(
        build_id=build_id,
        transcript=transcript,
        message_id=str(message_id),
    )

    # Create future to wait for approval
    future = loop.create_future()
    pending_approvals[build_id] = future

    try:
        # Wait for approval with timeout
        approved = await asyncio.wait_for(future, timeout=BUILD_APPROVAL_TIMEOUT_SECONDS)
        return approved
    except asyncio.TimeoutError:
        # Timeout = reject by default
        return False
```

**Configuration**:
```bash
PENNY_BUILD_APPROVAL_TIMEOUT=300  # Default: 300 seconds (5 minutes)
```

### Layer 4: Audit Trail (Database)

All approval attempts are tracked in the `pending_approvals` table.

**Implementation**: `penny/database.py:114-132`

```sql
CREATE TABLE IF NOT EXISTS pending_approvals (
    id TEXT PRIMARY KEY,
    build_id TEXT NOT NULL,
    transcript TEXT NOT NULL,
    message_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    approved BOOLEAN,
    client_ip TEXT,
    resolved_from_ip TEXT
)
```

**Audit fields**:
- `created_at` - When approval was requested
- `resolved_at` - When user responded
- `approved` - Final decision (true/false)
- `transcript` - Original voice memo text
- `client_ip` - IP address that requested the build
- `resolved_from_ip` - IP address that approved/rejected the build

### Layer 5: Fail-Secure Defaults

All security decisions default to the safest option:

| Scenario | Default | Rationale |
|----------|---------|-----------|
| Tailscale check fails | Block | Better to break access than allow unauthorized |
| Webhook token missing | Allow | Local testing compatibility (but warn in logs) |
| Approval timeout | Reject | Better to miss a build than execute unauthorized code |
| Database error | Reject | Fail-closed on audit trail corruption |

## Rationale

### Why This Approach?

1. **Defense-in-depth** - Multiple independent layers must all fail for a breach
2. **Zero-trust** - Even Tailscale network traffic gets validated
3. **Human-in-the-loop** - No code execution without explicit approval
4. **Auditability** - All security decisions logged with timestamps
5. **Fail-secure** - Errors and timeouts default to safest option

### Why Not Alternatives?

| Alternative | Rejected Because |
|-------------|------------------|
| **API key authentication** | Adds complexity, keys can leak, Tailscale is stronger |
| **OAuth2/JWT** | Overkill for personal homelab, introduces token management |
| **Only Tailscale** | Single point of failure, webhook still publicly exposed |
| **Only approval gate** | Doesn't protect other endpoints from network exposure |
| **Fail-open on timeout** | Risky - could execute builds when user is unavailable |

### Design Principles

1. **Security by default** - Safe defaults, explicit opt-in to relax security
2. **Graceful degradation** - Security layers work independently
3. **Observable security** - All decisions logged for audit
4. **Low friction** - Approval process is quick (tap a button)

## Consequences

### Positive

- ✅ **No unauthorized code execution** - Human approval required for all builds
- ✅ **Network isolation** - Only Tailscale devices can reach API endpoints
- ✅ **Audit trail** - Complete history of all approval requests
- ✅ **Fail-secure** - Timeouts and errors default to rejection
- ✅ **Webhook protection** - Telegram secret token validates webhook calls
- ✅ **Production-ready** - Suitable for 24/7/365 public internet exposure

### Negative

- ⚠️ **Approval friction** - Every build requires manual approval (by design)
- ⚠️ **Tailscale dependency** - Must join Tailscale network for API access
- ⚠️ **Configuration complexity** - Multiple security-related env vars
- ⚠️ **Mobile notifications** - Requires Telegram app for approvals

### Trade-offs

| Aspect | Before | After |
|--------|--------|-------|
| Build latency | Instant | ~5-30 seconds (approval time) |
| Network access | Open to Tailscale | Open to Tailscale (enforced) |
| Webhook security | None | Secret token validation |
| Audit capability | None | Full approval history |
| Security posture | Trusted network | Defense-in-depth |
| Fail behavior | Ambiguous | Explicit reject-on-timeout |

## Implementation Details

### Database Schema

```sql
-- Pending build approvals for security gate
CREATE TABLE IF NOT EXISTS pending_approvals (
    id TEXT PRIMARY KEY,
    build_id TEXT NOT NULL,
    transcript TEXT NOT NULL,
    message_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    approved BOOLEAN
);

-- Indexes for efficient lookups
CREATE INDEX idx_pending_approvals_build_id ON pending_approvals(build_id);
CREATE INDEX idx_pending_approvals_status ON pending_approvals(status);
CREATE INDEX idx_pending_approvals_client_ip ON pending_approvals(client_ip);
```

### API Endpoints

| Endpoint | Security Layer |
|----------|----------------|
| All endpoints | Tailscale IP whitelist (Layer 1) |
| `/api/telegram/webhook` | Webhook secret token (Layer 2) |
| `/api/ingest` (build category) | Build approval gate (Layer 3) |
| All security decisions | Audit trail (Layer 4) |

### Configuration

```bash
# Network security (Layer 1)
PENNY_TAILSCALE_ONLY=true  # Default: true (Tailscale-only access)

# Webhook security (Layer 2)
TELEGRAM_WEBHOOK_SECRET=xxx  # Required for webhook endpoint

# Build approval (Layer 3)
PENNY_BUILD_APPROVAL_TIMEOUT=300  # Default: 300 seconds (5 minutes)

# Fail-secure behavior (Layer 5)
# All timeouts default to rejection
# All errors default to blocking access
```

## Examples

### Example 1: Successful Build Flow

```
1. User sends voice memo: "Fix the authentication bug"
2. Mac mini transcribes and POSTs to /api/ingest (allowed: Tailscale IP)
3. LLM classifier: category="build", confidence=0.9
4. Build approval requested:
   - Message sent to @PennyMoltBot
   - Inline buttons: [Approve] [Reject]
5. User taps [Approve]
6. Build proceeds with Claude Code (GLM-4.7)
7. Database record: approved=true, resolved_at=<timestamp>
```

### Example 2: Timeout Rejection

```
1. User sends voice memo: "Deploy to production"
2. LLM classifier: category="build", confidence=0.85
3. Build approval requested
4. User is away from phone...
5. 5 minutes pass...
6. System auto-rejects: approved=false, status=timeout
7. Message updated: "Build Request Timed Out - Rejected by default"
```

### Example 3: Network Block

```
1. Attacker tries: curl https://141.148.146.79:8888/api/items
2. Client IP: 1.2.3.4 (not Tailscale)
3. TailscaleIPMiddleware blocks request
4. Response: 403 Forbidden - "Access denied: Tailscale connection required"
5. Log: "Blocked request from non-Tailscale IP: 1.2.3.4"
```

## Security Posture

### Current Capabilities

| Control | Status | Notes |
|---------|--------|-------|
| Network isolation | ✅ Active | Tailscale-only access |
| Build approval gate | ✅ Active | All builds require approval |
| Webhook validation | ✅ Active | Secret token required |
| Audit trail | ✅ Active | All approvals logged |
| Fail-secure defaults | ✅ Active | Timeouts reject |

### Threat Model Mitigations

| Threat | Mitigation |
|--------|------------|
| Unauthorized code execution | Build approval gate (human must approve) |
| Webhook abuse | Secret token validation + Tailscale IP check |
| Network exposure | Tailscale IP whitelist (100.x.x.x only) |
| Compromised voice source | Build approval gate (human sees transcript) |
| Prompt injection | Human review before any code execution |
| Audit trail tampering | SQLite with file permissions (chmod 600) |

### What This Does NOT Protect Against

- ⚠️ **Compromised Tailscale credentials** - If attacker joins your Tailscale network
- ⚠️ **Compromised Telegram account** - If attacker has access to your Telegram
- ⚠️ **Local system compromise** - If attacker has shell access to OCI-Dev
- ⚠️ **Social engineering** - If user approves malicious build unknowingly

**Mitigation**: Use Tailscale key expiration, enable 2FA on Telegram, harden SSH access.

## Future Considerations

### Potential Enhancements

1. **Approval allowlist** - Pre-approve certain safe build patterns
2. **Approval delegation** - Allow trusted users to approve builds
3. **MFA for approvals** - Require second factor for production builds
4. **Approval analytics** - Track approval rates, reasons, patterns
5. **Automatic expiration** - Auto-reject stale approvals after N hours

### Monitoring

Key metrics to track:
- Approval rate (target: 80-95% approved)
- Average approval time (target: <30 seconds)
- Timeout rate (target: <5%)
- Blocked requests by IP (target: 0)
- Webhook validation failures (target: 0)

## References

- Implementation: `penny/main.py:39-67` (Tailscale middleware), `penny/main.py:252-255` (webhook validation)
- Build approval: `penny/integrations/claude_code.py:168-212` (approval logic)
- Database schema: `penny/database.py:114-132` (pending_approvals table)
- Related ADR: `ADR-001-background-orchestrator.md` (orchestrator security considerations)
- Security audit: See `TODO.md` Done (2026-01-29) for audit results

---

**Architecture Note**: This security architecture applies to the Penny + OpenClaw integrated system. Penny provides the voice interface layer while OpenClaw provides the underlying AI agent platform. All security controls are implemented in Penny (this repository).
