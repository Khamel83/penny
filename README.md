# Penny

Voice memo relay. Transcribes and pushes to OpenClaw.

## Architecture

```
Voice Memo (iPhone/Watch)
    → iCloud sync
    → Mac Mini (this watcher)
    → mlx-whisper transcription
    → OpenClaw webhook
    → OpenClaw handles memory, routing, Telegram
```

## Setup (Mac Mini)

1. Install dependencies:
```bash
pip install mlx-whisper watchdog requests
```

2. Set environment:
```bash
export OPENCLAW_URL="http://100.126.13.70:18789"
export OPENCLAW_TOKEN="your-webhook-token"
```

3. Run:
```bash
python watcher.py
```

## Run as launchd service

Create `~/Library/LaunchAgents/com.penny.watcher.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.penny.watcher</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/macmini/penny/watcher.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OPENCLAW_URL</key>
        <string>http://100.126.13.70:18789</string>
        <key>OPENCLAW_TOKEN</key>
        <string>your-token</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/penny-watcher.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/penny-watcher.log</string>
</dict>
</plist>
```

Load: `launchctl load ~/Library/LaunchAgents/com.penny.watcher.plist`

## Voice Input Options

You have TWO ways to send voice to OpenClaw:

1. **Voice Memos** → iCloud → Mac Mini → Penny watcher → OpenClaw (long-form)
2. **Telegram Voice Notes** → @PennyOCIBot → OpenClaw (quick messages)

## OpenClaw (OCI-Dev)

OpenClaw runs on OCI-Dev (100.126.13.70:18789) as a systemd service.

```bash
# Check status
ssh oci "sudo systemctl status openclaw"

# View health
ssh oci "openclaw health"

# View logs
ssh oci "tail -f /tmp/openclaw/openclaw-*.log"
```
