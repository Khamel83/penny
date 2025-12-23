"""Pytest fixtures for Penny tests."""

import os
import pytest

# Ensure no real API calls during tests
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""
os.environ["JELLYSEERR_API_KEY"] = ""
os.environ["GOOGLE_KEEP_EMAIL"] = ""
os.environ["GOOGLE_KEEP_TOKEN"] = ""
