from __future__ import annotations

import importlib
import logging
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Keep any test-created runtime files inside /tmp (sandbox-writable).
os.environ["HOME"] = "/tmp/penny_test_home"
os.environ["OPENROUTER_API_KEY"] = "test-key"
os.environ["TELEGRAM_BOT_TOKEN"] = "test-bot"
os.environ["TELEGRAM_CHAT_ID"] = "12345"
os.environ["GOOGLE_CREDENTIALS_FILE"] = "/tmp/penny_test_home/.penny/google_credentials.json"
os.environ["GOOGLE_TOKEN_FILE"] = "/tmp/penny_test_home/.penny/google_token.json"
logging.disable(logging.CRITICAL)

import classifier  # noqa: E402
import core  # noqa: E402


class CorePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        # Fresh module globals are easier than hand-resetting patched config objects.
        importlib.reload(core)

    def test_send_telegram_respects_toggle(self) -> None:
        with patch.object(core.cfg.notifications, "telegram_enabled", False), patch.object(
            core.requests, "post"
        ) as post_mock:
            self.assertFalse(core.send_telegram("hello"))
            post_mock.assert_not_called()

    def test_classify_and_route_raises_when_note_write_fails(self) -> None:
        with patch.object(core, "classify", return_value={"skip": True, "reason": "note"}), patch.object(
            core, "add_note", return_value=False
        ):
            with self.assertRaises(core.RoutingError):
                core.classify_and_route("journal entry", source="iCloud")

    def test_classify_and_route_raises_when_reminder_write_fails(self) -> None:
        result = {"items": [{"item": "buy milk", "category": "groceries"}]}
        with patch.object(core, "classify", return_value=result), patch.object(
            core, "add_reminder", return_value=False
        ):
            with self.assertRaises(core.RoutingError):
                core.classify_and_route("buy milk", source="Google Tasks")

    def test_whisper_token_gibberish_becomes_intelligible_placeholder_note(self) -> None:
        with patch.object(core, "classify", return_value={"skip": True, "reason": "empty transcript"}) as classify_mock, patch.object(
            core, "add_note", return_value=True
        ) as add_note_mock:
            result = core.classify_and_route("SE<|hr|><|hr|><|hr|>", source="iCloud")

        self.assertTrue(result.get("skip"))
        classify_mock.assert_called_once_with("", core.cfg.openrouter_api_key, core.cfg.llm.model)
        add_note_mock.assert_called_once_with(
            "(No intelligible speech detected.)",
            folder_name="Penny",
            source="iCloud",
        )


class ClassifierFallbackTests(unittest.TestCase):
    def test_normalize_transcript_strips_whisper_tokens(self) -> None:
        self.assertEqual(core.normalize_transcript_text("hello <|hr|> world"), "hello world")
        self.assertEqual(core.normalize_transcript_text("SE<|hr|><|hr|><|hr|>"), "")

    def test_fallback_preserves_full_transcript(self) -> None:
        transcript = "abc123 " * 100
        result = classifier.classify(transcript, api_key="", model="unused")
        self.assertTrue(result.get("fallback"))
        self.assertEqual(result["items"][0]["item"], transcript.strip())


if __name__ == "__main__":
    unittest.main()
