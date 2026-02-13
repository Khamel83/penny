# iCloud Voice Memos Sync Issue

**Status:** BLOCKED - Apple iCloud issue, not fixable programmatically

## Problem
Voice Memos recorded on Apple Watch sync to iPhone but do NOT sync from iPhone to Mac mini via iCloud.

## Evidence
- Watch recordings appear on iPhone within seconds
- Mac mini iCloud Voice Memos toggle was reset (off/on)
- Mac mini can reach iCloud.com (network is fine)
- Last successful sync: Feb 12, 2026 at 22:13
- Multiple test recordings never appeared on Mac mini

## Attempted Fixes
1. ✗ `killall bird` - iCloud Drive daemon restart
2. ✗ `killall cloudd` - CloudKit daemon restart  
3. ✗ Toggle iCloud Voice Memos off/on in System Settings
4. ✗ Open Voice Memos app to trigger sync
5. ✗ `brctl download` - doesn't work for CloudKit apps

## Root Cause
Voice Memos uses CloudKit (not iCloud Drive). CloudKit sync is "eventual consistency" with no manual trigger. Apple's sync is stuck.

## Possible Solutions (Future)

### Option A: Fix iCloud on Mac mini (Nuclear)
- Sign out of iCloud completely
- Restart Mac
- Sign back in to iCloud
- Re-enable Voice Memos sync

### Option B: Webhook Approach (Bypass iCloud)
- iOS Shortcut records audio
- POSTs directly to webhook server
- Webhook transcribes and sends to Telegram
- **Already built:** `webhook/server.py` running on port 5678
- **Blocker:** Need public URL or Tailscale on iPhone

### Option C: Use Different Recording App
- "Just Press Record" syncs via iCloud Drive (instant)
- Has native Shortcuts integration
- Costs ~$5

## What's Working
- `watcher.py` on Mac mini monitors Voice Memos folder ✓
- Telegram delivery via direct Bot API ✓
- OpenClaw delivery via SSH to OCI-Dev ✓
- Webhook server on OCI-Dev port 5678 ✓
- Transcription on Mac mini via mlx-whisper ✓

## Files
- `/home/ubuntu/github/penny/watcher.py` - Mac mini watcher (deployed)
- `/home/ubuntu/github/penny/webhook/server.py` - OCI-Dev webhook (running on port 5678)
- `/etc/systemd/system/penny-webhook.service` - Systemd service

## Next Steps
1. Try nuclear iCloud fix (sign out/in) on Mac mini
2. Or set up iOS Shortcut with public webhook URL
3. Or install "Just Press Record" app
