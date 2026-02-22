# Penny

Voice memo relay for Apple Watch/iPhone → Telegram transcription.

## Workflow

```
Apple Watch / iPhone Voice Memo
    → iCloud sync (30-60s)
    → Mac Mini (watcher.py)
    → mlx-whisper transcription
    → @PennyMoltBot on Telegram
```

## Deployment

| Component | Location | Status |
|-----------|----------|--------|
| Voice Watcher | macmini (launchd) | Running |
| Telegram Bot | @PennyMoltBot | Connected |

## Requirements

- macOS with Homebrew
- Python 3.10+ with `mlx-whisper`, `requests`, `watchdog`
- ffmpeg (`brew install ffmpeg`)

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
