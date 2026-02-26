# Penny

Voice-to-reminders system. Speak naturally, items land in the right Apple Reminders list automatically.

## How It Works

### Input: Two ways to add items

**Google Home (kitchen, hands-free)**
```
"Hey Google, add milk eggs and sausages to my tasks"
→ give any time when prompted
→ items appear in Apple Reminders within 3 minutes
```

**iPhone Voice Memo**
```
Record a memo: "pick up dry cleaning, call dentist, get milk"
→ Penny transcribes and classifies automatically
→ items appear in Apple Reminders within 60 seconds
```

### What happens in between

1. LLM reads the text and extracts individual actionable items
2. Each item is classified into the right list
3. Items are added to Apple Reminders on the Mac Mini (iCloud syncs to your devices)
4. Telegram notification confirms what was added and where
5. Google Tasks item is marked complete automatically

### Routing

| Category | Examples |
|----------|---------|
| Groceries | milk, eggs, anything food/shopping |
| Errands | dry cleaning, post office, store visits |
| Home | repairs, cleaning, maintenance |
| Health | doctor, dentist, medications, exercise |
| Work | meetings, deadlines, professional tasks |
| Kids | school, activities, supplies |
| Inbox | anything that doesn't clearly fit above |

Pure non-reminders (journal thoughts, music ideas, random notes) are skipped — nothing added.

---

## Services (running on Mac Mini as launchd agents)

| Service | File | What it does |
|---------|------|-------------|
| `com.penny.watcher` | `watcher.py` | Polls iCloud Voice Memos every 60s |
| `com.penny.tasks` | `tasks_poller.py` | Polls Google Tasks every 3 min |
| `com.penny.webhook` | `webhook/server.py` | HTTP server on port 5678 for direct uploads |

---

## Operations

```bash
# Check all services
ssh macmini "launchctl list | grep penny"

# View logs
ssh macmini "tail -f ~/.penny/logs/watcher.log"
ssh macmini "tail -f ~/.penny/logs/tasks.log"
ssh macmini "tail -f ~/.penny/logs/webhook.log"

# Restart a service
ssh macmini "launchctl unload ~/Library/LaunchAgents/com.penny.watcher.plist && launchctl load ~/Library/LaunchAgents/com.penny.watcher.plist"
```

## Deploy from repo

```bash
rsync -av --exclude='.git' --exclude='__pycache__' --exclude='venv' \
  /home/ubuntu/github/penny/ macmini:/Users/macmini/penny/

# Restart all services
ssh macmini "for svc in watcher webhook tasks; do
  launchctl unload ~/Library/LaunchAgents/com.penny.\${svc}.plist
  launchctl load ~/Library/LaunchAgents/com.penny.\${svc}.plist
done"
```

---

## Configuration

Non-secret settings in `config.toml`. Secrets (API keys) are set as environment variables in the launchd plists.

Plist templates: `launchd/*.plist.template` — substitute secrets and deploy to `~/Library/LaunchAgents/` on Mac Mini.

Secrets stored encrypted at: `~/github/oneshot/secrets/penny.env.encrypted`

```bash
# Decrypt to view
SOPS_AGE_KEY_FILE=~/.age/key.txt sops --input-type dotenv --output-type dotenv \
  -d ~/github/oneshot/secrets/penny.env.encrypted
```

### Required environment variables (in plists)

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | LLM classification via OpenRouter |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `GOOGLE_CREDENTIALS_FILE` | Path to Google OAuth credentials JSON |
| `GOOGLE_TOKEN_FILE` | Path to Google OAuth token JSON |

---

## Google Tasks setup (one-time)

OAuth credentials and token live at:
- `~/.penny/google_credentials.json`
- `~/.penny/google_token.json`

To re-authorize: run `scripts/google_auth.py` and follow the console flow.

Google Cloud project needs Tasks API enabled.
App runs in Testing mode — your Google account must be listed as a test user in the OAuth consent screen.

---

## macOS TCC permission (one-time)

Python needs permission to write to Apple Reminders. Grant it once at:

**System Settings → Privacy & Security → Automation → Python → Reminders ✓**

This persists permanently — never needs to be done again.

---

## Runtime state (Mac Mini)

All runtime files live at `~/.penny/`:

| File | Purpose |
|------|---------|
| `logs/watcher.log` | Voice memo poller log |
| `logs/tasks.log` | Google Tasks poller log |
| `logs/webhook.log` | Webhook server log |
| `last_pk.txt` | Last processed voice memo (don't delete) |
| `processed.txt` | Processed memo IDs (deduplication) |
| `synced_tasks.txt` | Processed Google Tasks IDs (deduplication) |
| `google_token.json` | Google OAuth token (auto-refreshes) |
| `google_credentials.json` | Google OAuth app credentials |
