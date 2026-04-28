# iOS Shortcut Setup for Penny (Minute-by-Minute)

This is an optional alternate ingest path. The primary Penny flow remains Apple Watch Voice Memos through iCloud sync.

## Option A: Record & Send Shortcut (Recommended)

Create a new Shortcut with these actions:

1. **Record Audio** - Duration: "Ask When Running" or "Set to 0 for manual stop"
2. **Get Contents of URL** - POST to webhook
   - URL: `http://macmini:5678/upload`
   - Headers: None
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
     - **Get Contents of URL** - POST to `http://macmini:5678/upload`
     - Form field: audio = Repeat Item

2. Create Automation:
   - Open Shortcuts → Automation tab
   - Create Personal Automation
   - Trigger: "When Voice Memos is opened" OR "At time intervals" (every 5 minutes)
   - Action: Run the shortcut above
   - Turn off "Notify when run"

## Webhook URL

- **Public (no Tailscale needed)**: `https://omars-mac-mini.deer-panga.ts.net/upload` (use this — works from anywhere, no VPN)
- **Via Tailscale**: `http://macmini:5678/upload` (when Tailscale is active on phone)
- **Local network**: `http://100.113.216.27:5678/upload` (hardcoded Tailscale IP)

## Testing

1. Run the shortcut
2. Record something short
3. Check webhook log: `ssh macmini "tail -f ~/.penny/logs/webhook.log"`
