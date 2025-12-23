<!-- ONE_SHOT v5.5 -->
# IMPORTANT: Read AGENTS.md - it contains skill and agent routing rules.
#
# Skills (synchronous, shared context):
#   "build me..."     → oneshot-core
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

## Project Overview

Penny is a voice assistant that receives transcribed voice memos, classifies them using an LLM, and routes them to appropriate homelab services (Google Keep, Jellyseerr, Telegram, Home Assistant, Apple Reminders, Apple Calendar, Apple Notes).

**Key Features:**
- Confidence-based routing: Low confidence (<70%) items are sent to Telegram for confirmation before routing
- 8 classification categories with graceful fallback to Telegram
- Apple integrations via AppleScript over SSH to Mac mini

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

- **`penny/main.py`**: FastAPI app with HTMX web UI. Endpoints: `/api/ingest` (receive transcriptions), `/api/items` (list items), `/api/items/{id}/reclassify` (manual reclassification), `/api/items/{id}/confirm` (confirm pending items)

- **`penny/classifier.py`**: Two-tier classification: LLM via OpenRouter (`google/gemini-2.5-flash-lite`) with keyword fallback. Returns JSON with classification, confidence score, and extracted routing data.

- **`penny/router.py`**: Dispatches to integrations based on classification. Implements confidence-based routing (sends low-confidence items to Telegram for confirmation) and graceful degradation—all routes fall back to Telegram on failure.

- **`penny/database.py`**: Async SQLite via aiosqlite. Database stored at `/app/data/penny.db`

- **`watcher/watcher.py`**: Standalone script for Mac mini. Watches iCloud Voice Memos folder, transcribes with mlx-whisper, POSTs to Penny.

### Integrations (`penny/integrations/`)

| Integration | Category | Notes |
|-------------|----------|-------|
| `google_keep.py` | shopping | Uses unofficial gkeepapi, requires master token auth |
| `jellyseerr.py` | media | Searches and requests movies/TV shows |
| `telegram.py` | work (+ fallback) | Universal fallback for all failed routes + confirmations |
| `reminders.py` | reminder | Apple Reminders via AppleScript over SSH |
| `calendar.py` | calendar | Apple Calendar via AppleScript over SSH |
| `notes.py` | notes | Apple Notes via AppleScript over SSH |

### Classification Categories

- `shopping` → Google Keep list
- `media` → Jellyseerr request
- `work` → Telegram notification
- `smart_home` → Home Assistant (not yet implemented)
- `reminder` → Apple Reminders
- `calendar` → Apple Calendar (with natural language date parsing via dateparser)
- `notes` → Apple Notes (daily note append or new note)
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
```

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

# Run all tests (52 tests)
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
