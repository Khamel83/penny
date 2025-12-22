# Penny

> Your personal voice assistant - Named after Alfred Pennyworth (Batman's butler) and Penny from Inspector Gadget

Record voice memos on your iPhone/Apple Watch → see them transcribed, classified, and **routed** to the right homelab service.

## Architecture

```
iPhone/Watch → Voice Memo → iCloud → Mac mini → mlx-whisper → Penny (homelab)
                                                                  ↓
                                            ┌─────────────────────┴─────────────────────┐
                                            │  LLM Router (Gemini 2.5 Flash via OpenRouter) │
                                            │  Classifies + Extracts structured data      │
                                            └─────────────────────┬─────────────────────┘
              ┌──────────────┬──────────────┬────────────────────┼────────────────┐
              ▼              ▼              ▼                    ▼                ▼
        ┌──────────┐  ┌──────────┐  ┌──────────────┐     ┌──────────┐     ┌──────────┐
        │  Google  │  │Jellyseerr│  │Home Assistant│     │ Telegram │     │  Penny   │
        │   Keep   │  │  Media   │  │  Smart Home  │     │   Bot    │     │  Storage │
        │ Shopping │  │ Requests │  │   Control    │     │  Tasks   │     │  Notes   │
        └──────────┘  └──────────┘  └──────────────┘     └──────────┘     └──────────┘
```

## Components

- **Penny Service** (this repo) - FastAPI + HTMX running on homelab
- **Watcher** (`watcher/`) - Mac mini script that transcribes with mlx-whisper
- **Integrations** (`penny/integrations/`) - External service connectors

## Categories & Routing

| Category | Keywords | Route | Example |
|----------|----------|-------|---------|
| **shopping** | grocery, buy, list | Google Keep | "Add milk and eggs to my shopping list" |
| **media** | movie, show, download | Jellyseerr | "Request the movie Dune" |
| **smart_home** | lights, thermostat | Home Assistant | "Turn off the bedroom lights" |
| **work** | meeting, deadline, remind | Telegram | "Remind me to email John tomorrow" |
| **personal** | idea, thought, note | Penny Storage | "Great idea for a new app feature" |

## Quick Start

### Homelab (Docker)

```bash
docker compose -f services/penny/docker-compose.yml up -d --build
```

### Environment Variables

```bash
# OpenRouter LLM (optional - falls back to keywords)
OPENROUTER_API_KEY=sk-or-v1-...

# Telegram (work tasks)
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# Jellyseerr (media requests)
JELLYSEERR_URL=http://jellyseerr:5055
JELLYSEERR_API_KEY=...

# Google Keep (shopping - requires gkeepapi auth)
GOOGLE_KEEP_EMAIL=...
GOOGLE_KEEP_TOKEN=...
GOOGLE_KEEP_SHOPPING_LIST=Shopping
```

### Mac mini Watcher

```bash
pip3 install mlx-whisper watchdog requests
python3 watcher/watcher.py
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI |
| `/api/ingest` | POST | Receive transcribed text, classify, and route |
| `/api/items` | GET | List all items |
| `/api/items/{id}/reclassify` | POST | Change classification |
| `/health` | GET | Health check |

## Classification

Penny uses a two-tier classification system:

1. **LLM Classification** (preferred) - Uses `google/gemini-2.5-flash-lite` via OpenRouter to:
   - Classify the memo into categories
   - Extract structured data (items list, movie title, task description, etc.)
   - Return JSON with routing instructions

2. **Keyword Fallback** - If LLM is unavailable or fails, falls back to keyword matching

## Graceful Degradation

When integrations fail, Penny falls back gracefully:
- Google Keep fails → Telegram notification
- Jellyseerr fails → Telegram notification
- Home Assistant fails → Telegram notification
- OpenRouter fails → Keyword-based classification

Telegram is the universal fallback - you'll always get your messages.

## License

MIT
