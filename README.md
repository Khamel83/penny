# Penny

Penny is voice capture middleware for Apple's native apps.

You speak naturally, Penny transcribes and routes it, and the result lands in Apple Reminders or Apple Notes. The primary flow is Apple Watch Voice Memos syncing to a Mac mini. The system is optimized for reliability over speed.

```
Voice front-end            →  Penny (middleware)  →  Apple back-end
────────────────────────────────────────────────────────────────────
Apple Watch Voice Memo     →  transcribe + classify  →  Reminders / Notes
Google Home                →  classify               →  Reminders / Notes
Clio routed item           →  classify               →  Reminders / Notes
```

---

Canonical documentation:
- `HANDOFF.md`
- `docs/README.md`
- `docs/reliability.md`
- `docs/macmini-deployment.md`
- `docs/troubleshooting.md`

---

## The architecture

**Front-ends** (how you speak to it):
- **Apple Watch Voice Memo** — primary input path, synced through Voice Memos/iCloud to the Mac mini
- **Google Home** — add to "My Tasks", give any time when prompted

**Middleware** (Penny, running on an always-on Apple Silicon Mac):
- Transcribes audio locally with Whisper (no cloud, no cost)
- Classifies free-form speech into actionable items using an LLM
- Routes each item to the right Apple list

**Back-end** (Apple's native apps, synced to all your devices via iCloud):
- **Apple Reminders** — for actionable items, sorted by category
- **Apple Notes** (Penny folder) — for everything else: thoughts, observations, things that aren't tasks

## Repo Map

- `watcher.py` — primary Apple Watch Voice Memos ingest path
- `transcript_log.py` — SQLite persistence, dedup, ingest state, retry metadata
- `core.py` — shared routing pipeline
- `classifier.py` — content-type detection and item extraction
- `reminders.py` — AppleScript bridge to Notes and Reminders
- `tasks_poller.py` — Google Home / Google Tasks ingest path
- `webhook/server.py` — optional direct-upload ingest path
- `scripts/` — auth, export, and validation helpers
- `launchd/` — launch agent templates for the Mac mini
- `docs/` — canonical product and operations documentation

---

## Routing

Clio should use Penny for Apple-side delivery instead of writing directly to Apple Notes or Reminders from OCI. Clio remains the ledger/router; Penny remains the Mac-side Apple bridge.

| What you say | Where it goes |
|---|---|
| "get milk, eggs, sausages" | Reminders → Groceries |
| "call dentist, pick up dry cleaning" | Reminders → Health, Errands |
| "fix the leaky faucet" | Reminders → Home |
| "expense report due Friday" | Reminders → Work |
| "the weather today is beautiful" | Notes → Penny folder |
| Any pure thought or observation | Notes → Penny folder |
| Short ambiguous memo | Notes → Penny folder + Reminders → Inbox |

Reminders lists: Groceries, Errands, Home, Health, Work, Kids, Inbox

One input can produce multiple routed items — "get milk, call dentist, fix faucet" becomes three reminders in three different lists.

Reliability rules:
- Voice Memos on Apple Watch is the primary ingest path.
- Memo duration is used as a soft routing signal, never a hard rule.
- Short ambiguous memos always go to Notes and also create an Inbox reminder with a timestamped excerpt.
- Reliability is prioritized over raw speed.

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
| `com.penny.watcher` | `watcher.py` | Polls iCloud Voice Memos every 60s, transcribes via Whisper, classifies and routes |
| `com.penny.tasks` | `tasks_poller.py` | Polls Google Tasks every 3 min, routes to Apple Reminders |
| `com.penny.webhook` | `webhook/server.py` | HTTP server on port 5678 for direct uploads and text ingestion |
| `com.penny.export` | `scripts/export_transcripts.py` | Dumps transcript history to JSON and rsyncs to homelab every 6h |

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

[voice_memos]
max_file_size_mb = 50
whisper_model = "mlx-community/whisper-large-v3-turbo"
poll_interval_seconds = 60
startup_process_limit = 5
```

After changing `config.toml`, rsync it to the Mac and restart the affected service:

```bash
rsync -av config.toml macmini:/Users/macmini/penny/
ssh macmini "launchctl kickstart -k gui/\$(id -u)/com.penny.watcher"
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
ssh macmini "launchctl kickstart -k gui/\$(id -u)/com.penny.SVCNAME"
```

### Automated health monitoring

A GitHub Actions workflow (`.github/workflows/health-check.yml`) runs daily at 9am UTC on a
self-hosted runner (`oci-dev`). It SSHes into macmini and checks:
- All services registered (count derived automatically from `launchd/*.plist.template` — no hardcoded number)
- Persistent services (watcher, tasks, webhook) have a running PID
- Watcher log updated in the last 15 minutes
- Tasks poller connected to Google Tasks
- VoiceMemos running (required for CloudKit sync)

Each check is **self-healing**: before failing, the workflow attempts to fix the problem
(restart the service via `launchctl kickstart`, relaunch VoiceMemos) and re-verifies.
Only if recovery fails does it exit non-zero and trigger a GitHub email.

No emails = everything is healthy.

The runner is installed as a systemd service on oci-dev:
```bash
sudo systemctl status actions.runner.Khamel83-penny.oci-dev.service
```

## Deploy from repo

```bash
python3.12 scripts/trust_check.py

rsync -av --exclude='.git' --exclude='__pycache__' --exclude='venv' \
  /path/to/penny/ macmini:/Users/macmini/penny/

ssh macmini "for svc in watcher webhook tasks; do
  launchctl kickstart -k gui/\$(id -u)/com.penny.\${svc}
done"
```

`scripts/trust_check.py` is the pre-deploy sanity gate — 7 checks: compile, duplicate entrypoints, sqlite3 leak detection, config invariants, launchd template keys, health-check.yml sync (verifies no hardcoded service count), and unit tests.

---

## Requirements

- **Mac** — required for AppleScript access to Reminders and Notes. This repo uses MLX-based Whisper (Apple Silicon only), but any Whisper backend would work on Intel if you swap it out. An always-on Mac Mini is the natural fit.
- macOS with Homebrew
- Python 3.11+
- ffmpeg (`brew install ffmpeg`)
- Always-on (Mac Mini recommended)

```bash
pip install -r requirements.txt
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
| `HERMES_WEBHOOK_URL` | Optional Hermes webhook endpoint; defaults to `http://100.126.13.70:7778/webhooks/penny` |
| `PENNY_WEBHOOK_SECRET` | Optional Hermes HMAC secret; if unset, Hermes notification is skipped |

Plist templates with placeholders: `launchd/*.plist.template`

Hermes notifications are best-effort. Penny signs each payload with
`X-Webhook-Signature` and a 3-second timeout. Penny continues routing normally
if Hermes is down, unreachable, or rejects the webhook.

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
| `~/.penny/transcripts.db` | SQLite transcript log — single source of truth for all transcriptions |
| `~/.penny/transcript_history.json` | Periodic JSON export (backed up to homelab) |
| `~/.penny/logs/` | Service logs |
| `~/.penny/last_pk.txt` | Last processed voice memo PK — do not delete |
| `~/.penny/health.txt` | Watcher health status (written every 5 min) |
| `~/.penny/health_tasks.txt` | Tasks poller health status |
| `~/.penny/google_token.json` | Google OAuth token (auto-refreshes) |
| `~/.penny/google_credentials.json` | Google OAuth app credentials |

Legacy dedup files (`processed.txt`, `processed_webhook.txt`, `synced_tasks.txt`) are still present but superseded by `transcripts.db`.
