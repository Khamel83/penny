# Penny

Voice memo relay for Apple Watch/iPhone → Telegram transcription.

## Workflow

Two options for getting voice memos from iPhone to Mac Mini:

### Option 1: iCloud Sync (Default)
```
Apple Watch / iPhone Voice Memo
    → iCloud sync (can be unreliable)
    → Mac Mini (watcher.py)
    → mlx-whisper transcription
    → @PennyMoltBot on Telegram
```

### Option 2: Webhook Direct Upload (More Reliable)
```
Apple Watch / iPhone Voice Memo
    → iOS Shortcut (POST to webhook)
    → Mac Mini (webhook/server.py)
    → mlx-whisper transcription
    → @PennyMoltBot on Telegram
```

The webhook approach bypasses iCloud sync entirely and is more reliable.

## Deployment

| Component | Location | Status |
|-----------|----------|--------|
| Voice Watcher (iCloud) | macmini (launchd) | Running |
| Webhook Server (Direct) | macmini (launchd) | Optional |
| Telegram Bot | @PennyMoltBot | Connected |

## Requirements

- macOS with Homebrew
- Python 3.10+ with `mlx-whisper`, `requests`, `watchdog`, `flask`
- ffmpeg (`brew install ffmpeg`)

```bash
pip install mlx-whisper requests watchdog flask
```

## Setup (Mac Mini)

The watcher runs from `/Users/macmini/penny/` with a virtualenv.

```bash
# Check status
launchctl list | grep penny

# View logs
tail -f /tmp/penny-watcher.log

# Restart
launchctl unload ~/Library/LaunchAgents/com.penny.watcher.plist
launchctl load ~/Library/LaunchAgents/com.penny.watcher.plist
```

## Environment Variables

Required in the launchd plist:

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `PATH` | Must include `/opt/homebrew/bin` |

Optional:

| Variable | Default |
|----------|---------|
| `VOICE_MEMOS_DIR` | `~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings` |

## Deployment from Repo

```bash
# Sync to macmini
rsync -avz --delete /home/ubuntu/github/penny/ macmini:~/penny/ --exclude '.git' --exclude 'docs/sessions'

# Restart the service
ssh macmini "launchctl unload ~/Library/LaunchAgents/com.penny.watcher.plist && launchctl load ~/Library/LaunchAgents/com.penny.watcher.plist"
```

## Adding Destinations

To add another destination (OpenClaw, Discord, etc.), add a function in `watcher.py`:

```python
def send_to_X(transcript):
    # POST to wherever
    pass

# Then call it in process():
send_to_telegram(transcript)
send_to_X(transcript)  # add this
```

## Related

- **@PennyOCIBot** - OpenClaw bot for Telegram voice notes (separate system)

## Webhook Setup (iOS Shortcut Alternative)

If iCloud sync is unreliable, use the webhook approach:

### 1. Deploy webhook server on macmini
```bash
# Copy webhook server
scp webhook/server.py macmini:~/penny/

# Create launchd service (see launchd/com.penny.webhook.plist.template)
# Load service
ssh macmini "launchctl load ~/Library/LaunchAgents/com.penny.webhook.plist"
```

### 2. Create iOS Shortcut

Create a shortcut that:
1. Takes voice memo input (or records new audio)
2. POSTs to: `https://<macmini-tailscale-ip>:5678/upload`
3. Uses form-data with key `audio` containing the audio file

Shortcut URL format:
```
https://100.113.216.27:5678/upload
```

(Note: Use macmini's Tailscale IP for private network access)
