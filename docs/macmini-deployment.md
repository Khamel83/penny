# Penny Deployment on Mac Mini

## File Locations

### Service Files
```
/Users/macmini/penny/
├── watcher.py              # Voice memo poller + Whisper transcription + routing
├── tasks_poller.py         # Google Tasks poller → Apple Reminders
├── webhook/
│   └── server.py           # HTTP server for direct uploads and text ingestion
├── core.py                 # Shared pipeline, hashing, Telegram, logging
├── classifier.py           # LLM classification (OpenRouter)
├── reminders.py            # AppleScript interface to Reminders/Notes
├── transcript_log.py       # SQLite transcript database (dedup + history)
├── config.py               # Config loader (config.toml + env vars)
├── config.toml             # Non-secret settings
├── scripts/
│   ├── trust_check.py      # Pre-deploy validation
│   ├── google_auth.py      # Google OAuth setup
│   └── export_transcripts.py  # Periodic backup to homelab
├── launchd/                # plist templates (substitute secrets and deploy)
│   ├── com.penny.watcher.plist.template
│   ├── com.penny.webhook.plist.template
│   ├── com.penny.tasks.plist.template
│   └── com.penny.export.plist.template
├── tests/                  # Unit tests
└── venv/                   # Python virtual environment
```

### Runtime State
```
~/.penny/
├── transcripts.db          # SQLite DB — single source of truth for all transcriptions
├── transcript_history.json # JSON export (backed up to homelab every 6h)
├── last_pk.txt             # Last processed voice memo PK
├── health.txt              # Watcher health status (written every 5 min)
├── health_tasks.txt        # Tasks poller health status
├── google_token.json       # Google OAuth token (auto-refreshes)
├── google_credentials.json # Google OAuth app credentials
└── logs/
    ├── watcher.log         # Application log (rotating)
    ├── watcher.system.log  # launchd stdout/stderr
    ├── webhook.log
    ├── tasks.log
    └── export.system.log
```

### Voice Memos Directory
```
~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/
```
Contains: *.m4a files, CloudRecordings.db (iCloud Voice Memos database)

### Launchd Services
```
~/Library/LaunchAgents/com.penny.{watcher,webhook,tasks,export}.plist
```

## Services

| Service | File | Interval | Description |
|---------|------|----------|-------------|
| `com.penny.watcher` | `watcher.py` | 60s | Polls iCloud Voice Memos DB, transcribes via Whisper, classifies and routes |
| `com.penny.tasks` | `tasks_poller.py` | 180s | Polls Google Tasks API, routes items to Apple Reminders |
| `com.penny.webhook` | `webhook/server.py` | continuous | HTTP server on port 5678 (direct uploads + text ingestion) |
| `com.penny.export` | `scripts/export_transcripts.py` | 6h | Dumps transcripts.db to JSON, rsyncs to homelab |

## Verification Commands

```bash
# Check all services
ssh macmini "launchctl list | grep penny"

# Check health
ssh macmini "cat ~/.penny/health.txt"
# Format: timestamp|db_records:XXX|watcher_ok:1|voicememos:1|pending:X|latest_recording_pk:X|awaiting_file:X|voice_memo_failed:X

# Check transcript database
ssh macmini "sqlite3 ~/.penny/transcripts.db 'SELECT status, COUNT(*) FROM transcripts GROUP BY status;'"

# Check last PK
ssh macmini "cat ~/.penny/last_pk.txt"

# View logs
ssh macmini "tail -20 ~/.penny/logs/watcher.log"

# Restart a service
ssh macmini "launchctl kickstart -k gui/\$(id -u)/com.penny.SVCNAME"
```

## Recovery Procedures

### If Service Stops Running
```bash
ssh macmini "launchctl kickstart -k gui/\$(id -u)/com.penny.watcher"
```

### If CloudRecordings.db Gets Corrupted
```bash
ssh macmini "rm ~/Library/Group\ Containers/group.com.apple.VoiceMemos.shared/Recordings/CloudRecordings.db*"
ssh macmini "killall bird && open -a VoiceMemos"
```

### If transcripts.db Gets Corrupted
```bash
ssh macmini "rm ~/.penny/transcripts.db"
# Re-create on next watcher startup via init_db()
# Migrated entries from old processed.txt files will be re-imported
ssh macmini "launchctl kickstart -k gui/\$(id -u)/com.penny.watcher"
```

### After System Reboot
All services auto-start via `RunAtLoad`. Verify:
```bash
ssh macmini "launchctl list | grep penny"
```

## How to Deploy Code Updates

```bash
python3 scripts/trust_check.py

rsync -av --exclude='.git' --exclude='__pycache__' --exclude='venv' \
  /home/ubuntu/github/penny/ macmini:/Users/macmini/penny/

ssh macmini "for svc in watcher webhook tasks export; do
  launchctl unload ~/Library/LaunchAgents/com.penny.\${svc}.plist
  launchctl load ~/Library/LaunchAgents/com.penny.\${svc}.plist
done"
```

## Files Not in Git

- `~/.penny/` — all runtime state (transcripts.db, logs, health files, Google tokens)
- `~/Library/LaunchAgents/com.penny.*.plist` — contain secrets (OPENROUTER_API_KEY, etc.)
- Templates at `launchd/*.plist.template` have placeholder values

## Power Settings

From `pmset -g`:
- sleep: 1 (but prevented by screensharingd, powerd)
- disksleep: 10
- displaysleep: 0
- autorestart: 1

## Backup

Transcript history is backed up to homelab every 6 hours via `com.penny.export`:
- Local: `~/.penny/transcript_history.json`
- Remote: `homelab:~/backups/penny/transcript_history.json`
