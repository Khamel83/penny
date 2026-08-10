# iOS Shortcut Setup for Penny (Minute-by-Minute)

This is an optional alternate ingest path. The primary Penny flow remains Apple Watch Voice Memos through iCloud sync.

## Option A: Record & Send Shortcut (Recommended)

Create a new Shortcut with these actions:

1. **Record Audio** - Duration: "Ask When Running" or "Set to 0 for manual stop"
2. **Get Contents of URL** - POST to webhook
   - URL: `http://127.0.0.1:5678/upload` for a local-Mac test, or the
     protected endpoint configured for your deployment
   - Headers: `Authorization: Bearer <PENNY_INGEST_TOKEN>`
   - Request Body: Form
     - audio: Variable (select the recorded audio)
3. **Show Result** - Show the transcript returned

### Add to Home Screen:
1. Long press the Shortcut
2. "Details" → "Add to Home Screen"
3. Name it "Penny Record"

### Use on Apple Watch:
1. Open Shortcuts app on Watch
2. Tap the Shortcut
3. Record
4. Done - sends immediately

## Option B: Voice Memos + Automation (Alternative)

If you prefer the native Voice Memos app:

1. Create Shortcut with:
   - **Find Voice Memos** - Filter: "Created in last 1 minute"
   - **Repeat with Each**:
     - **Get Contents of URL** - POST to `http://127.0.0.1:5678/upload` for a
       local-Mac test, or the protected endpoint configured for your deployment
     - Header: `Authorization: Bearer <PENNY_INGEST_TOKEN>`
     - Form field: audio = Repeat Item

2. Create Automation:
   - Open Shortcuts → Automation tab
   - Create Personal Automation
   - Trigger: "When Voice Memos is opened" OR "At time intervals" (every 5 minutes)
   - Action: Run the shortcut above
   - Turn off "Notify when run"

## Webhook URL

Phase A binds the webhook to loopback (`127.0.0.1`) by default. A phone or
watch cannot reach that address directly; use it only for a local-Mac test.
There is no public Penny upload URL.

For a phone-accessible Shortcut, first deploy a protected LAN or tunnel
endpoint and use that deployment's hostname. Set `PENNY_WEBHOOK_HOST` to the
protected interface and set `PENNY_WEBHOOK_ALLOW_NONLOOPBACK=1` only after the
firewall/tunnel and the ingest token are in place. The server refuses an
unprotected non-loopback bind at startup; verify `/ready` reports the protected
bind before putting the endpoint in a Shortcut. Do not use `0.0.0.0` as a
standalone exposure setting or publish a tailnet URL from this document.

## Testing

1. Run the shortcut
2. Record something short
3. Check webhook log: `ssh macmini "tail -f ~/.penny/logs/webhook.log"`

Set `PENNY_INGEST_TOKEN` in the webhook launchd environment before using either
shortcut. `config.toml` defaults the webhook to loopback; set
`PENNY_WEBHOOK_HOST` and `PENNY_WEBHOOK_ALLOW_NONLOOPBACK=1` only for an
explicitly protected deployment. Old headerless clients receive `401
Unauthorized`.
