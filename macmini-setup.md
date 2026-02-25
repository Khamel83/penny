# Penny on Mac mini Setup Guide

Penny runs on mac mini and transcribes voice memos from iCloud to Telegram.

## Deploy Location

- **Server**: `macmini` (Tailscale IP: `100.113.216.27`)
- **Directory**: `/Users/macmini/penny/`
- **Service**: `com.penny.watcher` (launchd)

## Voice Memos Directory

Voice memos are synced by iCloud to:

```
~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/
```

**Note**: The path has a space in "Group Containers" - always quote properly.

## Quick Commands

```bash
# SSH to mac mini
ssh macmini

# Check service status
launchctl list | grep penny

# View service logs
tail -f /tmp/penny-watcher.log

# Restart service
launchctl unload ~/Library/LaunchAgents/com.penny.watcher.plist
launchctl load ~/Library/LaunchAgents/com.penny.watcher.plist

# Check processed files count
wc -l ~/.penny/processed.txt

# List recent voice memos
ls -lt "$HOME/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/" | head -10
```

## Catch Up on Missed Memos

If the service was down and you need to transcribe missed files:

```bash
ssh macmini
cd ~/penny
source venv/bin/activate
python3 << 'EOF'
import hashlib
import os
from pathlib import Path
from datetime import datetime

VOICE_DIR = Path("/Users/macmini/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings")
PROCESSED = Path("~/.penny/processed.txt").expanduser()

import sys
sys.path.insert(0, "/Users/macmini/penny")
from watcher import transcribe, send_to_telegram, mark_processed

# Get processed hashes
processed_hashes = set()
if PROCESSED.exists():
    processed_hashes = set(PROCESSED.read_text().strip().split("\n"))

# Get all m4a files
m4a_files = sorted(VOICE_DIR.glob("*.m4a"), key=lambda f: os.path.getmtime(f))

print(f"Total m4a files: {len(m4a_files)}")
print(f"Already processed: {len(processed_hashes)}")

# Transcribe unprocessed files
count = 0
for f in m4a_files:
    file_hash = hashlib.md5(f.read_bytes()).hexdigest()
    if file_hash not in processed_hashes:
        print(f"\n[{count+1}] Transcribing: {f.name}")
        try:
            transcript = transcribe(f)
            send_to_telegram(transcript)
            mark_processed(f)
            count += 1
        except Exception as e:
            print(f"  Error: {e}")

print(f"\nTotal transcribed: {count}")
EOF
```

## Service Installation

1. Copy files to mac mini:
```bash
scp watcher.py macmini:/Users/macmini/penny/
```

2. Create the launchd plist (see `launchd/com.penny.watcher.plist.template`):
```bash
cat > ~/Library/LaunchAgents/com.penny.watcher.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.penny.watcher</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/macmini/penny/venv/bin/python3</string>
        <string>/Users/macmini/penny/watcher.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>TELEGRAM_BOT_TOKEN</key>
        <string>YOUR_BOT_TOKEN_HERE</string>
        <key>TELEGRAM_CHAT_ID</key>
        <string>YOUR_CHAT_ID_HERE</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/penny-watcher.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/penny-watcher.log</string>
    <key>WorkingDirectory</key>
    <string>/Users/macmini/penny</string>
</dict>
</plist>
EOF
```

3. Load the service:
```bash
launchctl load ~/Library/LaunchAgents/com.penny.watcher.plist
```

## Troubleshooting

### Service not detecting new files

1. Check the log:
```bash
tail -50 /tmp/penny-watcher.log
```

2. Verify directory path:
```bash
ls -la "$HOME/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/"
```

3. Check if files exist:
```bash
find "$HOME/Library/Group Containers" -name "*.m4a" -mtime -1
```

### Telegram not receiving messages

1. Check credentials in the plist:
```bash
launchctl export com.penny.watcher | grep TELEGRAM
```

2. Test manually:
```bash
cd ~/penny
source venv/bin/activate
python3 -c "from watcher import send_to_telegram; send_to_telegram('test message')"
```

### iCloud sync issues

Voice memos synced from iPhone may take time to appear on mac mini. The `Recordings` directory contains:
- `.m4a` files - actual audio recordings
- `CloudRecordings.db*` - iCloud sync database
- Subdirectories for iCloud asset storage

If files aren't appearing:
1. Open Voice Memos app on mac mini to trigger sync
2. Check iPhone iCloud sync status
3. Wait 5-10 minutes for iCloud to sync

## Dependencies

```bash
# Python virtual environment
cd ~/penny
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install mlx-whisper watchdog requests
```

## Notes

- launchd plists MUST include `PATH` in EnvironmentVariables or homebrew tools won't work
- The service runs with KeepAlive, so it restarts if it crashes
- Check `~/.penny/processed.txt` for tracking transcribed files (MD5 hashes)
