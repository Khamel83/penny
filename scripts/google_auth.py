#!/usr/bin/env python3
"""
One-time Google OAuth setup for Penny.

Run this once on the Mac Mini to authorize access to Google Tasks.
Opens a browser for the OAuth consent flow and saves the token.

Usage:
    python3 scripts/google_auth.py

Prerequisites — do these in Google Cloud Console first:
    1. Go to https://console.cloud.google.com/
    2. Create a project (e.g. "Penny")
    3. Go to APIs & Services → Library → search "Google Tasks API" → Enable
    4. Go to APIs & Services → OAuth consent screen
       - User Type: External
       - Fill in app name (e.g. "Penny"), your email, save
       - Add scope: .../auth/tasks (or just proceed, it will be requested at login)
    5. Go to APIs & Services → Credentials → Create Credentials → OAuth client ID
       - Application type: Desktop app
       - Name: anything (e.g. "Penny Desktop")
       - Download the JSON file
    6. Save the downloaded JSON as:  ~/.penny/google_credentials.json
    7. Run this script: python3 scripts/google_auth.py
"""
import sys
from pathlib import Path

# Allow imports from parent directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import get_config


def main():
    cfg = get_config()

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        sys.exit(
            "ERROR: Missing Google auth libraries.\n"
            "Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
        )

    SCOPES = ["https://www.googleapis.com/auth/tasks"]

    if not cfg.google_credentials_file.exists():
        sys.exit(
            f"ERROR: Credentials file not found: {cfg.google_credentials_file}\n\n"
            "Download it from Google Cloud Console:\n"
            "  APIs & Services → Credentials → OAuth 2.0 Client IDs → Download JSON\n"
            f"  Save it as: {cfg.google_credentials_file}\n\n"
            "Then run this script again."
        )

    print(f"Credentials file: {cfg.google_credentials_file}")
    print(f"Token will be saved to: {cfg.google_token_file}")
    print()
    print("Opening browser for Google authorization...")
    print("(If no browser opens, check the terminal for a URL to visit manually)")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(
        str(cfg.google_credentials_file), SCOPES
    )
    creds = flow.run_local_server(port=0)

    cfg.google_token_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.google_token_file.write_text(creds.to_json())

    print(f"Success! Token saved to: {cfg.google_token_file}")
    print()
    print("You can now start the tasks poller service:")
    print("  launchctl load ~/Library/LaunchAgents/com.penny.tasks.plist")


if __name__ == "__main__":
    main()
