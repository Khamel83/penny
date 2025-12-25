#!/bin/bash
# Setup Telegram webhook for Penny Claude Code builds
# Run this AFTER adding penny.example.com to Cloudflare tunnel

set -e

# Load environment
source /home/khamel83/homelab/.env

WEBHOOK_URL="https://penny.example.com/api/telegram/webhook"

echo "=== Penny Telegram Webhook Setup ==="
echo ""

# Check if public URL is accessible
echo "1. Testing public URL accessibility..."
if curl -sf "${WEBHOOK_URL%/api/telegram/webhook}/health" > /dev/null 2>&1; then
    echo "   ✅ penny.example.com is accessible"
else
    echo "   ❌ penny.example.com is NOT accessible"
    echo "   → Please add penny.example.com to your Cloudflare tunnel first"
    echo "   → See docs/CLAUDE_CODE_SETUP.md for instructions"
    exit 1
fi

# Set webhook
echo ""
echo "2. Configuring Telegram webhook..."
RESULT=$(curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
    -d "url=${WEBHOOK_URL}" \
    -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}")

if echo "$RESULT" | grep -q '"ok":true'; then
    echo "   ✅ Webhook configured successfully"
else
    echo "   ❌ Failed to configure webhook:"
    echo "   $RESULT"
    exit 1
fi

# Verify
echo ""
echo "3. Verifying webhook configuration..."
INFO=$(curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo")
WEBHOOK_ACTIVE=$(echo "$INFO" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('result',{}).get('url',''))")

if [ "$WEBHOOK_ACTIVE" = "$WEBHOOK_URL" ]; then
    echo "   ✅ Webhook verified: $WEBHOOK_URL"
else
    echo "   ⚠️  Webhook URL mismatch"
    echo "   Expected: $WEBHOOK_URL"
    echo "   Got: $WEBHOOK_ACTIVE"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Test by sending a voice memo that says:"
echo "  'Build me a simple hello world website'"
echo ""
echo "Or test directly:"
echo "  curl -X POST https://penny.example.com/api/ingest \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"text\": \"build me a hello world page\", \"source_file\": \"test\"}'"
