# Claude Code Integration Setup

This document describes how to complete the Claude Code build integration for Penny.

## Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| Z.AI API Key | ✅ Configured | `ZAI_API_KEY` in homelab .env |
| Telegram Webhook Secret | ✅ Generated | `TELEGRAM_WEBHOOK_SECRET` in homelab .env |
| Penny Container | ✅ Deployed | Running as non-root user (UID 1001) |
| Cloudflare Tunnel | ✅ Configured | penny-tunnel container + CNAME record |
| Telegram Webhook | ✅ Active | https://penny.example.com/api/telegram/webhook |
| Claude Agent SDK | ✅ Working | SDK message handling with class-based types |

## Critical Requirements

### Non-Root User in Docker

**Claude CLI refuses to run with `--dangerously-skip-permissions` as root.** The Dockerfile creates a `penny` user (UID/GID 1001) and runs the application as that user.

```dockerfile
# Create non-root user for Claude CLI
RUN groupadd -g 1001 penny && useradd -u 1001 -g penny -m penny

# Set ownership
RUN mkdir -p /app/data /app/builds && chown -R penny:penny /app

# Switch to non-root user
USER penny
```

### Data Directory Permissions

The mounted `./data` volume must be writable by the container user (UID 1001). On the host:

```bash
# Set group ownership to match container user
sudo chgrp -R 1001 ./data
sudo chmod -R g+w ./data
```

### Required System Packages

The Docker image must include `procps` for Claude CLI process management:

```dockerfile
RUN apt-get install -y procps
```

## Architecture

```
Telegram → penny.example.com (Cloudflare) → penny-tunnel container → penny:8000
```

## Setup Reference (Already Completed)

### Step 1: Add penny.example.com to Cloudflare Tunnel

The Telegram webhook requires a public URL. Your tunnel uses dashboard-managed configuration.

1. Go to: https://one.dash.cloudflare.com/
2. Navigate: **Networks** → **Tunnels**
3. Click your tunnel: `0267e858-7457-4947-a0ad-153610c3a3ce`
4. Click **Configure** → **Public Hostname** tab
5. Click **Add a public hostname**
6. Fill in:

   | Field | Value |
   |-------|-------|
   | Subdomain | `penny` |
   | Domain | `example.com` |
   | Type | `HTTP` |
   | URL | `penny:8000` |

7. Click **Save**

### Step 2: Configure Telegram Webhook

After the tunnel hostname is active, run:

```bash
source /home/khamel83/homelab/.env

curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=https://penny.example.com/api/telegram/webhook" \
  -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}"
```

Expected response:
```json
{"ok":true,"result":true,"description":"Webhook was set"}
```

### Step 3: Verify Setup

Test the webhook is configured:
```bash
source /home/khamel83/homelab/.env
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo" | python3 -m json.tool
```

Test Penny health via public URL:
```bash
curl https://penny.example.com/health
```

## Permission Model

### Why `bypassPermissions` is Appropriate

The Claude Agent SDK uses `permission_mode="bypassPermissions"` which allows all tool operations without prompts. This is intentional for Penny's autonomous voice-to-build pipeline.

**The whole point is first-pass automation** - saying "build me X" should produce a deliverable without approving 12 individual steps.

| Concern | Mitigation |
|---------|------------|
| Delete system files | Docker isolation - container only sees `/app/` |
| Write to sensitive paths | Non-root user (UID 1001) - no access to `/etc/`, `~/.ssh/` |
| Network attacks | Container network is controlled by Docker |
| Host filesystem access | Sandboxed - builds isolated to `/app/builds/` |
| Runaway API costs | Model selector picks cheap GLM-4.7 by default |

The `bypassPermissions` mode exists specifically for **autonomous agents in controlled environments** - which is exactly what Penny is.

### Alternative Permission Modes

If you need more control (e.g., running outside Docker):

| Mode | Behavior | Use Case |
|------|----------|----------|
| `bypassPermissions` | All tools auto-approved | Sandboxed autonomous builds (current) |
| `acceptEdits` | File edits auto-approved, prompts for others | Semi-autonomous with some oversight |
| `default` | Prompts for all dangerous operations | Interactive development |

See [Claude Agent SDK Permissions](https://platform.claude.com/docs/en/agent-sdk/permissions) for details.

## How It Works

### Build Flow

1. Voice memo transcribed → classified as `build`
2. `model_selector.py` chooses GLM-4.7 (Z.AI) or Opus based on:
   - **Opus** if: keywords (critical, urgent, production, security) OR confidence < 70%
   - **GLM-4.7** otherwise (default, cheap)
3. Claude Code runs the build with Omar's preferences
4. If Claude asks a question → Telegram message sent to Omar
5. Omar replies → webhook receives answer → build continues
6. Deliverables extracted and stored

### Environment Variables

Located in `/home/khamel83/homelab/.env`:

```bash
# Claude Code builds
ZAI_API_KEY=<your-key>              # Z.AI GLM-4.7 access
ANTHROPIC_API_KEY=                   # Optional: Opus for critical builds
TELEGRAM_WEBHOOK_SECRET=<generated>  # Webhook authentication

# Already configured
TELEGRAM_BOT_TOKEN=<existing>
TELEGRAM_CHAT_ID=<existing>
OPENROUTER_API_KEY=<existing>        # For classification
```

### Files Added

- `penny/config/claude_code.py` - Configuration constants
- `penny/model_selector.py` - GLM vs Opus selection logic
- `penny/integrations/claude_code.py` - Build execution
- `penny/integrations/telegram_qa.py` - Q&A with Omar
- `data/omar-preferences.md` - Omar's build preferences
- `docs/CLAUDE_CODE_SETUP.md` - This file

### Database Tables Added

- `claude_sessions` - Build session tracking
- `learned_preferences` - Preferences learned from builds
- `pending_questions` - Telegram Q&A state

## Troubleshooting

### Claude CLI refuses to run (exit code 1)

**Error**: `--dangerously-skip-permissions cannot be used with root/sudo privileges for security reasons`

**Cause**: Docker container is running as root.

**Fix**: Ensure Dockerfile creates and uses non-root user:
```dockerfile
RUN groupadd -g 1001 penny && useradd -u 1001 -g penny -m penny
USER penny
```

### Database is read-only

**Error**: `sqlite3.OperationalError: attempt to write a readonly database`

**Cause**: Container user (UID 1001) cannot write to mounted volume.

**Fix**: Set proper permissions on host:
```bash
sudo chgrp -R 1001 ./data
sudo chmod -R g+w ./data
docker restart penny
```

### Claude CLI missing 'ps' command

**Error**: `Executable not found in $PATH: "ps"`

**Cause**: Python slim image doesn't include procps.

**Fix**: Add to Dockerfile:
```dockerfile
RUN apt-get install -y procps
```

### SDK returns empty output

**Error**: Build completes but output is empty.

**Cause**: Incorrect message type checking. SDK uses class names (`AssistantMessage`, `ResultMessage`), not a `.type` attribute.

**Fix**: Check message types by class name:
```python
message_type = type(message).__name__
if message_type == "AssistantMessage":
    # Extract from content blocks
elif message_type == "ResultMessage":
    # Extract from .result attribute
```

### Webhook not receiving messages

1. Verify tunnel hostname is active:
   ```bash
   curl -I https://penny.example.com/health
   ```

2. Check webhook info:
   ```bash
   source /home/khamel83/homelab/.env
   curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
   ```

3. Check Penny logs:
   ```bash
   docker logs penny --tail 50
   ```

### Build not using correct model

Check model selection reason:
```python
from penny.model_selector import get_model_reason
print(get_model_reason("your transcript", 0.85))
```

### Container missing env vars

Recreate with explicit env file:
```bash
cd /home/khamel83/homelab
docker compose -f services/penny/docker-compose.yml --env-file .env up -d --force-recreate
```

## Testing the Integration

Send a test build request:
```bash
curl -X POST https://penny.example.com/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"text": "build me a simple hello world website", "source_file": "test"}'
```

For critical builds (will use Opus if ANTHROPIC_API_KEY is set):
```bash
curl -X POST https://penny.example.com/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"text": "critical: fix the production authentication bug", "source_file": "test"}'
```
