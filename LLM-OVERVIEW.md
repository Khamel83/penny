# LLM-OVERVIEW: Penny

> Complete context for any LLM to understand this project.
> **Last Updated**: 2026-01-28
> **ONE_SHOT Version**: 6.0

## 1. WHAT IS THIS PROJECT?

### One-Line Description
A voice assistant that transcribes, classifies, and routes voice memos to appropriate services with autonomous build capabilities.

### The Problem It Solves
Voice memos pile up unorganized. Manual transcription and routing is tedious. Complex voice-to-build workflows require expensive LLM usage for simple tasks.

### Current State
- **Status**: Production (OCI-Dev 24/7/365)
- **Version**: 2.1 (Security Hardening)
- **Last Milestone**: Security hardening - Tailscale IP whitelist + Build approval gate (2026-01-28)
- **Next Milestone**: Home Assistant integration

## 2. ARCHITECTURE OVERVIEW

### Tech Stack
| Component | Technology |
|-----------|------------|
| Language | Python 3.12 |
| Framework | FastAPI + HTMX |
| Database | SQLite (async via aiosqlite) |
| Deployment | systemd on OCI-Dev (100.126.13.70:8888) |
| Classification LLM | OpenRouter (gemini-2.5-flash-lite) |
| Build LLM | Z.AI GLM-4.7 / Anthropic Opus |
| Transcription | mlx-whisper on Mac mini |
| Service Router | Claude/Gemini CLI + OpenRouter/GLM APIs |

### Key Components

| Component | Purpose | Location |
|-----------|---------|----------|
| `main.py` | FastAPI app with HTMX web UI | `penny/main.py` |
| `classifier.py` | LLM + keyword classification | `penny/classifier.py` |
| `router.py` | Category → integration routing | `penny/router.py` |
| `service_router.py` | Dispatch to AI services (no API keys) | `penny/service_router.py` |
| `database.py` | Async SQLite (items, tasks, sessions) | `penny/database.py` |
| `orchestrator/loop.py` | Background polling loop | `penny/orchestrator/loop.py` |
| `orchestrator/probes.py` | Cheap info-gathering functions | `penny/orchestrator/probes.py` |
| `orchestrator/escalation.py` | Confidence-based escalation | `penny/orchestrator/escalation.py` |
| `watcher/watcher.py` | Mac mini transcription relay | `watcher/watcher.py` |

### Integration Categories

| Category | Route | Integration |
|----------|-------|-------------|
| shopping | Google Keep | `penny/integrations/google_keep.py` |
| media | Jellyseerr | `penny/integrations/jellyseerr.py` |
| reminder | Apple Reminders | `penny/integrations/reminders.py` |
| calendar | Apple Calendar | `penny/integrations/calendar.py` |
| notes | Apple Notes | `penny/integrations/notes.py` |
| work | Telegram | `penny/integrations/telegram.py` |
| build | Claude Code | `penny/integrations/claude_code.py` |
| smart_home | Home Assistant | *Not yet implemented* |
| personal | Penny Storage | Internal database |

## 3. KEY FILES

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Project instructions for Claude Code |
| `AGENTS.md` | ONE_SHOT skill routing rules |
| `TODO.md` | Task tracking |
| `README.md` | User-facing documentation |
| `deploy/penny.service` | systemd service configuration |
| `deploy/install.sh` | Production installation script |

## 4. DATA FLOW

```
Voice Memo → iCloud → Mac mini Watcher → mlx-whisper
                                        ↓
                              Penny API (OCI-Dev:8888)
                                        ↓
                    ┌───────────────────┴───────────────────┐
                    │   LLM Classifier (OpenRouter/Gemini)   │
                    │   Extract: category, confidence, data │
                    └───────────────────┬───────────────────┘
                                        ↓
                    ┌───────────────────┴───────────────────┐
                    │           Router (Confidence Check)    │
                    │    <70% → Telegram confirmation       │
                    └───────────────────┬───────────────────┘
                                        ↓
        ┌───────────────┬───────────────┼───────────────┬───────────────┐
        ▼               ▼               ▼               ▼               ▼
    [Integrations] [Build Tasks] [Background    [Service       [Fallback]
                    │           │     Orchestrator]  Router        │
                    │           │           │               │          │
            Claude Code   Cheap Probes  →  Expensive    AI Services  Telegram
            (GLM/Opus)    + Escalation     Reasoning    Dispatch     Universal
```

## 5. BACKGROUND ORCHESTRATOR

### Philosophy: "Gather signal cheap, reason expensive"

Penny runs cheap probes automatically while you're away and only escalates to expensive LLM reasoning when confidence thresholds are met.

### Available Probes

| Probe | Purpose | Cost |
|-------|---------|------|
| `probe_grep` | Search codebase with ripgrep | Free |
| `probe_file_read` | Read specific files | Free |
| `probe_api_check` | Health check URLs | Free |
| `probe_atlas` | Query knowledge base | Free |
| `probe_command` | Run safe diagnostic commands | Free |

### Escalation Logic

| Confidence | Action |
|------------|--------|
| ≥0.8 | Direct delivery (no reasoning) |
| ≥0.6 | Quick reasoning (cheap LLM) |
| <0.6 | Full reasoning (expensive LLM) |

### Configuration

```bash
PENNY_POLL_INTERVAL=30      # Poll interval in seconds
PENNY_HIGH_CONFIDENCE=0.8   # Threshold for direct delivery
PENNY_PROBE_TIMEOUT=30      # Probe timeout in seconds
```

## 6. SERVICE ROUTER

Penny dispatches to authenticated AI services without storing API keys:

| Service | Auth Method | Use Case |
|---------|-------------|----------|
| `claude` | CLI (Max plan) | Primary build execution |
| `gemini` | CLI (Google) | Alternative reasoning |
| `openrouter` | API key | Classification LLM |
| `glm` | Z.AI API | Cheap/fast builds (~$3/month) |

**Key Principle**: Penny never holds Anthropic API keys directly. Uses pre-authenticated CLIs or aggregator APIs.

## 7. CLAUDE CODE INTEGRATION

### Model Selection

| Condition | Model | Reason |
|-----------|-------|--------|
| Normal request | GLM-4.7 | Cheap ($3/month via Z.AI) |
| Keywords: critical, urgent, production, security | Opus | High-stakes |
| Confidence < 70% | Opus | Ambiguous needs smarts |
| Complexity: auth, payments, migrations | Opus | Complex architecture |

### Build Flow

1. Voice memo classified as "build"
2. **🔐 Approval request** sent via Telegram (inline buttons)
3. User taps **Approve** or **Reject** (5 min timeout → auto-reject)
4. Model selector chooses GLM or Opus
5. Service router dispatches to Claude CLI
6. Q&A via Telegram if needed (10 min timeout)
7. Auto-deployment to:
   - Static sites → penny-builds nginx
   - Backends → OCI-Dev systemd
8. URL sent via Telegram

### Security Gate

**No code runs without explicit approval.** This prevents:
- Accidental builds from misclassified voice memos
- Malicious builds if voice memo source is compromised
- Unexpected cost from complex builds

## 8. CURRENT STATE

### What Works
- ✅ Voice transcription (mlx-whisper on Mac mini)
- ✅ LLM classification (9 categories)
- ✅ All routing integrations (Google Keep, Jellyseerr, Apple apps, Telegram)
- ✅ Voice-to-build pipeline (GLM + Opus)
- ✅ Background orchestrator with probes
- ✅ Service router for AI dispatch
- ✅ Confidence-based routing (<70% → Telegram confirmation)
- ✅ Graceful degradation (all failures → Telegram)
- ✅ @PennyMoltBot (inbound + outbound Telegram)
- ✅ 24/7/365 operation (systemd)
- ✅ Direct watcher → Penny flow (no intermediary)

### What's In Progress
- 🔄 Home Assistant integration (backlog)

### What's Broken/Workarounds
- **Mac mini TCC**: Voice Memos in protected folder. Watcher copies to temp before transcribing.
- **Google Keep**: Uses unofficial API (gkeepapi), may break.

## 9. DEPLOYMENT

### Production (OCI-Dev)

```bash
# Location
100.126.13.70:8888 (Tailscale)
141.148.146.79:8888 (Public)

# Services
- Penny (8888) - Voice classification and routing
- @PennyMoltBot - Penny's Telegram bot (inbound + outbound)
- @PennyOCIBot - OpenClaw's bot (external dependency)

# Management
sudo systemctl status penny penny-telegram
journalctl -u penny -f
```

### Local Development

```bash
# Setup
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Run
PENNY_DB_PATH=./data/penny.db .venv/bin/uvicorn penny.main:app --reload --port 8000

# Test (111 tests)
.venv/bin/pytest -v
```

## 10. ENVIRONMENT VARIABLES

### Required
- `OPENROUTER_API_KEY` - Classification LLM
- `TELEGRAM_BOT_TOKEN` - Notifications + Q&A
- `TELEGRAM_CHAT_ID` - Your Telegram ID

### Build Integration
- `ZAI_API_KEY` - Z.AI GLM-4.7 access
- `ANTHROPIC_API_KEY` - Opus for critical builds (optional)
- `TELEGRAM_WEBHOOK_SECRET` - Webhook security

### Integrations
- `JELLYSEERR_URL`, `JELLYSEERR_API_KEY`
- `GOOGLE_KEEP_EMAIL`, `GOOGLE_KEEP_TOKEN`
- `MAC_MINI_HOST`, `MAC_MINI_USER`

### Orchestrator
- `PENNY_POLL_INTERVAL` - Background task poll interval (default: 30s)
- `PENNY_HIGH_CONFIDENCE` - Threshold for direct delivery (default: 0.8)
- `PENNY_PROBE_TIMEOUT` - Probe timeout (default: 30s)

## 11. IMPORTANT CONTEXT

- **Architecture**: Penny is a voice assistant layer built on top of OpenClaw. Penny handles voice-specific features (transcription, classification, routing) while OpenClaw provides the underlying AI agent platform.
- **Security model**: Defense-in-depth with Tailscale IP whitelist + build approval gate
- **Permission model**: `bypassPermissions` used AFTER explicit Telegram approval - safe because human-in-the-loop
- **Router pattern**: All integration failures cascade to Telegram as universal fallback
- **Confidence routing**: <70% triggers Telegram confirmation before routing
- **Service router**: Penny never stores Anthropic API keys directly - uses authenticated CLIs or aggregator APIs
- **Background orchestrator**: Implements "gather signal cheap, reason expensive" pattern
- **Z.AI**: Provides Anthropic-compatible API at ~$3/month for simple builds
- **OpenClaw**: v2026.1.27 hardened against prompt injection (DM allowlist, fail-closed auth)
- **Database path**: Configurable via `PENNY_DB_PATH` (defaults to `/app/data/penny.db` for Docker, `./data/penny.db` for local)
- **Web UI**: Server-rendered HTML with HTMX for interactions

### Security Controls (v2.1)

| Control | Implementation | Bypass |
|---------|---------------|--------|
| Tailscale IP whitelist | `TailscaleIPMiddleware` in main.py | `PENNY_TAILSCALE_ONLY=false` |
| Build approval gate | `request_build_approval()` in claude_code.py | None - always required |
| File permissions | chmod 600 on .env, data/*.db | Manual chmod |
| Approval timeout | 5 min default | `PENNY_BUILD_APPROVAL_TIMEOUT=N` |

## 12. DATABASE SCHEMA

### Tables

| Table | Purpose |
|-------|---------|
| `items` | Voice memo classifications (id, text, classification, confidence, routed_to, status) |
| `background_tasks` | Orchestrator task state (id, type, status, probe_results, confidence) |
| `claude_sessions` | Build execution tracking (id, prompt, model, status, result) |
| `learned_preferences` | Preferences learned from builds |
| `pending_questions` | Telegram Q&A state |
| `pending_approvals` | Build approval requests (id, build_id, transcript, status, approved) |

## 13. API ENDPOINTS

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI (HTMX) |
| `/health` | GET | Health check |
| `/api/ingest` | POST | Receive transcribed text, classify, route |
| `/api/items` | GET | List all items |
| `/api/items/{id}/reclassify` | POST | Change classification |
| `/api/items/{id}/confirm` | POST | Confirm pending classification |
| `/api/telegram/webhook` | POST | Telegram callback for build Q&A |
| `/api/tasks/background` | POST | Create background task |
| `/api/orchestrator/status` | GET | Check orchestrator state |
