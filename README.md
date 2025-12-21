# Penny

> Your personal voice assistant - Named after Alfred Pennyworth (Batman's butler) and Penny from Inspector Gadget

Record voice memos on your iPhone/Apple Watch → see them transcribed and classified at `penny.khamel.com`.

## Architecture

```
iPhone/Watch → Voice Memo → iCloud → Mac mini → mlx-whisper → Penny (homelab) → Web UI
```

## Components

- **Penny Service** (this repo) - FastAPI + HTMX running on homelab
- **Watcher** (`watcher/`) - Mac mini script that transcribes and sends to Penny

## Quick Start

### Homelab (Docker)

```bash
docker compose up -d
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
| `/api/ingest` | POST | Receive transcribed text |
| `/api/items` | GET | List all items |
| `/api/items/{id}/reclassify` | POST | Change classification |
| `/health` | GET | Health check |

## Classification

Currently uses simple keyword matching:

- **shopping**: grocery, buy, pick up, store, list
- **work**: meeting, HR, project, deadline, client
- **personal**: remember, idea, thought, journal

Items that don't match are classified as **unknown**.

## License

MIT
