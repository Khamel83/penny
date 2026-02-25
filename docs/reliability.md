# Penny Reliability Guide

## How to Ensure Penny Works Forever

### 1. Service Auto-Start (RunAtLoad + KeepAlive)

The launchd plist has both `RunAtLoad` and `KeepAlive`:
- `RunAtLoad` = Starts when mac mini boots
- `KeepAlive` = Restarts if it crashes

Verify:
```bash
ssh macmini "launchctl list | grep penny"
# Should show com.penny.watcher with a PID
```

### 2. Health Check File

The watcher writes to `~/.penny/health.txt` every 5 minutes:
```bash
ssh macmini "cat ~/.penny/health.txt"
# Shows: timestamp|db_records:XXX|watcher_ok:1
```

Monitor this file to detect if the service is alive.

### 3. Dependency Checks on Startup

The watcher now checks all dependencies on startup:
- ffmpeg availability
- Python packages (mlx_whisper, requests, watchdog)
- Voice Memos directory
- Telegram credentials
- Database integrity

If any check fails, it logs to `/tmp/penny-watcher.log`.

### 4. Dual Detection Method

The watcher uses TWO methods to find recordings:

**Method 1: Database Polling**
- Polls `CloudRecordings.db` every 60 seconds
- Finds new Z_PK entries (recording IDs)
- Works when iCloud sync is working normally

**Method 2: Disk Scanning**
- Scans for unprocessed `.m4a` files on disk
- Catches files that appear before database updates
- Handles delayed/broken iCloud sync

Both methods run in parallel. If one fails, the other still works.

### 5. Regular Health Logging

Every 5 minutes, the watcher logs:
```
Health check: OK | PK=117 | Files on disk: 119
```

This tells you:
- Service is running (OK)
- Last processed recording (PK=117)
- Total files in Voice Memos directory

## What to Do After Mac Mini Restart

### Automatic (Nothing Required)

1. Service auto-starts via launchd
2. Dependency checks run
3. Initial scan processes any missed recordings
4. Polling loop begins

### Verify It's Working

```bash
# Check service is running
ssh macmini "launchctl list | grep penny"

# Check recent logs
ssh macmini "tail -20 /tmp/penny-watcher.log"

# Check health file
ssh macmini "cat ~/.penny/health.txt"
```

## Failure Modes & Recovery

### Mode 1: iCloud Sync Stops

**Symptoms**: New recordings don't appear in database

**Detection**: Disk scan finds unprocessed files

**Recovery**: Automatic - disk scan catches them when they appear

**Manual fix**:
```bash
# Force iCloud sync restart
ssh macmini "killall bird && open -a VoiceMemos"
```

### Mode 2: Database Gets Corrupted

**Symptoms**: Database queries fail

**Detection**: Startup check logs "Database corrupted"

**Recovery**:
```bash
# Delete database to force rebuild
ssh macmini "rm ~/Library/Group\ Containers/group.com.apple.VoiceMemos.shared/Recordings/CloudRecordings.db*"
ssh macmini "launchctl kickstart -k gui/$(id -u)/com.penny.watcher"
```

### Mode 3: ffmpeg Path Issues

**Symptoms**: "ffmpeg not found" errors

**Detection**: Startup check logs "ffmpeg not found"

**Prevention**: PATH is set in launchd plist

**Manual check**:
```bash
ssh macmini "/opt/homebrew/bin/ffmpeg -version"
```

### Mode 4: Service Stops Running

**Symptoms**: No PID in launchctl list

**Recovery**: KeepAlive should restart it automatically

**Manual restart**:
```bash
ssh macmini "launchctl kickstart -k gui/$(id -u)/com.penny.watcher"
```

### Mode 5: Code Gets Out of Date

**Prevention**: Deploy latest code from repo

**Re-sync**:
```bash
rsync -avz /home/ubuntu/github/penny/ macmini:~/penny/ --exclude '.git' --exclude 'docs/sessions'
ssh macmini "launchctl kickstart -k gui/$(id -u)/com.penny.watcher"
```

## Monitoring Script

Create this script to check Penny health:

```bash
#!/bin/bash
# check_penny_health.sh

# Check service is running
if ! ssh macmini "launchctl list | grep -q com.penny.watcher"; then
    echo "FAIL: Penny service not running"
    exit 1
fi

# Check health file is recent (within 10 minutes)
HEALTH_TIME=$(ssh macmini "cut -d'|' -f1 ~/.penny/health.txt | cut -d'T' -f2 | cut -d'.' -f1")
HEALTH_EPOCH=$(date -j -f "%H:%M:%S" "$HEALTH_TIME" +%s 2>/dev/null || echo 0)
NOW_epoch=$(date +%s)
if [ $((NOW_epoch - HEALTH_EPOCH)) -gt 600 ]; then
    echo "FAIL: Health file is old (stale service)"
    exit 1
fi

# Check recent log activity
if ! ssh macmini "tail -1 /tmp/penny-watcher.log | grep -q 'Health check'"; then
    echo "WARN: No recent health checks in log"
fi

echo "OK: Penny service is healthy"
ssh macmini "tail -1 /tmp/penny-watcher.log"
```

## Summary: Why This Won't Break

1. **Auto-start on boot** - launchd `RunAtLoad`
2. **Auto-restart on crash** - launchd `KeepAlive`
3. **Startup dependency checks** - Fails fast if something wrong
4. **Dual detection methods** - Database + disk scanning
5. **Health status file** - Can be monitored externally
6. **Regular health logging** - Every 5 minutes
7. **Explicit PATH** - ffmpeg always found

The system has multiple layers of redundancy. If any component fails, there's a backup.
