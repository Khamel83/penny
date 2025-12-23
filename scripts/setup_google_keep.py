#!/usr/bin/env python3
"""
Google Keep Authentication Setup for Penny

This script helps you authenticate with Google Keep and obtain a master token.

IMPORTANT: Google Keep requires special authentication because:
1. gkeepapi is an unofficial library
2. Google doesn't provide official API access to Keep
3. You need an App Password (not your regular Google password)

PREREQUISITES:
1. Enable 2-Step Verification on your Google Account:
   https://myaccount.google.com/security

2. Generate an App Password:
   - Go to: https://myaccount.google.com/apppasswords
   - Select "Mail" as the app (or any app)
   - Select your device
   - Click "Generate"
   - Copy the 16-character password (e.g., "abcd efgh ijkl mnop")

3. Run this script with your email and app password

USAGE:
    python scripts/setup_google_keep.py

The script will output the master token. Add these to your environment:
    export GOOGLE_KEEP_EMAIL="your-email@gmail.com"
    export GOOGLE_KEEP_TOKEN="the-master-token"
"""

import getpass
import sys

def main():
    print("=" * 60)
    print("Google Keep Authentication Setup for Penny")
    print("=" * 60)
    print()
    print("BEFORE YOU CONTINUE:")
    print("1. Make sure 2-Step Verification is enabled on your Google Account")
    print("2. Generate an App Password at: https://myaccount.google.com/apppasswords")
    print()

    try:
        import gkeepapi
    except ImportError:
        print("ERROR: gkeepapi is not installed.")
        print("Run: pip install gkeepapi")
        sys.exit(1)

    email = input("Enter your Google email: ").strip()
    if not email:
        print("Email is required.")
        sys.exit(1)

    print()
    print("Enter your App Password (the 16-character code from Google).")
    print("Note: Spaces are optional, e.g., 'abcdefghijklmnop' or 'abcd efgh ijkl mnop'")
    password = getpass.getpass("App Password: ").replace(" ", "")

    print()
    print("Authenticating with Google Keep...")

    try:
        keep = gkeepapi.Keep()
        keep.login(email, password)
        token = keep.getMasterToken()

        print()
        print("=" * 60)
        print("SUCCESS! Authentication complete.")
        print("=" * 60)
        print()
        print("Add these environment variables to your Penny deployment:")
        print()
        print(f'export GOOGLE_KEEP_EMAIL="{email}"')
        print(f'export GOOGLE_KEEP_TOKEN="{token}"')
        print()
        print("Or add them to your .env file:")
        print()
        print(f'GOOGLE_KEEP_EMAIL={email}')
        print(f'GOOGLE_KEEP_TOKEN={token}')
        print()

        # Test by syncing
        print("Testing connection...")
        keep.sync()
        print(f"Connected! Found {len(list(keep.all()))} notes/lists.")
        print()

        # Check for existing shopping list
        shopping_list = None
        for note in keep.all():
            if hasattr(note, 'items') and note.title == "Shopping":
                shopping_list = note
                break

        if shopping_list:
            unchecked = [item.text for item in shopping_list.items if not item.checked]
            print(f"Found existing 'Shopping' list with {len(unchecked)} unchecked items.")
        else:
            print("No 'Shopping' list found - Penny will create one automatically.")

    except gkeepapi.exception.LoginException as e:
        print()
        print(f"ERROR: Login failed - {e}")
        print()
        print("Common issues:")
        print("1. Wrong App Password - make sure you copied all 16 characters")
        print("2. 2-Step Verification not enabled")
        print("3. App Password expired or revoked")
        print()
        print("Try generating a new App Password at:")
        print("https://myaccount.google.com/apppasswords")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
