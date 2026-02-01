# Penny

Voice memo relay. Transcribes and pushes to OpenClaw.

## Architecture

```
Voice Memo (iPhone/Watch)
    → iCloud sync
    → Mac Mini (watcher.py)
    → mlx-whisper transcription
    → OpenClaw (OCI-Dev)
    → Telegram via @PennyOCIBot
```

## Current Deployment Status

| Component | Location | Status |
|-----------|----------|--------|
| OpenClaw Gateway | OCI-Dev (100.126.13.70:18789) | Running via systemd |
| Telegram Bot | @PennyOCIBot | Connected |
| Voice Watcher | Mac Mini (launchd) | Running |

## Voice Input Options

1. **Voice Memos** → iCloud → Mac Mini → Penny watcher → OpenClaw (long-form)
2. **Telegram Voice Notes** → @PennyOCIBot → OpenClaw (quick messages)

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

## OpenClaw (OCI-Dev)

OpenClaw runs as a systemd service with SOPS-encrypted secrets.

```bash
# Check status
ssh oci "sudo systemctl status openclaw"

# View health
ssh oci "openclaw health"

# View logs
ssh oci "tail -f /tmp/openclaw/openclaw-*.log"

# Restart
ssh oci "sudo systemctl restart openclaw"
```

## Secrets

All secrets are SOPS/Age encrypted in `~/openclaw/secrets.yaml` on OCI-Dev.

```bash
# Decrypt and view
cd ~/openclaw
SOPS_AGE_KEY_FILE=~/.age/key.txt sops -d secrets.yaml
```

## Old Code

The original Penny codebase (~3000 lines) is preserved on the `archive` branch.
