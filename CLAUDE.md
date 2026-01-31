<!-- ONE_SHOT v6.0 -->
# IMPORTANT: Read AGENTS.md - it contains skill and agent routing rules.
#
# Skills (synchronous, shared context):
#   "build me..."     → front-door
#   "plan..."         → create-plan
#   "implement..."    → implement-plan
#   "debug/fix..."    → debugger
#   "deploy..."       → push-to-cloud
#   "ultrathink..."   → thinking-modes
#   "beads/ready..."  → beads (persistent tasks)
#
# Agents (isolated context, background):
#   "security audit..." → security-auditor
#   "explore/find all..." → deep-research
#   "background/parallel..." → background-worker
#   "coordinate agents..." → multi-agent-coordinator
#
# Always update TODO.md as you work.
<!-- /ONE_SHOT -->
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Relationship to OpenClaw

Penny is a **voice assistant layer built on top of OpenClaw**:

- **Penny** (this repo): Voice memos → transcription → classification → routing
- **OpenClaw** (separate project): AI agent platform with skills/integrations

Think of Penny as a specialized "voice interface" that uses OpenClaw as its AI engine.

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

## Project Overview

**About This Project**: This repository contains **Penny**, a voice assistant layer built on top of OpenClaw. Penny handles transcribed voice memos, classification, and routing to homelab services.

**Penny Features:**
- **Penny**: Voice assistant (transcribe → classify → route)
- **Build Pipeline**: Voice-to-code via Claude Agent SDK
- **Background Orchestrator**: Cheap probes + expensive reasoning
- **Telegram Integration**: Two bots (@PennyMoltBot for voice, @PennyOCIBot for general AI)

Penny receives transcribed voice memos, classifies them using an LLM, and routes them to appropriate homelab services (Google Keep, Jellyseerr, Telegram, Home Assistant, Apple Reminders, Apple Calendar, Apple Notes).

**Core Philosophy:** "Gather signal cheap, reason expensive."

Penny runs cheap probes in the background while you're away, accumulates findings, and only escalates to expensive LLM reasoning when confidence thresholds are met.

**Key Features:**
- **Background Orchestrator**: Runs cheap probes (grep, file reads, API checks, Atlas queries) automatically
- **Confidence-based escalation**: High (≥0.8) → deliver, Medium (≥0.6) → quick reasoning, Low → full reasoning
- Confidence-based routing: Low confidence (<70%) items are sent to Telegram for confirmation before routing
- 9 classification categories with graceful fallback to Telegram
- Voice-to-build pipeline via Claude Code (GLM-4.7 or Opus)
- Apple integrations via AppleScript over SSH to Mac mini

**Deployment:**
- Runs as systemd service on OCI Dev (100.126.13.70:8888)
- Mac mini acts as transcription relay only

## Commands

```bash
# Run locally (development)
PENNY_DB_PATH=./data/penny.db uvicorn penny.main:app --reload --host 0.0.0.0 --port 8000

# Build and run with Docker
docker build -t penny .
docker run -p 8000:8000 -v $(pwd)/data:/app/data penny

# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run watcher on Mac mini (requires mlx-whisper)
pip install mlx-whisper watchdog requests
python watcher/watcher.py
```

## Architecture

### Data Flow
```
Voice Memo (iCloud) → Mac mini watcher → mlx-whisper transcription → Penny API
    → LLM classifier (OpenRouter/Gemini) → Router → External services
```

### Core Components

- **`penny/main.py`**: FastAPI app with HTMX web UI. Endpoints: `/api/ingest` (receive transcriptions), `/api/items` (list items), `/api/items/{id}/reclassify` (manual reclassification), `/api/items/{id}/confirm` (confirm pending items), `/api/tasks/background` (create background tasks), `/api/orchestrator/status` (check orchestrator)

- **`penny/classifier.py`**: Two-tier classification: LLM via OpenRouter (`google/gemini-2.5-flash-lite`) with keyword fallback. Returns JSON with classification, confidence score, and extracted routing data.

- **`penny/router.py`**: Dispatches to integrations based on classification. Implements confidence-based routing (sends low-confidence items to Telegram for confirmation) and graceful degradation—all routes fall back to Telegram on failure. Supports `background=True` to queue tasks for async processing.

- **`penny/database.py`**: Async SQLite via aiosqlite. Includes `items` table and `background_tasks` table for orchestrator state.

- **`watcher/watcher.py`**: Standalone script for Mac mini. Watches iCloud Voice Memos folder, transcribes with mlx-whisper, POSTs to Penny at OCI Dev.

### Orchestrator (`penny/orchestrator/`)

The background orchestrator implements the "gather signal cheap, reason expensive" pattern:

- **`loop.py`**: `BackgroundOrchestrator` class - polls for pending tasks, runs probes, escalates when ready
- **`probes.py`**: Cheap information-gathering probes:
  - `probe_grep` - Search codebase with ripgrep
  - `probe_file_read` - Read specific files
  - `probe_api_check` - Health check URLs
  - `probe_atlas` - Query knowledge base
  - `probe_command` - Run safe diagnostic commands
- **`escalation.py`**: Confidence-based escalation to expensive reasoning

### Service Router (`penny/service_router.py`)

Routes to external LLMs without API keys in Penny:
- Claude CLI dispatch (uses Max plan credentials)
- Gemini CLI dispatch
- OpenRouter HTTP API
- GLM HTTP API

### Integrations (`penny/integrations/`)

| Integration | Category | Notes |
|-------------|----------|-------|
| `google_keep.py` | shopping | Uses unofficial gkeepapi, requires master token auth |
| `jellyseerr.py` | media | Searches and requests movies/TV shows |
| `telegram.py` | work (+ fallback) | Universal fallback for all failed routes + confirmations |
| `reminders.py` | reminder | Apple Reminders via AppleScript over SSH |
| `calendar.py` | calendar | Apple Calendar via AppleScript over SSH |
| `notes.py` | notes | Apple Notes via AppleScript over SSH |
| `claude_code.py` | build | Voice-to-project via Claude Agent SDK |
| `telegram_qa.py` | build | Q&A with user during builds |

### Classification Categories

- `shopping` → Google Keep list
- `media` → Jellyseerr request
- `work` → Telegram notification
- `smart_home` → Home Assistant (not yet implemented)
- `reminder` → Apple Reminders
- `calendar` → Apple Calendar (with natural language date parsing via dateparser)
- `notes` → Apple Notes (daily note append or new note)
- `build` → Claude Code (GLM-4.7 for simple, Opus for critical builds)
- `personal` → Stored in Penny only

## Environment Variables

```bash
PENNY_DB_PATH           # SQLite path (default: /app/data/penny.db, use ./data/penny.db for local dev)
PENNY_CONFIDENCE_THRESHOLD  # Confidence threshold for confirmation (default: 0.7)
OPENROUTER_API_KEY      # LLM classification (optional, falls back to keywords)
TELEGRAM_BOT_TOKEN      # Required for work routing + fallback
TELEGRAM_CHAT_ID
JELLYSEERR_URL          # e.g., http://jellyseerr:5055
JELLYSEERR_API_KEY
GOOGLE_KEEP_EMAIL
GOOGLE_KEEP_TOKEN       # Master token from gkeepapi auth
GOOGLE_KEEP_SHOPPING_LIST  # Default: "Shopping"

# Apple integrations (via SSH to Mac mini)
MAC_MINI_HOST           # Default: macmini
MAC_MINI_USER           # Default: macmini
PENNY_REMINDERS_LIST    # Default: Reminders
PENNY_CALENDAR          # Default: Calendar
PENNY_NOTES_FOLDER      # Default: Penny

# Orchestrator settings
PENNY_POLL_INTERVAL     # Background task poll interval in seconds (default: 30)
PENNY_HIGH_CONFIDENCE   # Threshold for direct delivery (default: 0.8)
PENNY_PROBE_TIMEOUT     # Probe timeout in seconds (default: 30)

# Service router
PENNY_CLAUDE_CLI        # Path to claude CLI (default: claude)
ATLAS_URL               # Atlas API URL for knowledge base queries
ATLAS_DB_PATH           # Atlas DB path for direct library import
```

## Security Architecture

Penny (on top of OpenClaw) implements defense-in-depth security with multiple protection layers:

1. **Network Layer** - Tailscale IP whitelist (100.x.x.x CGNAT range)
2. **Approval Gate** - Build approvals require explicit Telegram confirmation
3. **Webhook Security** - Telegram webhook validates secret token
4. **Audit Trail** - All approvals tracked in database with timestamps
5. **Fail-Secure Defaults** - Timeouts reject, Tailscale defaults to enabled

### Configuration

```bash
# Network security
PENNY_TAILSCALE_ONLY=true  # Default: true (Tailscale-only access)

# Webhook security
TELEGRAM_WEBHOOK_SECRET=xxx  # Required for webhook endpoint

# Build approval
PENNY_BUILD_APPROVAL_TIMEOUT=300  # Default: 300 seconds (5 minutes)
```

### Security Posture

- No API key storage (uses parent Claude Code credentials)
- No code execution without approval
- All requests logged with client IP
- Graceful degradation on Telegram failures

**See `docs/ADR-002-openclaw-security-hardening.md` for full security architecture documentation.**

## Key Patterns

- Router pattern: each integration failure cascades to `send_telegram()` as universal fallback
- LLM classifier extracts structured data alongside classification (e.g., shopping items, movie titles)
- Database path configurable via `PENNY_DB_PATH` (defaults to `/app/data/penny.db` for Docker)
- Web UI is server-rendered HTML with HTMX for interactions

## Testing

```bash
# Create venv and install deps
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]" pytest-asyncio requests httpx

# Run all tests (111 tests)
.venv/bin/pytest -v
```

## Setup Checklist

**See TODO.md for detailed setup tasks.** Quick reference:

### 1. Apple Integrations (Mac mini) - ONE TIME
```bash
# Connect via Screen Sharing (vnc://macmini) and run:
~/penny/grant_permissions.sh
# Approve all permission dialogs that appear
```

### 2. Google Keep - ONE TIME
```bash
# On Penny server:
pip install gkeepapi
python scripts/setup_google_keep.py
# Follow prompts, requires App Password from https://myaccount.google.com/apppasswords
```

### 3. Required Environment Variables
See `.env.example` for full list. Minimum required:
- `OPENROUTER_API_KEY` - LLM classification
- `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` - Notifications/fallback

### Integration Status

| Integration | Setup Script | Status |
|-------------|--------------|--------|
| Telegram | Create bot via @BotFather | Required |
| Google Keep | `scripts/setup_google_keep.py` | Optional |
| Apple Reminders | `~/penny/grant_permissions.sh` on Mac mini | Optional |
| Apple Calendar | `~/penny/grant_permissions.sh` on Mac mini | Optional |
| Apple Notes | `~/penny/grant_permissions.sh` on Mac mini | Optional |
| Jellyseerr | Just set env vars | Optional |
| Home Assistant | Not yet implemented | Backlog |
