#!/usr/bin/env python3
"""Tests for Penny configuration loading."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Set required env vars before importing config
os.environ.setdefault("HOME", "/tmp/penny_test_home")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot")
os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")
os.environ.setdefault(
    "GOOGLE_CREDENTIALS_FILE",
    "/tmp/penny_test_home/.penny/google_credentials.json",
)
os.environ.setdefault(
    "GOOGLE_TOKEN_FILE",
    "/tmp/penny_test_home/.penny/google_token.json",
)

import config  # noqa: E402


class ConfigTests(unittest.TestCase):
    def setUp(self):
        config._config = None
        # Force test env vars to avoid picking up real secrets from the environment
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        os.environ["TELEGRAM_BOT_TOKEN"] = "test-bot"
        os.environ["TELEGRAM_CHAT_ID"] = "12345"
        os.environ["PENNY_INGEST_TOKEN"] = "ingest-test-token"
        os.environ[
            "GOOGLE_CREDENTIALS_FILE"
        ] = "/tmp/penny_test_home/.penny/google_credentials.json"
        os.environ[
            "GOOGLE_TOKEN_FILE"
        ] = "/tmp/penny_test_home/.penny/google_token.json"

    def tearDown(self):
        config._config = None
        os.environ.pop("MAYA_DELIVERY_TIMEOUT_SECONDS", None)
        os.environ.pop("MAYA_DELIVERY_MAX_ATTEMPTS", None)
        os.environ.pop("MAYA_DELIVERY_MAX_AGE_DAYS", None)
        os.environ.pop("MAYA_MAX_ATTEMPTS", None)
        os.environ.pop("MAYA_MAX_AGE_DAYS", None)
        os.environ.pop("PENNY_INGEST_TOKEN", None)
        os.environ.pop("PENNY_WEBHOOK_HOST", None)

    def test_get_config_returns_config_with_expected_fields(self):
        cfg = config.get_config()
        self.assertEqual(cfg.llm.model, "google/gemini-2.5-flash-lite")
        self.assertEqual(cfg.google_tasks.list_name, "My Tasks")
        self.assertEqual(cfg.google_tasks.poll_interval_seconds, 180)
        self.assertIn("Groceries", cfg.apple_reminders.lists)
        self.assertEqual(cfg.apple_reminders.default_list, "Inbox")
        self.assertEqual(cfg.voice_memos.max_file_size_mb, 50)
        self.assertEqual(cfg.voice_memos.poll_interval_seconds, 60)
        self.assertEqual(cfg.webhook.port, 5678)
        self.assertEqual(cfg.webhook.host, "127.0.0.1")
        self.assertEqual(cfg.webhook.ingest_token, "ingest-test-token")
        self.assertEqual(cfg.webhook.max_request_bytes, 51 * 1024 * 1024)
        self.assertEqual(cfg.openrouter_api_key, "test-key")

    def test_webhook_host_can_be_overridden_for_lan_deployment(self):
        os.environ["PENNY_WEBHOOK_HOST"] = "0.0.0.0"
        cfg = config.get_config()
        self.assertEqual(cfg.webhook.host, "0.0.0.0")

    def test_get_config_caches_result(self):
        cfg1 = config.get_config()
        cfg2 = config.get_config()
        self.assertIs(cfg1, cfg2)

    def test_missing_config_toml_exits(self):
        with patch.object(config, "CONFIG_PATH", Path("/nonexistent/path/config.toml")):
            with self.assertRaises(SystemExit):
                config.get_config()

    def test_missing_api_key_prints_warning(self):
        os.environ.pop("OPENROUTER_API_KEY", None)
        config._config = None
        with patch("sys.stderr"):
            cfg = config.get_config()
            self.assertEqual(cfg.openrouter_api_key, "")
        os.environ["OPENROUTER_API_KEY"] = "test-key"

    def test_default_list_in_lists(self):
        cfg = config.get_config()
        self.assertIn(cfg.apple_reminders.default_list, cfg.apple_reminders.lists)

    def test_telegram_warning_suppressed_when_disabled(self):
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        config._config = None
        # telegram_enabled is false in config.toml, so no warning should be printed
        cfg = config.get_config()
        self.assertFalse(cfg.telegram_bot_token)
        self.assertFalse(cfg.telegram_chat_id)
        os.environ["TELEGRAM_BOT_TOKEN"] = "test-bot"
        os.environ["TELEGRAM_CHAT_ID"] = "12345"

    def test_config_loads_telegram_disabled_from_config_toml(self):
        cfg = config.get_config()
        self.assertFalse(cfg.notifications.telegram_enabled)

    def test_maya_config_env_overrides(self):
        os.environ["MAYA_TRANSCRIPT_URL"] = "http://localhost:8200/ingest/transcript"
        os.environ["MAYA_INGEST_TOKEN"] = "sekrit"
        config._config = None
        cfg = config.get_config()
        self.assertEqual(cfg.maya.transcript_url, "http://localhost:8200/ingest/transcript")
        self.assertEqual(cfg.maya.ingest_token, "sekrit")
        # Clean up
        os.environ.pop("MAYA_TRANSCRIPT_URL", None)
        os.environ.pop("MAYA_INGEST_TOKEN", None)

    def test_maya_delivery_timeout_is_configurable_and_bounded(self):
        for raw_value, expected in (
            ("7.5", 7.5),
            ("0", 1.0),
            ("300", 30.0),
            ("not-a-number", 10.0),
        ):
            with self.subTest(raw_value=raw_value):
                os.environ["MAYA_DELIVERY_TIMEOUT_SECONDS"] = raw_value
                config._config = None
                self.assertEqual(
                    config.get_config().maya.delivery_timeout_seconds,
                    expected,
                )

    def test_maya_retry_bounds_are_configurable_but_never_exceed_contract(self):
        for raw_attempts, raw_age_days, expected_attempts, expected_age_days in (
            ("12", "3", 12, 3),
            ("0", "0", 1, 1),
            ("200", "200", 20, 7),
            ("not-a-number", "not-a-number", 20, 7),
        ):
            with self.subTest(raw_attempts=raw_attempts, raw_age_days=raw_age_days):
                os.environ["MAYA_DELIVERY_MAX_ATTEMPTS"] = raw_attempts
                os.environ["MAYA_DELIVERY_MAX_AGE_DAYS"] = raw_age_days
                config._config = None
                cfg = config.get_config()
                self.assertEqual(cfg.maya.max_attempts, expected_attempts)
                self.assertEqual(cfg.maya.max_age_days, expected_age_days)


if __name__ == "__main__":
    unittest.main()
