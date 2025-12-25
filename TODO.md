# TODO

Project task tracking following [todo.md](https://github.com/todomd/todo.md) spec.

## Setup Required (One-Time)

### Apple Integrations (Mac mini)
- [ ] Connect to Mac mini via Screen Sharing (`vnc://macmini`)
- [ ] Run `~/penny/grant_permissions.sh` and approve permission dialogs
- [ ] Verify Reminders, Calendar, and Notes access works

### Google Keep Authentication
- [ ] Install gkeepapi: `pip install gkeepapi`
- [ ] Create App Password at https://myaccount.google.com/apppasswords
- [ ] Run `python scripts/setup_google_keep.py`
- [ ] Add `GOOGLE_KEEP_EMAIL` and `GOOGLE_KEEP_TOKEN` to environment

### Environment Variables (Penny Server)
- [ ] Set `OPENROUTER_API_KEY` for LLM classification
- [ ] Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` for notifications
- [ ] Set `JELLYSEERR_URL` and `JELLYSEERR_API_KEY` for media requests
- [ ] Deploy updated Penny with new environment variables

---

## Backlog
- [ ] Implement Home Assistant integration (`penny/integrations/home_assistant.py`)
- [ ] Add Telegram webhook to handle /confirm and /reclassify commands
- [ ] Consider moving Apple integrations to watcher (runs locally, better permissions)

## In Progress


## Done (2025-12-25 - Voice-to-Build Pipeline Fixed)
- [x] Fix watcher ffmpeg permission denied (temp copy workaround for macOS TCC)
- [x] Fix Claude CLI root privileges error (non-root user in Docker, UID 1001)
- [x] Fix missing `ps` command (added procps to Dockerfile)
- [x] Fix SDK empty output (class-based message type checking)
- [x] Fix database read-only (group permissions on mounted volume)
- [x] End-to-end voice-to-build pipeline verified working

## Done (Previous)
- [x] Claude Code integration (voice-to-build pipeline with Z.AI GLM-4.7 / Opus)
- [x] Add confidence-based routing with Telegram confirmation (<70%)
- [x] Add Apple Reminders integration via AppleScript
- [x] Add Apple Calendar integration via AppleScript
- [x] Add Apple Notes integration via AppleScript
- [x] Add dateparser for natural language date/time parsing
- [x] Create grant_permissions.sh script on Mac mini
- [x] Create setup_google_keep.py authentication helper
- [x] Add new categories: reminder, calendar, notes
- [x] Update .env.example with comprehensive documentation
- [x] Fix ReclassifyRequest validation - add `media` and `smart_home` to pattern
- [x] Add tests for classifier and router modules (52 tests)
- [x] Make database path configurable via `PENNY_DB_PATH` env var
- [x] LLM-powered classification via OpenRouter (Gemini 2.5 Flash)
- [x] Google Keep shopping list integration
- [x] Jellyseerr media request integration
- [x] Telegram notifications (+ universal fallback)
- [x] Mac mini watcher with mlx-whisper transcription
- [x] Watcher runs as launchd service with auto-retry
- [x] HTMX web UI

---
*Updated by OneShot skills. Say `(ONE_SHOT)` to re-anchor.*
