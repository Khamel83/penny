# Penny Troubleshooting Guide

## Symptom: New recordings not appearing on mac mini

### Diagnosis

Check the database for latest PK:
```bash
ssh macmini 'sqlite3 "$HOME/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/CloudRecordings.db" "SELECT Z_PK, ZCUSTOMLABEL, ZDATE FROM ZCLOUDRECORDING ORDER BY Z_PK DESC LIMIT 5;"'
```

If the highest PK doesn't match your latest recording on iPhone → **iPhone is not uploading to iCloud**.

### Root Cause: iPhone → iCloud Sync Failure

The Penny system works as follows:
1. **Apple Watch** → Records voice memo
2. **iPhone** → Receives recording from watch
3. **iCloud** → iPhone uploads to iCloud (⚠️ THIS STEP FAILS)
4. **Mac mini** → Downloads from iCloud and transcribes

If step 3 fails, mac mini never receives the recording.

### Solutions

#### 1. Check iPhone iCloud Settings (Most Common Fix)

On your iPhone:
1. Settings → [Your Name] → iCloud
2. Tap "Show All" → Find "Voice Memos"
3. **Ensure "Sync this [Device]" is ON**

#### 2. Force Voice Memos Sync on iPhone

On your iPhone:
1. Open Voice Memos app
2. Pull down to trigger sync (look for spinning icon)
3. Keep app open for 1-2 minutes

#### 3. Check Network Conditions

Voice Memos only sync over WiFi when:
- iPhone is connected to WiFi
- iPhone is NOT in Low Power Mode
- iPhone has sufficient iCloud storage

Check: Settings → iCloud → Account Storage

#### 4. Restart iCloud Sync on iPhone

On your iPhone:
1. Settings → [Your Name] → iCloud → Show All → Voice Memos
2. Turn OFF "Sync this iPhone"
3. Wait 10 seconds
4. Turn ON "Sync this iPhone"
5. Open Voice Memos app and trigger sync

#### 5. Check for iCloud Outages

Visit: https://www.apple.com/support/systemstatus/

Look for issues with "iCloud Drive" or "CloudKit".

### Mac Mini Side Checks

**Key fact**: CloudKit (Voice Memos sync) requires the VoiceMemos app to be running. It does NOT sync in the background like iCloud Drive. The watcher now refreshes VoiceMemos every 60s, probes Apple Event responsiveness, and recycles an unresponsive process after three failed probes. It is also a login item so it starts on boot.

The watcher polls the database every 60 seconds. Verify it's running:

```bash
# Check service
ssh macmini "launchctl list | grep penny"

# Check log
ssh macmini "tail -f ~/.penny/logs/watcher.log"

# Check last seen PK
ssh macmini "cat ~/.penny/last_pk.txt"
```

### Expected Behavior After Fix

Once iPhone uploads to iCloud:
1. Database entry appears within 30 seconds
2. Mac mini detects new PK within 60 seconds
3. Audio file downloads (can take 1-5 minutes depending on size)
4. Transcription completes
5. Telegram message sent

Total latency: **2-7 minutes** after iPhone uploads to iCloud.

### Alternate Path: iOS Automation (Optional)

The primary Penny flow is still Apple Watch Voice Memos through iCloud. If you ever need an alternate ingest path for troubleshooting, you can create an iOS Shortcut automation:

1. Open Shortcuts app on iPhone
2. Create Automation: "When Voice Memos is closed"
3. Action: "Get latest Voice Memo" → "Upload to http://macmini:5678/upload"
4. Turn off "Notify when run"

This sends recordings directly to mac mini when you close the Voice Memos app, bypassing iCloud delays.

See: `docs/ios-shortcut-setup.md`

---

## Symptom: GitHub health check failing — SSH timeout / wrong IP

### Diagnosis

In the GitHub Actions run log, you see:
```
ssh: connect to host 192.168.7.165 port 22: Connection timed out
```

The runner is resolving `macmini` to its LAN IP instead of the Tailscale IP (`100.113.216.27`).

### Root cause

The self-hosted runner's job environment doesn't always inherit `~/.ssh/config`, so SSH falls back to mDNS and finds the macmini's LAN address. OCI can't reach `192.168.7.x`, so every connection silently hangs for ~2 minutes before failing.

### Quick checks

```bash
# 1. Is macmini reachable from oci-dev right now?
ssh -F /home/ubuntu/.ssh/config -o ConnectTimeout=10 macmini "echo OK"

# 2. Is Tailscale running on macmini?
ssh macmini "tailscale status | head -5"

# 3. Trigger a fresh health check run to get new logs
gh workflow run health-check.yml --ref main
```

### Fix if Tailscale is down on macmini

```bash
# Via LAN (if on same network or via homelab as jump host)
ssh -i ~/.ssh/id_ed25519 macmini@192.168.7.165 "sudo tailscale up"
# Or physically: System Preferences → Tailscale → Connect
```

### Fix if SSH config resolution breaks again

The workflow uses `-F /home/ubuntu/.ssh/config` explicitly on every SSH call. If the runner user or config path changes, update `SSH_MACMINI` in `.github/workflows/health-check.yml`.
