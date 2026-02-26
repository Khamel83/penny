# Handoff: Code Review Fixes + Deploy

**Created**: 2026-02-25 19:28
**Context Used**: ~low (session ending cleanly)

## Quick Summary
Ran a full three-pass code review on the Penny codebase. Found and fixed three real bugs, pushed to remote, rsynced to Mac mini, and restarted all three services. All services confirmed running clean.

## What's Done
- [x] Full code review (3-pass: safety, design, tests)
- [x] Fix: `sqlite3.connect(timeout=5.0)` on all 3 DB calls in `watcher.py` (commit: 329e355)
- [x] Fix: Gate Telegram credential check on `telegram_enabled` in `check_dependencies()` (commit: 329e355)
- [x] Fix: Remove `safe_body = f"{safe_text}"` no-op in `reminders.add_note` (commit: 329e355)
- [x] Pushed to `origin/main`
- [x] Rsynced to `macmini:/Users/macmini/penny/`
- [x] Restarted all 3 launchd services (watcher, webhook, tasks)
- [x] Verified clean logs — no errors, no spurious warnings

## Not Started (Remaining review suggestions, lower priority)
- [ ] Deduplicate `CATEGORY_EMOJI` (defined identically in watcher.py, server.py, tasks_poller.py)
- [ ] Deduplicate `build_result_message` and `send_telegram` (watcher.py ↔ server.py)
- [ ] Rename `startup_process_limit` → `max_files_per_cycle` (misleading name, used every poll)
- [ ] Chunked `get_file_hash` to avoid reading 50MB files fully into memory
- [ ] Document/mitigate race condition between watcher.py and webhook's watchdog (duplicate reminder risk)

## Active Files
- `watcher.py` — fixed, deployed
- `reminders.py` — fixed, deployed
- No files left in a partial state

## Key Decisions Made
1. **sqlite timeout=5.0**: Chosen over WAL mode (we don't own the DB; readonly open would be ideal but requires more changes)
2. **Telegram gate**: Added `cfg.notifications.telegram_enabled` guard in `check_dependencies()` rather than suppressing in `env()` — keeps the fix surgical
3. **safe_body removal**: Used `safe_text` directly in the f-string; variable was a literal no-op

## Important Discoveries
- All 3 services start cleanly with no errors after fixes
- Google OAuth token auto-refreshed during the session (19:15) — token handling is solid
- `telegram_enabled = false` in config.toml — Telegram notifications intentionally off
- Last processed voice memo PK = 240; 5 files on disk
- watcher.py `check_dependencies` was previously always logging ERROR for missing Telegram creds even when disabled — now silent

## Current State (Mac Mini)
- All 3 services running (launchctl exit code 0)
- watcher: polling every 60s, PK=240
- webhook: Flask up on 0.0.0.0:5678
- tasks: polling every 180s, connected to Google Tasks "My Tasks"

## Next Steps (if resuming)
1. **Optional cleanup**: Deduplicate CATEGORY_EMOJI + Telegram helpers into a shared module
2. **Optional**: Rename `startup_process_limit` to `max_files_per_cycle`
3. **No urgent work** — system is stable and set-and-forget

## Resume
/restore @thoughts/shared/handoffs/2026-02-25-code-review-fixes-handoff.md
