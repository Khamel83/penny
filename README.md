# Penny

> Your personal voice assistant - Named after Alfred Pennyworth (Batman's butler) and Penny from Inspector Gadget

Record voice memos on your iPhone/Apple Watch → see them transcribed, classified, and **routed** to the right service. Including autonomous project creation via Claude Code.

## Architecture

```
iPhone/Watch → Voice Memo → iCloud → Mac mini → mlx-whisper → Penny (homelab)
                                                                  ↓
                                            ┌─────────────────────┴─────────────────────┐
                                            │  LLM Router (Gemini 2.5 Flash via OpenRouter) │
                                            │  Classifies + Extracts structured data      │
                                            └─────────────────────┬─────────────────────┘
        ┌──────────┬──────────┬──────────┬──────────┬─────────────┼────────────┐
        ▼          ▼          ▼          ▼          ▼             ▼            ▼
   ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐  ┌──────────┐ ┌──────────┐
   │ Google │ │Jellys- │ │ Apple  │ │ Apple  │ │ Apple  │  │ Telegram │ │  Claude  │
   │  Keep  │ │  eerr  │ │Remind- │ │Calendar│ │ Notes  │  │   Bot    │ │   Code   │
   │Shopping│ │ Media  │ │  ers   │ │ Events │ │ Notes  │  │  Tasks   │ │  Builds  │
   └────────┘ └────────┘ └────────┘ └────────┘ └────────┘  └──────────┘ └──────────┘
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
2. **Select model** based on complexity:
   - Simple builds → GLM-4.7 via Z.AI (~$3/month)
   - Critical/complex → Claude Opus (when keywords like "production", "urgent", "auth")
3. **Execute** autonomously with your preferences
4. **Ask questions** via Telegram if needed (10 min timeout)
5. **Deliver** the finished project

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
# Create venv
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]" pytest-asyncio requests httpx

# Run server
PENNY_DB_PATH=./data/penny.db .venv/bin/uvicorn penny.main:app --reload --port 8000

# Run tests (87 tests)
.venv/bin/pytest -v
```

### Homelab (Docker)

```bash
# Build
docker build -t penny .

# Set data directory permissions (required for non-root container)
sudo chgrp -R 1001 ./data
sudo chmod -R g+w ./data

# Run
docker run -p 8000:8000 -v $(pwd)/data:/app/data penny
```

**Note**: The container runs as a non-root user (UID 1001) because Claude CLI refuses to run with elevated privileges. The data directory must be writable by this user.

## Environment Variables

```bash
# Required
OPENROUTER_API_KEY=sk-or-v1-...    # Classification LLM
TELEGRAM_BOT_TOKEN=...              # Notifications + Q&A
TELEGRAM_CHAT_ID=...                # Your Telegram ID

# Build Integration
ZAI_API_KEY=...                     # Z.AI GLM-4.7 (~$3/month)
ANTHROPIC_API_KEY=...               # Opus for critical builds (optional)
TELEGRAM_WEBHOOK_SECRET=...         # Webhook security

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
| `/` | GET | Web UI |
| `/api/ingest` | POST | Receive transcribed text, classify, and route |
| `/api/items` | GET | List all items |
| `/api/items/{id}/reclassify` | POST | Change classification |
| `/api/items/{id}/confirm` | POST | Confirm pending classification |
| `/api/telegram/webhook` | POST | Telegram callback for build Q&A |
| `/health` | GET | Health check |

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
  main.py              # FastAPI app
  classifier.py        # LLM + keyword classification
  router.py            # Category → integration routing
  model_selector.py    # GLM vs Opus selection
  database.py          # SQLite storage
  integrations/
    claude_code.py     # Build execution (SDK + CLI fallback)
    telegram_qa.py     # Async Q&A for builds
    telegram.py        # Notifications
    jellyseerr.py      # Media requests
    google_keep.py     # Shopping lists
    reminders.py       # Apple Reminders
    calendar.py        # Apple Calendar
    notes.py           # Apple Notes
watcher/
  watcher.py           # Mac mini transcription (with TCC workaround)
data/
  omar-preferences.md  # Build preferences
docs/
  CLAUDE_CODE_SETUP.md # Build integration setup + troubleshooting
```

## Mac mini Watcher

The watcher runs on a Mac mini and handles Voice Memo transcription via mlx-whisper.

**Important**: Voice Memos are in a macOS-protected folder. The watcher copies files to `~/penny/temp/` before transcribing because ffmpeg (used by mlx-whisper) cannot access protected folders when running as a launchd service.

## License

MIT
