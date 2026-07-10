# Penny Handoff

This file is the assistant-facing entry point for Penny.

## What Penny Is

Penny is voice capture middleware for Apple's native apps. The primary flow is:

`Apple Voice Memos -> Penny local SQLite ledger -> Whisper transcription -> Maya -> downstream routing`

Penny can fall back to its local Apple Reminders / Apple Notes routing when Maya is
not configured.

## Canonical Docs

- [README.md](README.md)
- [docs/README.md](docs/README.md)
- [docs/reliability.md](docs/reliability.md)
- [docs/macmini-deployment.md](docs/macmini-deployment.md)
- [docs/troubleshooting.md](docs/troubleshooting.md)

## Active Production Incident: Voice Memos Stalled Before Transcription

Diagnosed on 2026-07-09 at approximately 18:20 PDT.

### Exact live paths

- Live checkout: `/Users/macmini/penny`
- This handoff after pulling the branch: `/Users/macmini/penny/HANDOFF.md`
- Watcher code: `/Users/macmini/penny/watcher.py`
- Penny config: `/Users/macmini/penny/config.toml`
- Penny local transcript ledger: `/Users/macmini/.penny/transcripts.db`
- Watcher log: `/Users/macmini/.penny/logs/watcher.system.log`
- Watcher launch script: `/Users/macmini/Library/Scripts/penny-watcher.sh`
- Watcher launchd plist: `/Users/macmini/Library/LaunchAgents/com.penny.watcher.plist`
- Apple Voice Memos source DB: `/Users/macmini/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/CloudRecordings.db`
- Apple Voice Memos audio directory: `/Users/macmini/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings`
- Maya checkout: `/Users/macmini/github/maya`
- Maya log: `/Users/macmini/Library/Logs/maya.log`

The Mac mini is reachable over Tailscale as `macmini@100.113.216.27`. The local
SSH alias `macmini` currently resolves to the LAN address `192.168.7.165`, which
was unreachable from the diagnosing Mac; use the Tailscale address if needed.

### Confirmed state

1. Apple Voice Memos is healthy and has records through `Z_PK=382`.
2. Penny's `voice_memo_ingest` ledger stops at `recording_pk=375`.
3. Seven recordings are therefore waiting upstream: PKs 376 through 382, dated
   2026-07-07 through 2026-07-09.
4. Penny's launchd watcher is alive, but every poll logs:
   `Database query failed: unable to open database file`.
5. macOS TCC attributes the access attempt to Homebrew Python 3.14.6 and returns
   `authValue=0, authReason=5`. The responsible executable is:
   `/opt/homebrew/Cellar/python@3.14/3.14.6/Frameworks/Python.framework/Versions/3.14/bin/python3.14`.
6. A direct query from an interactive SSH shell can read the same database and
   returns `(recording_count=264, max_pk=382)`. This isolates the failure to the
   background launchd process's macOS privacy context, not a missing/corrupt DB.
7. Maya forwarding is disabled independently: `[maya] transcript_url = ""` in
   `/Users/macmini/penny/config.toml`.
8. Penny's most recent successful transcript is ID 453 from 2026-06-28. Its
   `routed_to` value is `note in Penny`, not Maya.

### Root cause

There are two independent breaks:

1. The launchd watcher cannot read Apple's protected Voice Memos database because
   the current Homebrew Python 3.14 executable is denied by macOS TCC. No new
   recording reaches Penny's local ledger or transcription stage.
2. Even after that is repaired, Penny will not send transcripts to Maya because
   the Maya transcript endpoint is blank in the live config.

### Recovery sequence

Do these steps on the Mac mini. Do not delete or reset either SQLite database.

1. In **System Settings -> Privacy & Security -> Full Disk Access**, grant access
   to the Python executable used by Penny's watcher. The current resolved binary
   is the Python 3.14.6 path shown above; `/Users/macmini/penny/venv/bin/python3`
   resolves to it. If macOS will not accept the venv symlink, add the resolved
   Homebrew binary directly.
2. Restart only the watcher:

   ```bash
   launchctl kickstart -k "gui/$(id -u)/com.penny.watcher"
   ```

3. Verify DB discovery advances beyond PK 375 and the access error stops:

   ```bash
   tail -n 100 /Users/macmini/.penny/logs/watcher.system.log
   sqlite3 -header -column /Users/macmini/.penny/transcripts.db \
     "SELECT recording_pk,status,transcript_row_id,updated_at FROM voice_memo_ingest ORDER BY recording_pk DESC LIMIT 12;"
   ```

4. Configure Penny's Maya target in `/Users/macmini/penny/config.toml`. The code
   expects Maya's `POST /ingest/transcript` endpoint and a bearer token matching
   Maya's `MAYA_INGEST_TOKEN`. Do not commit the production token. Confirm the
   deployed Maya URL and secret-loading mechanism before changing the live file.
5. Restart the watcher again after configuring Maya.
6. Verify a single backlog memo end-to-end before allowing the rest to drain:
   - the Apple PK appears in `voice_memo_ingest`;
   - a transcript row is created in `transcripts`;
   - `transcription_completed_at` is populated;
   - `routed_to` identifies Maya rather than `note in Penny` or Reminders;
   - Maya's log records the corresponding `/ingest/transcript` request;
   - the record ends in `routed`, not `pending` or `failed`.

### Useful read-only probes

```bash
# Compare Apple's source watermark with Penny's ingest watermark.
sqlite3 "/Users/macmini/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/CloudRecordings.db" \
  "SELECT COUNT(*), MAX(Z_PK) FROM ZCLOUDRECORDING;"
sqlite3 /Users/macmini/.penny/transcripts.db \
  "SELECT MAX(recording_pk) FROM voice_memo_ingest;"

# Confirm the live processes without assuming they are functionally healthy.
launchctl list | grep -E 'com[.]penny[.](watcher|webhook|tasks)|com[.]maya[.]server'

# Inspect the two relevant logs.
tail -n 100 /Users/macmini/.penny/logs/watcher.system.log
tail -n 100 /Users/macmini/Library/Logs/maya.log
```

Process presence is not proof of pipeline health. Completion requires matching
watermarks plus one traced recording that reaches Maya.

## Operational Shape

- The live deployment is expected to be a git checkout on the Mac mini.
- Keep local machine state out of git: `.env`, `secrets.env`, `venv/`, `~/.penny/`, and launchd plist outputs are runtime artifacts.
- `config.toml` holds non-secret, repo-managed settings.
- `launchd/*.plist.template` are the source templates; the real plists are machine-local.

## Validation

Before shipping repo changes:

1. Run `python3.12 scripts/trust_check.py`.
2. Run `uv run python -m pytest tests/ -v`.
3. Restart the affected launchd agents on the Mac mini.
4. Confirm the webhook health endpoint on port `5678`.

## Fleet Watchlist Note

If this repo is added to Maya's fleet watchlist, the registered repo name should be `penny`.
