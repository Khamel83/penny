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
# Format: timestamp|db_records:XXX|watcher_ok:1|voicememos:1|voicememos_responsive:1|voice_db_ok:1|voice_db_wal_age_seconds:X|cloud_latest_recording_pk:X|pending:X|latest_recording_pk:X|awaiting_file:X|voice_memo_failed:X|slack_pending:X|slack_failed:X|slack_health_error:0
```

Fields:
- `db_records` — total recordings in CloudRecordings.db
- `watcher_ok` — watcher service healthy (1/0)
- `voicememos` — VoiceMemos app has a process (1/0)
- `voicememos_responsive` — VoiceMemos answered an Apple Event (1/0); this catches an alive-but-stuck app
- `voice_db_ok` — CloudRecordings.db passed SQLite integrity and read checks (1/0)
- `voice_db_wal_age_seconds` — age of the SQLite WAL carrying recent sync writes; `-1` means no WAL is present
- `cloud_latest_recording_pk` — latest raw Voice Memos row visible locally
- `pending` — transcripts awaiting routing
- `latest_recording_pk` — latest Voice Memo PK durably registered in local ingest state
- `awaiting_file` — DB entries seen but audio file not yet present on disk
- `voice_memo_failed` — ingest entries that hit a terminal error and need investigation
- `slack_pending` — Slack deliveries waiting for their first send or next retry window
- `slack_failed` — Slack deliveries that exhausted the retry policy and need review
- `slack_health_error` — `1` when Slack outbox health could not be read; this also forces `watcher_ok:0`

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

Eligible iCloud transcripts also create one durable `slack_deliveries` outbox row:
- `transcript_row_id` UNIQUE prevents duplicate Slack rows on replay
- `next_attempt_at` gates retries so failed sends do not spin every poll cycle
- `provider_ts` stores the Slack message timestamp after acknowledgement
- bodies over Slack's 40,000-character `chat.postMessage` boundary are split into deterministic chunks; `next_chunk_index`, per-chunk retry state, and stable per-chunk client message IDs make retries durable and idempotent
- each outbox pass attempts at most one Slack chunk, leaving later chunks durably pending so ingestion and poll-loop draining remain bounded
- the complete original transcript remains in `message_text`; concatenating acknowledged chunks reproduces it exactly
- terminal `failed` rows stay visible in health output instead of retrying forever
- Slack transcript delivery is independent from `config.toml`'s Telegram toggle; the watcher uses `PENNY_SLACK_BOT_TOKEN` and always targets channel ID `C0BKS0QT7FU`
- `PENNY_SLACK_CHANNEL_ID` in the tracked watcher template is a pinned runtime invariant, not a configurable destination; alternate `PENNY_SLACK_CHANNEL_ID` or generic `SLACK_CHANNEL_ID` values cannot redirect new delivery
- Slack mentions, push notifications, badges, and channel notification preferences are external Slack settings, not Penny repository settings

Maya routing is a separate evidence stream from both transcript receipt and Slack delivery:
- Penny sends the full persisted transcript body, original `source`, optional `duration_seconds`, and stable `client_ref = penny:<transcript_row_id>` to `MAYA_TRANSCRIPT_URL`
- Penny reads the Maya bearer token only from `MAYA_INGEST_TOKEN` at runtime and does not persist or print it
- `routing_progress.maya_route` records whether Maya was `attempting`, `accepted`, `rejected`, or `failed`
- only a validated Maya acceptance response marks the transcript as routed to `maya`; non-200, malformed 200, timeout, and transport failures fall back to local routing with the rejection/failure details preserved in local state
- for a newly ingested recording, Maya or local routing completes before the watcher attempts its Slack outbox copy

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
- Watcher refreshes VoiceMemos before every poll cycle, even when its process exists
- Watcher probes Apple Event responsiveness, not just `pgrep`
- After three consecutive failed responsiveness probes, watcher terminates and relaunches VoiceMemos automatically

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

### Evidence checklist for one transcript

When validating one transcript end-to-end, collect evidence in this order:

1. Penny receipt: transcript row in `transcripts.db` proves Penny received and persisted it locally.
2. Maya acceptance or rejection: `routing_progress.maya_route` shows the latest Maya attempt, using `client_ref = penny:<transcript_id>`.
3. Slack acceptance or rejection: `slack_deliveries` shows whether the verbatim Slack copy was acknowledged, retried, or terminally failed.

These categories are intentionally independent. A Maya rejection is not a missing Penny receipt, and a Slack failure is not proof that Maya or local routing failed.

### Notification control inventory

When someone asks "are notifications enabled?", answer with the exact layer:

1. Telegram: `config.toml` `[notifications].telegram_enabled`. `false` disables Telegram sends without removing the code path or credentials.
2. Slack transcript mirroring: watcher runtime env `PENNY_SLACK_BOT_TOKEN` enables posting. The destination is pinned to channel ID `C0BKS0QT7FU`; it is not selected from the environment.
3. Slack user/channel notification behavior: external Slack preference. Penny does not store or infer this setting, and Telegram state must never be used as a proxy for it.

### Live Slack verification sequence for operators

Use this when closing a notification-policy issue or verifying the Slack canary after a deployment. The controller runs the live canary; this repo only documents how to inspect the result.

1. Check Penny's real health endpoint:

```bash
ssh macmini "curl -fsS http://127.0.0.1:5678/health"
```

Expected result:

- JSON includes `"status":"ok"` and `"service":"penny-webhook"`.
- With the current repo policy, `"telegram_configured"` may be `false`; that does not disable Slack transcript mirroring.

2. Check watcher health and Slack outbox counters:

```bash
ssh macmini "cat ~/.penny/health.txt"
```

Expected result:

- `watcher_ok:1`
- `slack_pending:`, `slack_failed:`, and `slack_health_error:0` fields are present
- no unexpected growth in `slack_failed`

3. Check Slack runtime wiring without printing the token:

```bash
ssh macmini '
runtime_snapshot="$(mktemp)"
trap "rm -f \"$runtime_snapshot\"" EXIT
launchctl print gui/$(id -u)/com.penny.watcher > "$runtime_snapshot" || exit 1
slack_configured=False
slack_channel_ok=False
while IFS= read -r line; do
  case "$line" in
    *"PENNY_SLACK_BOT_TOKEN => "?*) slack_configured=True ;;
  esac
  case "$line" in
    *"PENNY_SLACK_CHANNEL_ID => C0BKS0QT7FU") slack_channel_ok=True ;;
  esac
done < "$runtime_snapshot"
echo "slack_configured=$slack_configured"
echo "slack_channel_ok=$slack_channel_ok"
'
```

Expected result:

- `slack_configured=True`
- `slack_channel_ok=True`

4. After the controller runs the live canary, read `#penny` channel ID `C0BKS0QT7FU` and verify this exact text appears verbatim:

```text
Penny health canary 20260726T205704Z: receipt test only; no action required.
```

Concrete verification procedure:

- run the read-only health command above and confirm the response still shows `status=ok`
- run the read-only watcher-runtime check above and confirm `slack_configured=True` and `slack_channel_ok=True`
- then read the `#penny` channel and match the canary text exactly, character for character

That combination proves Penny transcript delivery was not suppressed by `telegram_enabled = false`. It does not prove, inspect, or change external Slack mention, badge, or push-notification preferences.

Slack mention, badge, and push-notification preferences are external Slack settings. Penny cannot inspect, change, or prove those preferences from repository state, so do not claim they were modified here.

### Mode 4: ffmpeg Path Issues

**Symptoms**: "ffmpeg not found" errors

**Detection**: Startup check logs "ffmpeg not found"

**Prevention**: PATH is set in launchd plist

### Mode 5: Service Stops Running

**Symptoms**: No PID in launchctl list

**Recovery**: Three layers kick in automatically:
1. `KeepAlive` in the launchd plist restarts the service immediately on crash
2. The daily CI health check detects any service without a PID and runs `launchctl kickstart -k` before alerting
3. Only if the restart also fails does a GitHub email go out

**Manual restart**:
```bash
ssh macmini "launchctl kickstart -k gui/$(id -u)/com.penny.SVCNAME"
```

### Mode 8: CI Health Check Fails — SSH Connects to Wrong IP

**Symptoms**: Health check fails in ~2 min with "Connection timed out" to a `192.168.x.x` address instead of the Tailscale IP.

**Root cause**: The GitHub Actions runner job environment doesn't always pick up `~/.ssh/config`, causing SSH to fall back to mDNS/local DNS and resolve `macmini` to its LAN IP (`192.168.7.165`) rather than the Tailscale IP (`100.113.216.27`). OCI cannot reach the LAN IP, so the connection hangs until TCP times out.

**Prevention**: The health check workflow uses explicit `-F /home/ubuntu/.ssh/config -o ConnectTimeout=15` on every SSH call, and runs an upfront connectivity check that fails in ≤15 s with a diagnostic message if macmini is unreachable.

**Manual diagnosis**:
```bash
# From oci-dev — should connect in <1s via Tailscale
ssh -F /home/ubuntu/.ssh/config macmini "echo OK"

# If it hangs or connects to wrong IP, Tailscale may be down on macmini:
ssh macmini "tailscale status"
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
8. **Health monitoring** — 5-min health file + daily CI health check with self-healing restarts
9. **Periodic backup** — JSON export to homelab every 6 hours
10. **Explicit PATH** — ffmpeg always found
