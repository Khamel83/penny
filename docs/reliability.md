# Penny Reliability Guide

## How to Ensure Penny Works Forever

### 1. Service Auto-Start (RunAtLoad + KeepAlive)

All launchd plists have both `RunAtLoad` and `KeepAlive`:
- `RunAtLoad` = Starts when mac mini boots
- `KeepAlive` = Restarts if it crashes

Verify:
```bash
ssh macmini "launchctl list | grep penny"
# Should show com.penny.watcher, com.penny.webhook, com.penny.tasks, com.penny.export
```

### 2. Health Check Files

The watcher writes to `~/.penny/health.txt` every 5 minutes:
```bash
ssh macmini "cat ~/.penny/health.txt"
# Format: timestamp|db_records:XXX|watcher_ok:1|voicememos:1|pending:X|latest_recording_pk:X|awaiting_file:X|voice_memo_failed:X
```

Fields:
- `db_records` — total recordings in CloudRecordings.db
- `watcher_ok` — watcher service healthy (1/0)
- `voicememos` — VoiceMemos app running (1/0)
- `pending` — transcripts awaiting routing
- `latest_recording_pk` — latest Voice Memo PK durably registered in local ingest state
- `awaiting_file` — DB entries seen but audio file not yet present on disk
- `voice_memo_failed` — ingest entries that hit a terminal error and need investigation

### 3. Dependency Checks on Startup

The watcher checks all dependencies before entering the poll loop:
- ffmpeg availability
- Python packages (mlx_whisper, requests)
- Voice Memos directory exists
- Telegram credentials (if enabled)
- CloudRecordings.db integrity

If any check fails, it logs to `~/.penny/logs/watcher.log`.

### 4. Dual Detection Method

The watcher uses TWO methods to find recordings:

**Method 1: Database Polling (primary)**
- Polls `CloudRecordings.db` every 60 seconds for `Z_PK > last_seen_pk`
- Finds new recording entries via primary key
- Deduplicates via `transcripts.db` content hash

**Method 2: Disk Scanning (backup)**
- Scans for unprocessed `.m4a` files on disk (age < 24h)
- Checks against `transcripts.db` content hash to avoid re-processing
- Catches files that appear before database updates
- Handles delayed/broken iCloud sync

Both methods run every cycle. The age cutoff prevents re-processing when VoiceMemos touches file mtimes.

### 4.5 Explicit Voice Memo Ingest State

Native Voice Memos is the primary ingest path, so Penny now tracks each memo through these states:
- `discovered` — DB row seen locally
- `awaiting_file` — DB row exists, file not downloaded yet
- `file_ready` — file present on disk
- `transcribed` — transcript persisted locally
- `routed` — Notes/Reminders write completed
- `failed` — a durable error occurred and is visible for retry/debugging

This prevents "seen once and lost forever" behavior when CloudKit metadata arrives before the audio file.

### 5. Transcript Database (Single Source of Truth)

All transcriptions are persisted to `~/.penny/transcripts.db` (SQLite) before routing:
- `content_hash` (MD5) UNIQUE constraint prevents duplicates
- Status tracking: `pending` → `routed` / `failed`
- Failed transcripts are retried every cycle (up to 5 at a time)
- Write-before-route ensures nothing is lost even if routing fails

### 6. Periodic Backup

`com.penny.export` runs every 6 hours:
- Dumps all transcript records to `~/.penny/transcript_history.json`
- Rsyncs to `homelab:~/backups/penny/`

## Failure Modes & Recovery

### Mode 1: iCloud Sync Stops

**Symptoms**: New recordings don't appear in database

**Root cause**: CloudKit (Voice Memos sync) requires the **VoiceMemos app to be running**. Unlike iCloud Drive, it does not sync in the background.

**Prevention**:
- VoiceMemos is a login item (starts hidden on boot)
- Watcher calls `open -g -a VoiceMemos` before every poll cycle

**Detection**: Disk scan finds unprocessed files

**Recovery**: Automatic (watcher opens VoiceMemos every 60s)

**Manual fix**:
```bash
ssh macmini "open -g -a VoiceMemos"
```

### Mode 2: CloudRecordings.db Gets Corrupted

**Symptoms**: Database queries fail, watcher logs "Database corrupted"

**Recovery**:
```bash
ssh macmini "rm ~/Library/Group\ Containers/group.com.apple.VoiceMemos.shared/Recordings/CloudRecordings.db*"
ssh macmini "killall bird && open -a VoiceMemos"
ssh macmini "launchctl kickstart -k gui/$(id -u)/com.penny.watcher"
```

### Mode 3: transcripts.db Gets Corrupted

**Symptoms**: Transcripts not being logged, dedup failing

**Recovery**:
```bash
ssh macmini "rm ~/.penny/transcripts.db"
ssh macmini "launchctl kickstart -k gui/$(id -u)/com.penny.watcher"
# init_db() re-creates the table on startup
# Old processed.txt files will be re-migrated (hashes only, no transcripts)
# Homelab backup can restore transcript text: homelab:~/backups/penny/transcript_history.json
```

### Mode 4: ffmpeg Path Issues

**Symptoms**: "ffmpeg not found" errors

**Detection**: Startup check logs "ffmpeg not found"

**Prevention**: PATH is set in launchd plist

### Mode 5: Service Stops Running

**Symptoms**: No PID in launchctl list

**Recovery**: KeepAlive should restart automatically

**Manual restart**:
```bash
ssh macmini "launchctl kickstart -k gui/$(id -u)/com.penny.SVCNAME"
```

### Mode 6: Routing Fails (AppleScript errors)

**Symptoms**: Transcripts logged with `status=failed` in database

**Recovery**: Automatic — watcher retries up to 5 failed transcripts per cycle

**Manual check**:
```bash
ssh macmini "sqlite3 ~/.penny/transcripts.db \"SELECT id, error_message FROM transcripts WHERE status='failed';\""
```

### Mode 7: DB Entry Exists But Audio File Is Still Missing

**Symptoms**: `latest_recording_pk` advances but `awaiting_file` stays above zero.

**Meaning**: the Mac has seen Voice Memos metadata in `CloudRecordings.db`, but the actual audio file has not finished downloading from iCloud yet.

**Recovery**: Automatic. The watcher keeps retrying these entries every cycle until the file appears.

## Summary: Why This Won't Break

1. **Auto-start on boot** — launchd `RunAtLoad`
2. **Auto-restart on crash** — launchd `KeepAlive`
3. **VoiceMemos always running** — Login item + watcher opens it every 60s
4. **Dual detection** — Database polling + disk scanning
5. **Transcript persistence** — Written to SQLite before routing (no data loss)
6. **Deduplication** — content hash UNIQUE + PK tracking + age cutoff
7. **Automatic retries** — Failed routing retried every cycle
8. **Health monitoring** — 5-min health file + daily CI health check
9. **Periodic backup** — JSON export to homelab every 6 hours
10. **Explicit PATH** — ffmpeg always found
