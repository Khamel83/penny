from __future__ import annotations

import importlib
import hmac
import hashlib
import json
import logging
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Keep any test-created runtime files inside /tmp (sandbox-writable).
os.environ["HOME"] = "/tmp/penny_test_home"
os.environ["OPENROUTER_API_KEY"] = "test-key"
os.environ["TELEGRAM_BOT_TOKEN"] = "test-bot"
os.environ["TELEGRAM_CHAT_ID"] = "12345"
os.environ["GOOGLE_CREDENTIALS_FILE"] = (
    "/tmp/penny_test_home/.penny/google_credentials.json"
)
os.environ["GOOGLE_TOKEN_FILE"] = "/tmp/penny_test_home/.penny/google_token.json"
logging.disable(logging.CRITICAL)

import classifier  # noqa: E402
import core  # noqa: E402

# Mock transcript_log at import time so core.py doesn't touch a real DB
patch("core.mark_routed", autospec=True).start()
patch("core.mark_failed", autospec=True).start()


class CorePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(core)

    def tearDown(self) -> None:
        super().tearDown()
        core.cfg.maya.transcript_url = ""
        core.cfg.maya.ingest_token = ""

    def test_send_telegram_respects_toggle(self) -> None:
        with (
            patch.object(core.cfg.notifications, "telegram_enabled", False),
            patch.object(core.requests, "post") as post_mock,
        ):
            self.assertFalse(core.send_telegram("hello"))
            post_mock.assert_not_called()

    def test_notify_hermes_sends_signed_payload(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "HERMES_WEBHOOK_URL": "http://hermes.local/webhooks/penny",
                    "PENNY_WEBHOOK_SECRET": "test-secret",
                },
                clear=False,
            ),
            patch.object(core.requests, "post") as post_mock,
        ):
            post_mock.return_value.raise_for_status = lambda: None
            ok = core._notify_hermes(
                "buy milk",
                [{"item": "buy milk", "category": "groceries"}],
                source="iCloud",
            )

        self.assertTrue(ok)
        post_mock.assert_called_once()
        args, kwargs = post_mock.call_args
        self.assertEqual(args[0], "http://hermes.local/webhooks/penny")
        body = kwargs["data"]
        expected_signature = hmac.new(
            b"test-secret", body.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        self.assertEqual(
            kwargs["headers"]["X-Webhook-Signature"], expected_signature
        )
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
        self.assertEqual(json.loads(body)["transcript"], "buy milk")
        self.assertEqual(kwargs["timeout"], 3)

    def test_notify_hermes_skips_when_secret_missing(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "HERMES_WEBHOOK_URL": "http://hermes.local/webhooks/penny",
                    "PENNY_WEBHOOK_SECRET": "",
                },
                clear=False,
            ),
            patch.object(core.requests, "post") as post_mock,
        ):
            self.assertFalse(core._notify_hermes("buy milk", [], source="iCloud"))
            post_mock.assert_not_called()

    def test_action_items_routes_to_reminders(self) -> None:
        """action_items content type uses the existing classifier and adds reminders."""
        classify_result = {"items": [{"item": "buy milk", "category": "groceries"}]}
        with (
            patch.object(core, "detect_content_type", return_value="action_items"),
            patch.object(core, "classify", return_value=classify_result),
            patch.object(core, "add_reminder", return_value=True),
        ):
            result = core.classify_and_route("buy milk", source="iCloud")
        self.assertFalse(result.get("skip"))
        self.assertEqual(len(result["items"]), 1)

    def test_action_items_notifies_hermes_after_successful_route(self) -> None:
        classify_result = {"items": [{"item": "buy milk", "category": "groceries"}]}
        with (
            patch.object(core, "detect_content_type", return_value="action_items"),
            patch.object(core, "classify", return_value=classify_result),
            patch.object(core, "add_reminder", return_value=True),
            patch.object(core, "_notify_hermes", return_value=True) as notify_mock,
        ):
            core.classify_and_route("buy milk", source="iCloud")
        notify_mock.assert_called_once_with(
            "buy milk", classify_result["items"], source="iCloud"
        )

    def test_action_items_raises_when_reminder_write_fails(self) -> None:
        result = {"items": [{"item": "buy milk", "category": "groceries"}]}
        with (
            patch.object(core, "detect_content_type", return_value="action_items"),
            patch.object(core, "classify", return_value=result),
            patch.object(core, "add_reminder", return_value=False),
        ):
            with self.assertRaises(core.RoutingError):
                core.classify_and_route("buy milk", source="Google Tasks")

    def test_action_items_skip_routes_to_notes(self) -> None:
        """When classifier says skip inside action_items, goes to Notes."""
        classify_result = {"skip": True, "reason": "not actionable"}
        with (
            patch.object(core, "detect_content_type", return_value="action_items"),
            patch.object(core, "classify", return_value=classify_result),
            patch.object(core, "add_note", return_value=True),
        ):
            result = core.classify_and_route("hmm whatever", source="iCloud")
        self.assertTrue(result.get("skip"))

    def test_long_note_goes_to_notes(self) -> None:
        with (
            patch.object(core, "detect_content_type", return_value="long_note"),
            patch.object(core, "add_note", return_value=True),
        ):
            result = core.classify_and_route(
                "long rambling journal entry...", source="iCloud"
            )
        self.assertTrue(result.get("skip"))
        self.assertEqual(result.get("reason"), "long_note")

    def test_long_note_raises_when_note_write_fails(self) -> None:
        with (
            patch.object(core, "detect_content_type", return_value="long_note"),
            patch.object(core, "add_note", return_value=False),
        ):
            with self.assertRaises(core.RoutingError):
                core.classify_and_route("long entry", source="iCloud")

    def test_unclear_creates_note_and_ref_reminder(self) -> None:
        with (
            patch.object(core, "detect_content_type", return_value="unclear"),
            patch.object(core, "add_note", return_value=True),
            patch.object(core, "add_reminder", return_value=True),
        ):
            result = core.classify_and_route("maybe a todo?", source="iCloud")
        self.assertTrue(result.get("skip"))
        self.assertIn("unclear", result.get("reason", ""))

    def test_unclear_reference_reminder_uses_timestamp_and_excerpt(self) -> None:
        with (
            patch.object(core, "detect_content_type", return_value="unclear"),
            patch.object(core, "add_note", return_value=True),
            patch.object(core, "add_reminder", return_value=True) as reminder_mock,
        ):
            core.classify_and_route("milk and eggs maybe tomorrow", source="iCloud")
        reminder_text = reminder_mock.call_args.args[0]
        self.assertIn("Review Penny note", reminder_text)
        self.assertIn("milk and eggs", reminder_text)

    def test_unclear_raises_when_note_write_fails(self) -> None:
        with (
            patch.object(core, "detect_content_type", return_value="unclear"),
            patch.object(core, "add_note", return_value=False),
        ):
            with self.assertRaises(core.RoutingError):
                core.classify_and_route("something", source="iCloud")

    def test_empty_transcript_returns_skip(self) -> None:
        result = core.classify_and_route("", source="iCloud")
        self.assertTrue(result.get("skip"))
        self.assertEqual(result.get("reason"), "empty transcript")

    def test_row_id_calls_mark_routed_on_success(self) -> None:
        classify_result = {"items": [{"item": "milk", "category": "groceries"}]}
        with (
            patch.object(core, "detect_content_type", return_value="action_items"),
            patch.object(core, "classify", return_value=classify_result),
            patch.object(core, "add_reminder", return_value=True),
            patch.object(core, "mark_routed") as mock_routed,
        ):
            core.classify_and_route("buy milk", source="iCloud", row_id=42)
            mock_routed.assert_called_once()

    def test_row_id_calls_mark_failed_on_error(self) -> None:
        with (
            patch.object(core, "detect_content_type", return_value="long_note"),
            patch.object(core, "add_note", return_value=False),
            patch.object(core, "mark_failed") as mock_failed,
        ):
            with self.assertRaises(core.RoutingError):
                core.classify_and_route("long", source="iCloud", row_id=42)
            mock_failed.assert_called_once()

    def test_retry_skips_already_created_note_and_reference_reminder(self) -> None:
        progress = {
            "note_created": True,
            "reference_reminder_created": True,
            "reference_reminder_text": "Review Penny note (2026-04-08 9:00 AM): maybe todo",
        }
        with (
            patch.object(core, "detect_content_type", return_value="unclear"),
            patch.object(
                core,
                "get_transcript",
                return_value={"routing_progress": json.dumps(progress)},
            ),
            patch.object(core, "add_note") as note_mock,
            patch.object(core, "add_reminder") as reminder_mock,
        ):
            result = core.classify_and_route("maybe todo", source="iCloud", row_id=42)
        self.assertTrue(result.get("skip"))
        note_mock.assert_not_called()
        reminder_mock.assert_not_called()

    def test_retry_skips_existing_reminders(self) -> None:
        progress = {"created_reminders": ["Groceries|milk"]}
        classify_result = {
            "items": [
                {"item": "milk", "category": "groceries"},
                {"item": "call dentist", "category": "health"},
            ]
        }
        with (
            patch.object(core, "detect_content_type", return_value="action_items"),
            patch.object(core, "classify", return_value=classify_result),
            patch.object(
                core,
                "get_transcript",
                return_value={"routing_progress": json.dumps(progress)},
            ),
            patch.object(core, "add_reminder", return_value=True) as reminder_mock,
        ):
            core.classify_and_route("milk and call dentist", source="iCloud", row_id=42)
        reminder_mock.assert_called_once_with("call dentist", "Health", "Inbox")

    def test_duration_passed_into_classification(self) -> None:
        with (
            patch.object(
                core, "detect_content_type", return_value="action_items"
            ) as type_mock,
            patch.object(
                core,
                "classify",
                return_value={"items": [{"item": "buy milk", "category": "groceries"}]},
            ) as classify_mock,
            patch.object(core, "add_reminder", return_value=True),
        ):
            core.classify_and_route("buy milk", source="iCloud", duration_seconds=123.4)
        self.assertEqual(type_mock.call_args.kwargs["duration_seconds"], 123.4)
        self.assertEqual(classify_mock.call_args.kwargs["duration_seconds"], 123.4)

    def test_whisper_token_gibberish_returns_empty_transcript_skip(self) -> None:
        """Whisper tokens normalize to empty string, which returns skip immediately."""
        result = core.classify_and_route("SE<|hr|><|hr|><|hr|>", source="iCloud")
        self.assertTrue(result.get("skip"))
        self.assertEqual(result.get("reason"), "empty transcript")



    @patch("core.requests.post")
    def test_routes_to_maya_when_configured(self, mock_post):
        """When Maya is configured and returns 200, route via Maya, skip local."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "ok": True, "routed_to": "clio", "routing_detail": "classified as actionable"
        }

        # Set Maya config
        core.cfg.maya.transcript_url = "http://maya:8200/ingest/transcript"
        core.cfg.maya.ingest_token = "test-token"

        result = core.classify_and_route("write a python script to parse CSV", source="test")

        self.assertEqual(result.get("reason"), "routed_to_maya")
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["json"]["transcript"], "write a python script to parse CSV")
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer test-token")
        self.assertIn("/ingest/transcript", mock_post.call_args[0][0])

    @patch("core.requests.post")
    def test_falls_back_when_maya_unavailable(self, mock_post):
        """When Maya returns non-2xx, fall back to local routing."""
        mock_post.return_value.status_code = 503
        mock_post.return_value.text = "Service Unavailable"

        core.cfg.maya.transcript_url = "http://maya:8200/ingest/transcript"
        core.cfg.maya.ingest_token = "test-token"

        with (
            patch.object(core, "detect_content_type", return_value="unclear"),
            patch.object(core, "add_note", return_value=True),
            patch.object(core, "add_reminder", return_value=True),
        ):
            result = core.classify_and_route("buy milk", source="test")

        mock_post.assert_called_once()
        # Local routing should still happen
        self.assertNotEqual(result.get("reason"), "routed_to_maya")

    def test_does_not_call_maya_when_not_configured(self):
        """When Maya URL is empty, skip Maya entirely."""
        core.cfg.maya.transcript_url = ""
        core.cfg.maya.ingest_token = ""

        with (
            patch.object(core, "detect_content_type", return_value="unclear"),
            patch.object(core, "add_note", return_value=True),
            patch.object(core, "add_reminder", return_value=True),
        ):
            result = core.classify_and_route("hello", source="test")

        self.assertNotEqual(result.get("reason"), "routed_to_maya")

    def test_classify_and_route_skips_maya_when_disallowed(self):
        """allow_maya=False must never call _route_to_maya (prevents Maya->Penny->Maya loops)."""
        calls = {"maya": 0}

        def fake_route_to_maya(*args, **kwargs):
            calls["maya"] += 1
            return True

        with (
            patch.object(core, "_route_to_maya", fake_route_to_maya),
            patch.object(
                core, "detect_content_type",
                lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stop-here")),
            ),
        ):
            with pytest.raises(RuntimeError, match="stop-here"):
                core.classify_and_route("buy milk", "test", allow_maya=False)

        assert calls["maya"] == 0


class ClassifierFallbackTests(unittest.TestCase):
    def test_normalize_transcript_strips_whisper_tokens(self) -> None:
        self.assertEqual(
            core.normalize_transcript_text("hello <|hr|> world"), "hello world"
        )
        self.assertEqual(core.normalize_transcript_text("SE<|hr|><|hr|><|hr|>"), "")

    def test_fallback_preserves_full_transcript(self) -> None:
        transcript = "abc123 " * 100
        result = classifier.classify(transcript, api_key="", model="unused")
        self.assertTrue(result.get("fallback"))
        self.assertEqual(result["items"][0]["item"], transcript.strip())

    def test_truncation_on_long_transcript(self) -> None:
        transcript = "word " * 3000  # way over 4000 chars
        with (
            patch.object(classifier, "log"),
            patch.object(classifier.requests, "post") as post_mock,
        ):
            post_mock.return_value.status_code = 200
            post_mock.return_value.raise_for_status = lambda: None
            post_mock.return_value.json.return_value = {
                "choices": [
                    {
                        "message": {
                            "content": '{"items": [{"item": "x", "category": "inbox"}]}'
                        }
                    }
                ]
            }
            classifier.classify(transcript, api_key="key", model="model")
            call_args = post_mock.call_args[1]["json"]["messages"][1]["content"]
            self.assertIn("[...truncated]", call_args)


class DetectContentTypeTests(unittest.TestCase):
    def test_returns_unclear_on_no_api_key(self) -> None:
        result = classifier.detect_content_type("some text", api_key="", model="unused")
        self.assertEqual(result, "unclear")

    def test_returns_unclear_on_api_failure(self) -> None:
        with patch.object(
            classifier.requests, "post", side_effect=Exception("network error")
        ):
            result = classifier.detect_content_type(
                "some text", api_key="key", model="model"
            )
            self.assertEqual(result, "unclear")

    def test_returns_action_items_from_llm(self) -> None:
        with patch.object(classifier.requests, "post") as post_mock:
            post_mock.return_value.status_code = 200
            post_mock.return_value.raise_for_status = lambda: None
            post_mock.return_value.json.return_value = {
                "choices": [{"message": {"content": "action_items"}}]
            }
            result = classifier.detect_content_type(
                "buy milk", api_key="key", model="model"
            )
            self.assertEqual(result, "action_items")

    def test_returns_long_note_from_llm(self) -> None:
        with patch.object(classifier.requests, "post") as post_mock:
            post_mock.return_value.status_code = 200
            post_mock.return_value.raise_for_status = lambda: None
            post_mock.return_value.json.return_value = {
                "choices": [{"message": {"content": "long_note"}}]
            }
            result = classifier.detect_content_type(
                "long rambling journal entry...", api_key="key", model="model"
            )
            self.assertEqual(result, "long_note")

    def test_returns_unclear_on_bad_response(self) -> None:
        with patch.object(classifier.requests, "post") as post_mock:
            post_mock.return_value.status_code = 200
            post_mock.return_value.raise_for_status = lambda: None
            post_mock.return_value.json.return_value = {
                "choices": [{"message": {"content": "something_weird"}}]
            }
            result = classifier.detect_content_type(
                "text", api_key="key", model="model"
            )
            self.assertEqual(result, "unclear")


if __name__ == "__main__":
    unittest.main()
