# Claude Code Integration Setup

This document describes how to complete the Claude Code build integration for Penny.

## Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| Z.AI API Key | ✅ Configured | `ZAI_API_KEY` in homelab .env |
| Telegram Webhook Secret | ✅ Generated | `TELEGRAM_WEBHOOK_SECRET` in homelab .env |
| Penny Container | ✅ Deployed | Running with all env vars |
| Cloudflare Tunnel | ✅ Configured | penny-tunnel container + CNAME record |
| Telegram Webhook | ✅ Active | https://penny.zoheri.com/api/telegram/webhook |

## Architecture

```
Telegram → penny.zoheri.com (Cloudflare) → penny-tunnel container → penny:8000
```

## Setup Reference (Already Completed)

### Step 1: Add penny.zoheri.com to Cloudflare Tunnel

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
   | Domain | `zoheri.com` |
   | Type | `HTTP` |
   | URL | `penny:8000` |

7. Click **Save**

### Step 2: Configure Telegram Webhook

After the tunnel hostname is active, run:

```bash
source /home/khamel83/homelab/.env

curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=https://penny.zoheri.com/api/telegram/webhook" \
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
curl https://penny.zoheri.com/health
```

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

### Webhook not receiving messages

1. Verify tunnel hostname is active:
   ```bash
   curl -I https://penny.zoheri.com/health
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
curl -X POST https://penny.zoheri.com/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"text": "build me a simple hello world website", "source_file": "test"}'
```

For critical builds (will use Opus if ANTHROPIC_API_KEY is set):
```bash
curl -X POST https://penny.zoheri.com/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"text": "critical: fix the production authentication bug", "source_file": "test"}'
```
