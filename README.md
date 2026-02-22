# Penny

Voice memo relay. Transcribes and sends to Telegram.

## Workflow

```
Apple Watch / iPhone Voice Memo
    → iCloud sync (30-60s)
    → Mac Mini (watcher.py)
    → mlx-whisper transcription
    → Telegram Bot API
```

## Deployment

| Component | Location | Status |
|-----------|----------|--------|
| Voice Watcher | Mac Mini (launchd) | Running |
| Telegram Bot | @PennyMoltBot | Connected |

## Setup (Mac Mini)

The watcher is deployed to `/Users/macmini/penny/` with a virtualenv.

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

- `TELEGRAM_BOT_TOKEN` - Bot token from @BotFather
- `TELEGRAM_CHAT_ID` - Your Telegram chat ID

Optional:

- `VOICE_MEMOS_DIR` - Path to Voice Memos (defaults to Mac path)

## Deployment from Repo

```bash
# Sync to macmini
rsync -avz --delete /home/ubuntu/github/penny/ macmini:~/penny/ --exclude '.git' --exclude 'docs/sessions'

# Restart the service
ssh macmini "launchctl unload ~/Library/LaunchAgents/com.penny.watcher.plist && launchctl load ~/Library/LaunchAgents/com.penny.watcher.plist"
```
