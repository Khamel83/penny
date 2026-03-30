# Penny

Penny is intelligent middleware between voice and Apple's native apps.

You speak naturally — to your phone, or a device sitting on the counter — and Penny figures out what you meant, routes it to the right place, and gets out of the way. Reminders go to Apple Reminders, sorted into the right list. Everything else goes to Apple Notes. Nothing gets lost.

```
Voice front-end  →  Penny (middleware)  →  Apple back-end
─────────────────────────────────────────────────────────
iPhone Voice Memo  →  transcribe + classify  →  Reminders / Notes
Google Home        →  classify             →  Reminders / Notes
```

---

## The architecture

**Front-ends** (how you speak to it):
- **iPhone Voice Memo** — record anything, hands-free, multiple items at once
- **Google Home** — add to "My Tasks", give any time when prompted

**Middleware** (Penny, running on an always-on Apple Silicon Mac):
- Transcribes audio locally with Whisper (no cloud, no cost)
- Classifies free-form speech into actionable items using an LLM
- Routes each item to the right Apple list

**Back-end** (Apple's native apps, synced to all your devices via iCloud):
- **Apple Reminders** — for actionable items, sorted by category
- **Apple Notes** (Penny folder) — for everything else: thoughts, observations, things that aren't tasks

---

## Routing

| What you say | Where it goes |
|---|---|
| "get milk, eggs, sausages" | Reminders → Groceries |
| "call dentist, pick up dry cleaning" | Reminders → Health, Errands |
| "fix the leaky faucet" | Reminders → Home |
| "expense report due Friday" | Reminders → Work |
| "the weather today is beautiful" | Notes → Penny folder |
| Any pure thought or observation | Notes → Penny folder |

Reminders lists: Groceries, Errands, Home, Health, Work, Kids, Inbox

One input can produce multiple routed items — "get milk, call dentist, fix faucet" becomes three reminders in three different lists.

---

## Google Home constraint — read this before touching anything

> **⚠️ This is the only way it works. Do not change it.**
>
> Google Home will only write to the default Google Tasks list, which must be named **"My Tasks"**.
> Google locked down every other integration path between 2022 and 2023 — custom list names,
> third-party apps, IFTTT variable capture — all gone. "My Tasks" is the one shot.
> If you rename it, the integration breaks with no workaround.

Voice command: **"Hey Google, add [items] to my tasks"** — give any time when prompted. The time is discarded; it's just Google's required prompt. Items are crossed off automatically after Penny processes them.

---

## Services (running on Mac Mini as launchd agents)

| Service | File | What it does |
|---------|------|-------------|
| `com.penny.watcher` | `watcher.py` | Polls iCloud Voice Memos every 60s |
| `com.penny.tasks` | `tasks_poller.py` | Polls Google Tasks every 3 min |
| `com.penny.webhook` | `webhook/server.py` | HTTP server on port 5678 for direct uploads |

---

## Configuration

Non-secret settings live in `config.toml`. The key ones:

```toml
[notifications]
telegram_enabled = false   # true to turn Telegram back on, false to silence it
                           # The code and credentials stay either way

[google_tasks]
list_name = "My Tasks"     # Do not change — see Google Home constraint above

[apple_reminders]
lists = ["Groceries", "Errands", "Home", "Health", "Work", "Kids", "Inbox"]
default_list = "Inbox"
```

After changing `config.toml`, rsync it to the Mac and restart the affected service:

```bash
rsync -av config.toml macmini:/Users/macmini/penny/
ssh macmini "launchctl unload ~/Library/LaunchAgents/com.penny.watcher.plist && launchctl load ~/Library/LaunchAgents/com.penny.watcher.plist"
```

---

## Operations

```bash
# Check all services are running (exit code 0 = healthy)
ssh macmini "launchctl list | grep penny"

# View logs
ssh macmini "tail -f ~/.penny/logs/watcher.log"
ssh macmini "tail -f ~/.penny/logs/tasks.log"
ssh macmini "tail -f ~/.penny/logs/webhook.log"

# Restart a service
ssh macmini "launchctl stop com.penny.SVCNAME && launchctl start com.penny.SVCNAME"
```

### Automated health monitoring

A GitHub Actions workflow (`.github/workflows/health-check.yml`) runs daily at 9am UTC on a
self-hosted runner (`oci-dev`). It SSHes into macmini and checks:
- All 3 services have a running PID
- Watcher log updated in the last 15 minutes
- Tasks poller connected to Google Tasks

If any check fails, GitHub sends an email. No emails = everything is healthy.

The runner is installed as a systemd service on oci-dev:
```bash
sudo systemctl status actions.runner.Khamel83-penny.oci-dev.service
```

## Deploy from repo

```bash
python3 scripts/trust_check.py

rsync -av --exclude='.git' --exclude='__pycache__' --exclude='venv' \
  /path/to/penny/ macmini:/Users/macmini/penny/

ssh macmini "for svc in watcher webhook tasks; do
  launchctl unload ~/Library/LaunchAgents/com.penny.\${svc}.plist
  launchctl load ~/Library/LaunchAgents/com.penny.\${svc}.plist
done"
```

`scripts/trust_check.py` is the pre-deploy sanity gate (compile, config invariants, launchd template checks, unit tests).

---

## Requirements

- **Mac** — required for AppleScript access to Reminders and Notes. This repo uses MLX-based Whisper (Apple Silicon only), but any Whisper backend would work on Intel if you swap it out. An always-on Mac Mini is the natural fit.
- macOS with Homebrew
- Python 3.11+
- ffmpeg (`brew install ffmpeg`)
- Always-on (Mac Mini recommended)

```bash
pip install mlx-whisper requests watchdog flask \
  google-api-python-client google-auth-httplib2 google-auth-oauthlib tomli
```

---

## Setup

### Environment variables (set in launchd plists)

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | LLM classification via OpenRouter |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token (kept even when notifications off) |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `GOOGLE_CREDENTIALS_FILE` | Path to Google OAuth credentials JSON |
| `GOOGLE_TOKEN_FILE` | Path to Google OAuth token JSON |

Plist templates with placeholders: `launchd/*.plist.template`

### One-time macOS permissions

Two approvals required, each permanent after the first:

1. **System Settings → Privacy & Security → Automation → Python → Reminders** ✓
2. **System Settings → Privacy & Security → Automation → Python → Notes** ✓

### Google Tasks setup

OAuth credentials and token live at `~/.penny/` on the Mac.

Google Cloud project `neon-feat-488623-u3` (Penny), Tasks API enabled.
**The app is published (Production mode)** — refresh tokens do not expire.

To re-authorize (should never be needed again): run `scripts/google_auth.py` on the Mac.

> **Why "Testing" mode kills the token every 7 days:** Google limits refresh token lifetime for apps
> in Testing mode. Publishing the app (APIs & Services → OAuth consent screen → Publish App) removes
> this restriction. The app does not need Google verification for personal use.

---

## Runtime state (Mac Mini, never commit these)

| File | Purpose |
|------|---------|
| `~/.penny/logs/` | Service logs |
| `~/.penny/last_pk.txt` | Last processed voice memo — do not delete |
| `~/.penny/processed.txt` | Processed memo hashes (deduplication) |
| `~/.penny/synced_tasks.txt` | Processed Google Tasks IDs (deduplication) |
| `~/.penny/google_token.json` | Google OAuth token (auto-refreshes) |
| `~/.penny/google_credentials.json` | Google OAuth app credentials |
