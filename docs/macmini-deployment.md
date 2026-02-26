# Penny Deployment on Mac Mini

## Exact File Locations

### Service Files
```
/Users/macmini/penny/
├── watcher.py              # Main watcher script (runs via launchd)
├── venv/                   # Python virtual environment
├── webhook/
│   └── server.py          # Webhook server (optional, not currently running)
└── .penny/                 # Runtime state directory
    ├── processed.txt       # Hashes of transcribed recordings (15 lines)
    ├── last_pk.txt         # Last database PK processed (117)
    └── health.txt          # Health status (written every 5 min)
```

### Launchd Service
```
~/Library/LaunchAgents/com.penny.watcher.plist
```
Contains: PATH, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

### Voice Memos Directory
```
~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/
```
Contains: *.m4a files (119 files currently), CloudRecordings.db

### Logs
```
~/.penny/logs/watcher.log         # Application log (rotating)
~/.penny/logs/watcher.system.log  # launchd stdout/stderr capture
```

## Current State

### Service Status
- Running: YES (PID 35027)
- Launchd label: com.penny.watcher
- Last PK processed: 117
- Processed recordings: 15
- Voice memos on disk: 119

### Environment
- Python: `/opt/homebrew/Cellar/python@3.14/3.14.0_1/Frameworks/Python.framework/Versions/3.14/bin/python3`
- ffmpeg: `/opt/homebrew/bin/ffmpeg`
- Virtual env: `/Users/macmini/penny/venv`

## Verification Commands

```bash
# Check service is running
ssh macmini "launchctl list | grep penny"

# Check recent logs
ssh macmini "tail -20 ~/.penny/logs/watcher.log"

# Check health file
ssh macmini "cat ~/.penny/health.txt"

# Check processed count
ssh macmini "wc -l ~/.penny/processed.txt"

# Check last PK
ssh macmini "cat ~/.penny/last_pk.txt"

# Check voice memos directory
ssh macmini "ls ~/Library/Group\ Containers/group.com.apple.VoiceMemos.shared/Recordings/" | wc -l

# Restart service
ssh macmini "launchctl kickstart -k gui/\$(id -u)/com.penny.watcher"
```

## Recovery Procedures

### If Service Stops Running
```bash
ssh macmini "launchctl load ~/Library/LaunchAgents/com.penny.watcher.plist"
```

### If Database Gets Corrupted
```bash
ssh macmini "rm ~/Library/Group\ Containers/group.com.apple.VoiceMemos.shared/Recordings/CloudRecordings.db*"
ssh macmini "killall bird && open -a VoiceMemos"
```

### After System Reboot
Service should auto-start via `RunAtLoad`. Verify:
```bash
ssh macmini "launchctl list | grep penny"
```

## How to Deploy Code Updates

```bash
# From local machine
rsync -avz /home/ubuntu/github/penny/ macmini:~/penny/ --exclude '.git' --exclude 'docs/sessions'

# Restart service on mac mini
ssh macmini "launchctl kickstart -k gui/\$(id -u)/com.penny.watcher"
```

## Power Settings (Currently)

From `pmset -g`:
- sleep: 1 (but prevented by screensharingd, powerd)
- disksleep: 10 (hard drives sleep after 10 min)
- displaysleep: 0 (display never sleeps)
- autorestart: 1 (auto-restart after power failure)

**Note**: disksleep=10 means hard drives may sleep. To fully disable sleep, run:
```bash
sudo pmset -a sleep 0 displaysleep 0 disksleep 0
```

## Files Not in Git (Generated on mac mini)

- ~/.penny/processed.txt - Recording hashes
- ~/.penny/last_pk.txt - Last database PK
- ~/.penny/health.txt - Health status
- ~/.penny/logs/watcher.log - Application logs
- ~/.penny/logs/watcher.system.log - launchd stdout/stderr logs
- ~/Library/LaunchAgents/com.penny.watcher.plist - Has secrets

## Repository Structure

```
/home/ubuntu/github/penny/
├── watcher.py              # Main script (deployed to macmini)
├── webhook/
│   └── server.py          # Webhook server (optional)
├── launchd/
│   ├── com.penny.watcher.plist.template
│   └── com.penny.webhook.plist.template
├── docs/
│   ├── reliability.md     # Reliability guide
│   ├── troubleshooting.md
│   └── ios-shortcut-setup.md
├── macmini-setup.md       # Setup guide
└── README.md
```

## Date: 2026-02-24

Last verified: Service running, processing recordings, health checks pending.
