# LLM Overview

> Context for any LLM working on this project. No secrets.

## What This Project Does
Penny is a voice assistant that receives transcribed voice memos from iCloud (via a Mac mini watcher), classifies them using an LLM, and routes them to appropriate homelab services (Google Keep for shopping, Jellyseerr for media requests, Telegram for work tasks, Home Assistant for smart home control).

## Tech Stack
- Language: Python 3.10+
- Framework: FastAPI + HTMX
- Database: SQLite (async via aiosqlite)
- Deployment: Docker on homelab
- LLM: OpenRouter (google/gemini-2.5-flash-lite)
- Transcription: mlx-whisper on Mac mini

## Project Structure
```
penny/
  main.py           # FastAPI app with HTMX web UI
  classifier.py     # LLM classification + keyword fallback
  router.py         # Dispatch to integrations based on category
  database.py       # Async SQLite storage
  models.py         # Pydantic models
  integrations/     # External service connectors
    telegram.py     # Telegram bot notifications
    jellyseerr.py   # Media request API
    google_keep.py  # Shopping list via gkeepapi
watcher/
  watcher.py        # Mac mini script - watches iCloud, transcribes, POSTs to Penny
tests/
  test_classifier.py  # 15 tests for classification logic
  test_router.py      # 15 tests for routing + fallback
  test_models.py      # 12 tests for Pydantic validation
static/
  style.css         # Web UI styles
```

## Key Files
| File | Purpose |
|------|---------|
| `CLAUDE.md` | Project instructions |
| `AGENTS.md` | Skill routing |
| `TODO.md` | Task tracking |
| `penny/classifier.py` | Classification logic |
| `penny/router.py` | Service routing + fallback |

## How to Run
```bash
# Development (local)
PENNY_DB_PATH=./data/penny.db uvicorn penny.main:app --reload --host 0.0.0.0 --port 8000

# Docker
docker build -t penny . && docker run -p 8000:8000 -v $(pwd)/data:/app/data penny

# Watcher (Mac mini)
python watcher/watcher.py

# Tests
.venv/bin/pytest -v
```

## Current State
- **Status**: In Development
- **Last Updated**: 2025-12-23

## Important Context
- Router uses graceful degradation: all integration failures fall back to Telegram
- Home Assistant integration is planned but not yet implemented
- Database path configurable via `PENNY_DB_PATH` env var (defaults to `/app/data/penny.db`)
- Google Keep uses unofficial gkeepapi requiring master token authentication
- 42 unit tests covering classifier, router, and models
