# LLM Overview

> Context for any LLM working on this project. No secrets.

## What This Project Does

Penny is a voice assistant that receives transcribed voice memos from iCloud (via a Mac mini watcher), classifies them using an LLM, and routes them to appropriate services:

- **Shopping** → Google Keep lists
- **Media** → Jellyseerr movie/TV requests
- **Reminders** → Apple Reminders (via Mac mini SSH)
- **Calendar** → Apple Calendar (via Mac mini SSH)
- **Notes** → Apple Notes (via Mac mini SSH)
- **Work** → Telegram notifications
- **Build** → Claude Code for autonomous project creation
- **Personal** → Stored in Penny

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.12 |
| Framework | FastAPI + HTMX |
| Database | SQLite (async via aiosqlite) |
| Deployment | Docker on homelab |
| Classification LLM | OpenRouter (gemini-2.5-flash-lite) |
| Build LLM | Z.AI GLM-4.7 / Anthropic Opus |
| Transcription | mlx-whisper on Mac mini |
| Public Access | Cloudflare Tunnel |

## Project Structure

```
penny/
  main.py              # FastAPI app with HTMX web UI + Telegram webhook
  classifier.py        # LLM classification + keyword fallback
  router.py            # Dispatch to integrations based on category
  database.py          # Async SQLite (items, sessions, preferences, questions)
  models.py            # Pydantic models
  model_selector.py    # GLM vs Opus selection logic for builds
  config/
    claude_code.py     # Build configuration constants
  integrations/
    telegram.py        # Telegram bot notifications
    telegram_qa.py     # Async Q&A for build clarifications
    jellyseerr.py      # Media request API
    google_keep.py     # Shopping list via gkeepapi
    reminders.py       # Apple Reminders via SSH
    calendar.py        # Apple Calendar via SSH
    notes.py           # Apple Notes via SSH
    claude_code.py     # Claude Code build execution
watcher/
  watcher.py           # Mac mini: watches iCloud, transcribes, POSTs to Penny
tests/
  test_*.py            # 87 tests covering all modules
data/
  omar-preferences.md  # User build preferences
docs/
  CLAUDE_CODE_SETUP.md # Build integration setup guide
```

## Key Files

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Project instructions for Claude |
| `AGENTS.md` | ONE_SHOT skill routing |
| `TODO.md` | Task tracking |
| `penny/model_selector.py` | Decides GLM vs Opus |
| `penny/integrations/claude_code.py` | Build execution |
| `data/omar-preferences.md` | User's tech stack preferences |

## Data Flow

```
Voice Memo → iCloud → Mac mini (watcher) → mlx-whisper transcription
                                                    ↓
                           Penny API (/api/ingest)
                                   ↓
              LLM Classifier (OpenRouter/Gemini)
                    ↓                        ↓
            [Normal Categories]        [Build Category]
                    ↓                        ↓
    ┌──────────────┴──────────┐       Model Selector
    ↓          ↓          ↓           ↓           ↓
  Keep    Jellyseerr   Apple    [Simple]     [Complex]
                       Apps         ↓           ↓
                               GLM-4.7       Opus
                               (Z.AI)     (Anthropic)
                                   ↓           ↓
                               Claude Code Execution
                                        ↓
                               Q&A via Telegram (if needed)
                                        ↓
                               Deliverables → User
```

## Claude Code Integration (NEW)

The "build" category enables voice-to-project creation:

### Model Selection Logic (`model_selector.py`)

| Condition | Model | Reason |
|-----------|-------|--------|
| Normal request | GLM-4.7 | Cheap ($3/month via Z.AI) |
| Keywords: critical, urgent, production, security | Opus | High-stakes |
| Confidence < 70% | Opus | Ambiguous request needs smarter model |
| Complexity: auth, payments, migrations | Opus | Complex architecture |

### Q&A Flow (`telegram_qa.py`)

When Claude Code needs clarification:
1. Question sent to Telegram via bot
2. User has 10 minutes to reply
3. Webhook receives answer and resumes build
4. Timeout → uses reasonable defaults

### Database Tables

| Table | Purpose |
|-------|---------|
| `items` | Voice memo classifications |
| `claude_sessions` | Build execution tracking |
| `learned_preferences` | Preferences learned from builds |
| `pending_questions` | Telegram Q&A state |

## How to Run

```bash
# Development (local)
PENNY_DB_PATH=./data/penny.db uvicorn penny.main:app --reload --port 8000

# Docker (homelab)
docker compose -f services/penny/docker-compose.yml up -d

# Watcher (Mac mini)
python watcher/watcher.py

# Tests (87 tests)
pytest -v
```

## Environment Variables

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

## Current State

- **Status**: Production
- **Last Updated**: 2025-12-25
- **Tests**: 87 passing
- **Categories**: 9 (shopping, media, work, personal, reminder, calendar, notes, smart_home, build)

## Important Context

- Router uses graceful degradation: all failures fall back to Telegram
- Confidence < 70% triggers Telegram confirmation before routing
- Claude Code builds run autonomously with optional Q&A
- Z.AI provides Anthropic-compatible API at ~$3/month
- Public access via Cloudflare Tunnel (penny.example.com)
