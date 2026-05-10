# LLM Overview — penny
*Updated: 2026-05-10 07:35 UTC | Tier: standard | Auto-updated: daily cron*

## What This Is
Penny is voice capture middleware for Apple's native apps.

## Current State
*Status: 🟢 active from local git history*

**Active work:**
- 39db8ce feat: notify Hermes after Penny routing
- e87cadd fix: refresh stale voice memo metadata
- 350bdf0 fix(watcher): limit DB poll to recordings within last 7 days
- 654fc42 fix(webhook): normalize audio to WAV before Whisper transcription
- 125aa7e fix(webhook): accept any multipart field name or raw body from iOS Shortcuts
- 7cd625e docs: add public Tailscale Funnel URL for iOS shortcut

**Known issues:**
- ba0bd3a docs: document SSH mDNS fallback failure mode and CI health check fix

**Recent changes (7 days):**
- `39db8ce feat: notify Hermes after Penny routing`
- `e87cadd fix: refresh stale voice memo metadata`

## Architecture
- Stack marker: No explicit stack marker found.
- Top-level entry: `classifier.py`
- Top-level entry: `config.py`
- Top-level entry: `config.toml`
- Top-level entry: `core.py`
- Top-level entry: `docs/`
- Top-level entry: `launchd/`
- Top-level entry: `LLM-OVERVIEW.md`
- Top-level entry: `README.md`

## Key Commands
- `git status --short`
- `git log --oneline -5`

## Dependencies
- **Runs on:** Not declared in local repo evidence.
- **Calls out to:** See repo docs and config files.
- **Called by:** Not declared in local repo evidence.
- **Env vars required:** No `.env.example` keys found.

## Critical Rules
- Preserve repo-local instructions in `AGENTS.md`, `CLAUDE.md`, or README when present.
- Do not infer behavior from the repository name alone; verify against local docs and source.

## Gotchas
- Generated from local evidence only: git history, top-level structure, README/CLAUDE/AGENTS/docs, and env examples.
