# Penny

> Your personal voice assistant - Named after Alfred Pennyworth (Batman's butler) and Penny from Inspector Gadget

**Status**: Production | **Tier**: Cloud Runtime (OCI-Dev) | **Last Updated**: 2026-01-28 | **Security**: Tailscale-only + Build Approval Gate

Record voice memos on your iPhone/Apple Watch → see them transcribed, classified, and **routed** to the right service. Including autonomous project creation via Claude Code.

## Architecture

```
iPhone/Watch → Voice Memo → iCloud → Mac mini → mlx-whisper → Penny API (OCI-Dev:8888)
                                                                  ↓
                                            ┌─────────────────────┴─────────────────────┐
                                            │  LLM Router (Gemini 2.5 Flash via OpenRouter) │
                                            │  Classifies + Extracts structured data      │
                                            └─────────────────────┬─────────────────────┘
        ┌──────────┬──────────┬──────────┬──────────┬─────────────┼────────────┬──────────┐
        ▼          ▼          ▼          ▼          ▼             ▼            ▼          ▼
   ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐  ┌──────────┐ ┌──────────┐ ┌────────┐
   │ Google │ │Jellys- │ │ Apple  │ │ Apple  │ │ Apple  │  │ Telegram │ │  Claude  │ │ Atlas  │
   │  Keep  │ │  eerr  │ │Remind- │ │Calendar│ │ Notes  │  │   Bot    │ │   Code   │ │  KB    │
   │Shopping│ │ Media  │ │  ers   │ │ Events │ │ Notes  │  │  Tasks   │ │  Builds  │ │Queries │
   └────────┘ └────────┘ └────────┘ └────────┘ └────────┘  └──────────┘ └──────────┘ └────────┘
                                                                          ▲
                                                                          │
                                                                   ┌──────┴────────┐
                                                                   │ Background    │
                                                                   │ Orchestrator  │
                                                                   │ (Probes +      │
                                                                   │  Escalation)   │
                                                                   └───────────────┘
```

## Penny vs OpenClaw

| Layer | Repository | Purpose |
|-------|-----------|---------|
| Penny | This repo | Voice assistant (transcribe, classify, route) |
| OpenClaw | https://github.com/openclaw/openclaw | AI agent platform |

Penny extends OpenClaw with voice-specific capabilities. Think of Penny as a "voice interface" layer on top of the OpenClaw AI agent platform.

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

## Categories & Routing

| Category | Keywords | Route | Example |
|----------|----------|-------|---------|
| **shopping** | grocery, buy, list | Google Keep | "Add milk and eggs to my shopping list" |
| **media** | movie, show, download | Jellyseerr | "Request the movie Dune" |
| **reminder** | remind, remember, don't forget | Apple Reminders | "Remind me to call mom tomorrow" |
| **calendar** | meeting, appointment, schedule | Apple Calendar | "Schedule dentist appointment Friday 2pm" |
| **notes** | note, idea, thought | Apple Notes | "Note: great idea for a new feature" |
| **smart_home** | lights, thermostat | Home Assistant | "Turn off the bedroom lights" |
| **work** | meeting, deadline, email | Telegram | "Email John about the project update" |
| **build** | build me, create, deploy | Claude Code | "Build me a simple todo app" |
| **personal** | (default) | Penny Storage | "Random thought to save" |

## Claude Code Integration (Voice-to-Build)

Say "build me a website" and Penny will:

1. **Classify** the request as a build task
2. **🔐 Request approval** via Telegram (Approve/Reject buttons)
3. **Select model** based on complexity:
   - Simple builds → GLM-4.7 via Z.AI (~$3/month)
   - Critical/complex → Claude Opus (when keywords like "production", "urgent", "auth")
4. **Execute** autonomously with your preferences
5. **Ask questions** via Telegram if needed (10 min timeout)
6. **Deliver** the finished project

**Security**: Builds require explicit Telegram approval before any code runs. Auto-reject after 5 minutes if no response.

### Example Voice Commands

```
"Build me a simple landing page for my portfolio"
"Create a Python CLI tool that converts CSV to JSON"
"Critical: fix the production authentication bug"  ← Uses Opus
"Deploy a new FastAPI service to my homelab"
```

### Auto-Deployment

Builds are automatically deployed after completion:

| Build Type | Deployment | URL Pattern |
|------------|------------|-------------|
| Static (React/Vite) | penny-builds nginx | `<project>.builds.khamel.com` |
| Python backend | OCI-Dev systemd | `<project>.deer-panga.ts.net` |
| Node backend | OCI-Dev systemd | `<project>.deer-panga.ts.net` |

The final URL is sent to you via Telegram automatically.

## Quick Start

### Local Development

```bash
# Clone and setup
git clone https://github.com/Khamel83/penny.git
cd penny
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Run server
PENNY_DB_PATH=./data/penny.db .venv/bin/uvicorn penny.main:app --reload --port 8000

# Run tests (111 tests)
.venv/bin/pytest -v
```

### Production Deployment (systemd)

```bash
# Install to /home/ubuntu/penny
cd /home/ubuntu/penny

# Create systemd service (see deploy/penny.service)
sudo cp deploy/penny.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable penny
sudo systemctl start penny

# Verify
curl http://localhost:8888/health
```

**Production Deployment Notes**:
- Penny runs as systemd service on OCI-Dev (100.126.13.70:8888)
- Mac mini watcher sends transcriptions directly to Penny (port 8888)
- Database at `/home/ubuntu/github/penny/data/penny.db`
- Telegram bot: @PennyMoltBot (inbound + outbound)
- Logs via journald: `journalctl -u penny -f`

### Docker (Alternative)

```bash
# Build
docker build -t penny .

# Set data directory permissions (required for non-root container)
sudo chgrp -R 1001 ./data
sudo chmod -R g+w ./data

# Run
docker run -p 8000:8000 -v $(pwd)/data:/app/data penny
```

**Note**: The container runs as a non-root user (UID 1001) because Claude CLI refuses to run with elevated privileges.

## Environment Variables

```bash
# Required
OPENROUTER_API_KEY=sk-or-v1-...    # Classification LLM
TELEGRAM_BOT_TOKEN=8232682412:...   # @PennyMoltBot (Penny's bot)
TELEGRAM_CHAT_ID=7884781716         # Your Telegram ID

# Build Integration
ZAI_API_KEY=...                     # Z.AI GLM-4.7 (~$3/month)
ANTHROPIC_API_KEY=...               # Opus for critical builds (optional)
TELEGRAM_WEBHOOK_SECRET=...         # Webhook security

# Security Settings
PENNY_TAILSCALE_ONLY=true           # Restrict to Tailscale IPs (100.x.x.x)
PENNY_BUILD_APPROVAL_TIMEOUT=300    # Build approval timeout in seconds (default: 5 min)

# Integrations
JELLYSEERR_URL=http://jellyseerr:5055
JELLYSEERR_API_KEY=...
GOOGLE_KEEP_EMAIL=...
GOOGLE_KEEP_TOKEN=...
MAC_MINI_HOST=macmini               # For Apple integrations
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI (HTMX) |
| `/health` | GET | Health check |
| `/api/ingest` | POST | Receive transcribed text, classify, and route |
| `/api/items` | GET | List all items |
| `/api/items/{id}/reclassify` | POST | Change classification |
| `/api/items/{id}/confirm` | POST | Confirm pending classification |
| `/api/telegram/webhook` | POST | Telegram callback for build Q&A |
| `/api/tasks/background` | POST | Create background task (orchestrator) |
| `/api/orchestrator/status` | GET | Check orchestrator state |

## Classification

Penny uses a two-tier classification system:

1. **LLM Classification** (preferred) - Uses Gemini 2.5 Flash via OpenRouter to:
   - Classify the memo into 9 categories
   - Extract structured data (items, titles, dates, etc.)
   - Return confidence score

2. **Keyword Fallback** - If LLM is unavailable, falls back to keyword matching

3. **Confidence Routing** - Items with <70% confidence go to Telegram for confirmation

## Graceful Degradation

When integrations fail, Penny falls back gracefully:
- Any integration fails → Telegram notification
- OpenRouter fails → Keyword-based classification
- Z.AI fails → Telegram notification about build failure

Telegram is the universal fallback - you'll always get your messages.

## Project Structure

```
penny/
  main.py              # FastAPI app with HTMX web UI
  classifier.py        # LLM + keyword classification
  router.py            # Category → integration routing
  model_selector.py    # GLM vs Opus selection
  database.py          # Async SQLite storage
  service_router.py    # Dispatch to Claude/Gemini/GLM APIs
  orchestrator/
    loop.py           # Background task polling loop
    probes.py         # Cheap info-gathering (grep, files, APIs)
    escalation.py     # Confidence-based escalation
  integrations/
    claude_code.py     # Build execution (SDK + CLI fallback)
    telegram_qa.py     # Async Q&A for builds
    telegram.py        # Notifications + universal fallback
    jellyseerr.py      # Media requests
    google_keep.py     # Shopping lists
    reminders.py       # Apple Reminders
    calendar.py        # Apple Calendar
    notes.py           # Apple Notes
    atlas.py           # Knowledge base queries
    trojanhorse.py     # Secret scanning
watcher/
  watcher.py           # Mac mini transcription (with TCC workaround)
deploy/
  install.sh           # Production installation script
  penny.service        # systemd service file
data/
  omar-preferences.md  # Build preferences
docs/
  CLAUDE_CODE_SETUP.md # Build integration setup + troubleshooting
```

## Mac mini Watcher

The watcher runs on a Mac mini and handles Voice Memo transcription via mlx-whisper.

**Important**: Voice Memos are in a macOS-protected folder. The watcher copies files to `~/penny/temp/` before transcribing because ffmpeg (used by mlx-whisper) cannot access protected folders when running as a launchd service.

## Background Orchestrator

Penny implements a "gather signal cheap, reason expensive" pattern:

1. **Cheap Probes** run automatically while you're away:
   - `probe_grep` - Search codebases with ripgrep
   - `probe_file_read` - Read specific files
   - `probe_api_check` - Health check URLs
   - `probe_atlas` - Query knowledge base
   - `probe_command` - Run safe diagnostic commands

2. **Confidence-Based Escalation**:
   - High confidence (≥0.8) → Direct delivery
   - Medium confidence (≥0.6) → Quick reasoning
   - Low confidence → Full LLM reasoning

3. **Background Loop** polls every 30 seconds (configurable via `PENNY_POLL_INTERVAL`)

## Service Router

Penny routes AI requests to authenticated services without storing API keys:

| Service | Auth Method | Use Case |
|---------|-------------|----------|
| `claude` | CLI (Max plan) | Primary build execution |
| `gemini` | CLI (Google) | Alternative reasoning |
| `openrouter` | API key | Classification LLM |
| `glm` | Z.AI API | Cheap/fast builds (~$3/month) |

## Security Model

Penny implements defense-in-depth:

| Layer | Control | Description |
|-------|---------|-------------|
| **Network** | Tailscale IP whitelist | Only 100.x.x.x IPs can access API |
| **Build Gate** | Telegram approval | Explicit tap required before code runs |
| **File Permissions** | chmod 600 | Secrets readable only by owner |
| **Timeout** | Auto-reject | Unanswered build requests rejected after 5 min |
| **Audit Trail** | Database logging | All approvals tracked in `pending_approvals` table |

To disable Tailscale restriction (not recommended): `PENNY_TAILSCALE_ONLY=false`

## Known Limitations

- **Home Assistant**: Integration not yet implemented (backlog)
- **Apple Integrations**: Require Mac mini with SSH access + AppleScript permissions
- **Google Keep**: Uses unofficial API (gkeepapi), may break
- **OpenClaw Integration**: Requires OpenClaw services for extended agent capabilities

## License

MIT
