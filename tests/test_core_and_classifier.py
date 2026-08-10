from __future__ import annotations

import importlib
import hmac
import hashlib
import json
import logging
import os
import sys
import tempfile
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
from apple_effects import AppleEffectError, AppleEffectReceipt  # noqa: E402

# Mock transcript_log at import time so core.py doesn't touch a real DB
patch("core.mark_routed", autospec=True).start()
patch("core.mark_failed", autospec=True).start()


class CorePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(core)
        self.note_receipt = AppleEffectReceipt(
            "1" * 64, "note", "note-test", "succeeded",
            actual_target="Penny", transcript_id=42,
        )
        self.reminder_receipt = AppleEffectReceipt(
            "2" * 64, "reminder", "reminder-test", "succeeded",
            actual_target="Inbox", transcript_id=42,
        )
        patch.object(core, "ensure_note", return_value=self.note_receipt).start()
        patch.object(core, "ensure_reminder", return_value=self.reminder_receipt).start()
        patch.object(core, "get_transcript", return_value={
            "transcript": "fixture transcript",
            "created_at": "2026-08-10T10:00:00Z",
            "recorded_at": "2026-08-10T10:00:00Z",
        }).start()
        patch.object(core, "update_transcript_progress", return_value=True).start()
        patch.object(core, "mark_routed", return_value=True).start()
        patch.object(core, "mark_failed", return_value=None).start()
        self.addCleanup(patch.stopall)

    def tearDown(self) -> None:
        super().tearDown()
        core.cfg.maya.transcript_url = ""
        core.cfg.maya.ingest_token = ""

    def test_file_hash_never_follows_a_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "outside.m4a"
            target.write_bytes(b"private-outside-bytes")
            link = root / "memo.m4a"
            link.symlink_to(target)

            with self.assertRaises(OSError):
                core.get_file_hash(link)

    def test_file_hash_rejects_symlinked_ancestor_within_source_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "voice"
            source_root.mkdir()
            outside = root / "outside"
            nested = outside / "nested"
            nested.mkdir(parents=True)
            (nested / "secret.m4a").write_bytes(b"private-outside-bytes")
            (source_root / "jump").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(OSError):
                core.get_file_hash(
                    source_root / "jump" / "nested" / "secret.m4a",
                    source_root=source_root,
                )

    def test_local_apple_route_without_row_id_fails_closed(self) -> None:
        with (
            patch.object(core, "detect_content_type", return_value="long_note"),
            patch.object(core, "ensure_note") as note_mock,
        ):
            with self.assertRaisesRegex(core.RoutingError, "canonical_id_required"):
                core.classify_and_route("long note", source="iCloud")
        note_mock.assert_not_called()

    def test_configured_maya_is_not_called_without_canonical_row(self) -> None:
        core.cfg.maya.transcript_url = "http://maya/ingest/transcript"
        core.cfg.maya.ingest_token = "token"
        with patch.object(core, "_route_to_maya") as maya:
            with self.assertRaisesRegex(core.RoutingError, "canonical_id_required"):
                core.classify_and_route("canonical guard", source="test")
        maya.assert_not_called()

    def test_route_to_maya_helper_rejects_missing_canonical_row_before_post(self) -> None:
        core.cfg.maya.transcript_url = "http://maya/ingest/transcript"
        core.cfg.maya.ingest_token = "token"
        with patch.object(core.requests, "post") as post:
            with self.assertRaisesRegex(core.RoutingError, "canonical_id_required"):
                core._route_to_maya("canonical guard", source="test", row_id=None)
        post.assert_not_called()

    def test_legacy_maya_route_is_fail_closed_even_when_explicitly_allowed(self) -> None:
        core.cfg.maya.transcript_url = "http://maya:8200/ingest/transcript"
        core.cfg.maya.ingest_token = "test-token"
        with (
            patch.object(core.requests, "post") as post,
            patch.object(core, "detect_content_type", return_value="long_note"),
        ):
            result = core.classify_and_route(
                "Keep provider delivery in the durable Maya v2 outbox.",
                source="iCloud",
                row_id=42,
                allow_maya=True,
            )
        post.assert_not_called()
        self.assertEqual(result["reason"], "long_note")

    def test_progress_flags_do_not_replace_apple_receipt_authority(self) -> None:
        receipt = AppleEffectReceipt(
            "a" * 64, "note", "note-id", "succeeded", actual_target="Penny",
            transcript_id=42,
        )
        with (
            patch.object(core, "detect_content_type", return_value="long_note"),
            patch.object(core, "get_transcript", return_value={
                "routing_progress": json.dumps({"note_created": True}),
                "created_at": "2026-08-10T10:00:00Z",
            }),
            patch.object(core, "ensure_note", return_value=receipt) as ensure_mock,
            patch.object(core, "update_transcript_progress", return_value=True),
            patch.object(core, "mark_routed", return_value=True) as routed_mock,
        ):
            core.classify_and_route("long note", source="iCloud", row_id=42)
        ensure_mock.assert_called_once()
        routed_mock.assert_called_once()

    def test_unclear_reference_reminder_uses_canonical_time_on_replay(self) -> None:
        note = AppleEffectReceipt("b" * 64, "note", "note-id", "succeeded", actual_target="Penny", transcript_id=43)
        reminder = AppleEffectReceipt("c" * 64, "reminder", "rem-id", "succeeded", actual_target="Inbox", transcript_id=43)
        row = {
            "routing_progress": json.dumps({
                "note_created": True,
                "reference_reminder_created": True,
                "reference_reminder_text": "stale wall clock text",
            }),
            "created_at": "2026-08-10T10:00:00Z",
            "recorded_at": "2026-08-10T09:30:00Z",
        }
        with (
            patch.object(core, "detect_content_type", return_value="unclear"),
            patch.object(core, "get_transcript", return_value=row),
            patch.object(core, "ensure_note", return_value=note),
            patch.object(core, "ensure_reminder", return_value=reminder) as ensure_mock,
            patch.object(core, "update_transcript_progress", return_value=True),
            patch.object(core, "mark_routed", return_value=True),
        ):
            core.classify_and_route("maybe todo", source="iCloud", row_id=43)
        reminder_text = ensure_mock.call_args.args[1]
        self.assertNotEqual(reminder_text, "stale wall clock text")
        self.assertIn("2026-08-10", reminder_text)

    def test_duplicate_classifier_items_have_one_effect(self) -> None:
        receipt = AppleEffectReceipt("d" * 64, "reminder", "rem-id", "succeeded", actual_target="Groceries", transcript_id=44)
        with (
            patch.object(core, "detect_content_type", return_value="action_items"),
            patch.object(core, "classify", return_value={"items": [
                {"item": "buy   milk", "category": "groceries"},
                {"item": "buy milk", "category": "groceries"},
            ]}),
            patch.object(core, "ensure_reminder", return_value=receipt) as ensure_mock,
            patch.object(core, "update_transcript_progress", return_value=True),
            patch.object(core, "mark_routed", return_value=True),
        ):
            core.classify_and_route("buy milk", source="iCloud", row_id=44)
        ensure_mock.assert_called_once()

    def test_effect_errors_redact_item_text(self) -> None:
        with (
            patch.object(core, "detect_content_type", return_value="action_items"),
            patch.object(core, "classify", return_value={"items": [{"item": "secret item", "category": "inbox"}]}),
            patch.object(core, "ensure_reminder", side_effect=AppleEffectError("provider_error")),
        ):
            with self.assertRaises(core.RoutingError) as raised:
                core.classify_and_route("secret item", source="iCloud", row_id=45)
        self.assertEqual(str(raised.exception), "provider_error")
        self.assertNotIn("secret item", str(raised.exception))

    def test_send_telegram_respects_toggle(self) -> None:
        with (
            patch.object(core.cfg.notifications, "telegram_enabled", False),
            patch.object(core.requests, "post") as post_mock,
        ):
            self.assertFalse(core.send_telegram("hello"))
            post_mock.assert_not_called()

    def test_send_telegram_is_suppressed_by_repo_default_config(self) -> None:
        self.assertFalse(core.cfg.notifications.telegram_enabled)
        with patch.object(core.requests, "post") as post_mock:
            self.assertFalse(core.send_telegram("hello"))
            post_mock.assert_not_called()

    def test_notify_hermes_sends_signed_payload(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "HERMES_WEBHOOK_URL": "http://hermes.local/webhooks/penny",
                    "PENNY_WEBHOOK_SECRET": "legacy-secret-must-not-be-used",
                    "PENNY_HERMES_WEBHOOK_SECRET": "hermes-secret",
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
            b"hermes-secret", body.encode("utf-8"), hashlib.sha256
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
                    "PENNY_WEBHOOK_SECRET": "legacy-secret-must-not-be-used",
                    "PENNY_HERMES_WEBHOOK_SECRET": "",
                },
                clear=False,
            ),
            patch.object(core.requests, "post") as post_mock,
        ):
            self.assertFalse(core._notify_hermes("buy milk", [], source="iCloud"))
            post_mock.assert_not_called()

    def test_classify_and_route_is_local_first_by_default(self) -> None:
        core.cfg.maya.transcript_url = "http://maya:8200/ingest/transcript"
        core.cfg.maya.ingest_token = "test-token"
        with (
            patch.object(core, "_route_to_maya") as maya,
            patch.object(core, "detect_content_type", return_value="long_note"),
        ):
            result = core.classify_and_route("local note", source="iCloud", row_id=42)
        self.assertEqual(result["reason"], "long_note")
        maya.assert_not_called()

    def test_disabled_legacy_maya_route_records_no_progress(self) -> None:
        core.cfg.maya.transcript_url = "http://maya:8200/ingest/transcript"
        core.cfg.maya.ingest_token = "test-token"
        sentinel = "MAYA_PROVIDER_BODY_SENTINEL"
        response = unittest.mock.Mock(status_code=503, text=sentinel)
        states: list[dict[str, object]] = []

        def record(_row_id, **details):
            states.append(details)
            return True

        with (
            patch.object(core.requests, "post", return_value=response) as post,
            patch.object(core, "get_transcript", return_value={"transcript": "safe body"}),
            patch.object(core, "_record_maya_route_state", side_effect=record),
        ):
            self.assertFalse(core._route_to_maya("safe body", "iCloud", row_id=42))

        encoded = json.dumps(states, sort_keys=True)
        self.assertNotIn(sentinel, encoded)
        self.assertNotIn("response_excerpt", encoded)
        self.assertNotIn("error_message", encoded)
        self.assertNotIn("source", encoded)
        self.assertEqual(states, [])
        post.assert_not_called()

    def test_effect_progress_does_not_persist_user_text(self) -> None:
        sentinel = "PRIVATE_REMINDER_BODY_SENTINEL"
        receipt = AppleEffectReceipt(
            "f" * 64,
            "reminder",
            "provider-id",
            "succeeded",
            actual_target="Inbox",
            transcript_id=42,
        )
        with patch.object(core, "update_transcript_progress") as update:
            self.assertTrue(
                core._record_effect_progress(
                    42,
                    effect_name="reference_reminder",
                    receipt=receipt,
                    reference_reminder_text=sentinel,
                    created_reminders=[f"Inbox|{sentinel}"],
                    content_type="unclear",
                )
            )
        encoded = json.dumps(update.call_args.args[1], sort_keys=True)
        self.assertNotIn(sentinel, encoded)
        self.assertNotIn("reference_reminder_text", encoded)
        self.assertNotIn("created_reminders", encoded)

    def test_automatic_telegram_mirror_is_disabled(self) -> None:
        classify_result = {"items": [{"item": "buy milk", "category": "groceries"}]}
        with (
            patch.object(core.cfg.notifications, "telegram_enabled", True),
            patch.object(core, "detect_content_type", return_value="action_items"),
            patch.object(core, "classify", return_value=classify_result),
            patch.object(core, "send_telegram") as telegram,
        ):
            core.classify_and_route("buy milk", source="iCloud", row_id=42)
        telegram.assert_not_called()

    def test_action_items_routes_to_reminders(self) -> None:
        """action_items content type uses the existing classifier and adds reminders."""
        classify_result = {"items": [{"item": "buy milk", "category": "groceries"}]}
        with (
            patch.object(core, "detect_content_type", return_value="action_items"),
            patch.object(core, "classify", return_value=classify_result),
        ):
            result = core.classify_and_route("buy milk", source="iCloud", row_id=42)
        self.assertFalse(result.get("skip"))
        self.assertEqual(len(result["items"]), 1)

    def test_action_items_notifies_hermes_after_successful_route(self) -> None:
        classify_result = {"items": [{"item": "buy milk", "category": "groceries"}]}
        with (
            patch.object(core, "detect_content_type", return_value="action_items"),
            patch.object(core, "classify", return_value=classify_result),
            patch.object(core, "_notify_hermes", return_value=True) as notify_mock,
        ):
            core.classify_and_route("buy milk", source="iCloud", row_id=42)
        notify_mock.assert_called_once_with(
            "buy milk", classify_result["items"], source="iCloud"
        )

    def test_action_items_raises_when_reminder_write_fails(self) -> None:
        result = {"items": [{"item": "buy milk", "category": "groceries"}]}
        with (
            patch.object(core, "detect_content_type", return_value="action_items"),
            patch.object(core, "classify", return_value=result),
            patch.object(core, "ensure_reminder", side_effect=AppleEffectError("provider_error")),
        ):
            with self.assertRaises(core.RoutingError):
                core.classify_and_route("buy milk", source="Google Tasks", row_id=42)

    def test_action_items_skip_routes_to_notes(self) -> None:
        """When classifier says skip inside action_items, goes to Notes."""
        classify_result = {"skip": True, "reason": "not actionable"}
        with (
            patch.object(core, "detect_content_type", return_value="action_items"),
            patch.object(core, "classify", return_value=classify_result),
        ):
            result = core.classify_and_route("hmm whatever", source="iCloud", row_id=42)
        self.assertTrue(result.get("skip"))

    def test_long_note_goes_to_notes(self) -> None:
        with (
            patch.object(core, "detect_content_type", return_value="long_note"),
        ):
            result = core.classify_and_route(
                "long rambling journal entry...", source="iCloud", row_id=42
            )
        self.assertTrue(result.get("skip"))
        self.assertEqual(result.get("reason"), "long_note")

    def test_long_note_raises_when_note_write_fails(self) -> None:
        with (
            patch.object(core, "detect_content_type", return_value="long_note"),
            patch.object(core, "ensure_note", side_effect=AppleEffectError("provider_error")),
        ):
            with self.assertRaises(core.RoutingError):
                core.classify_and_route("long entry", source="iCloud", row_id=42)

    def test_unclear_creates_note_and_ref_reminder(self) -> None:
        with (
            patch.object(core, "detect_content_type", return_value="unclear"),
        ):
            result = core.classify_and_route("maybe a todo?", source="iCloud", row_id=42)
        self.assertTrue(result.get("skip"))
        self.assertIn("unclear", result.get("reason", ""))

    def test_unclear_reference_reminder_uses_timestamp_and_excerpt(self) -> None:
        with (
            patch.object(core, "detect_content_type", return_value="unclear"),
        ):
            core.classify_and_route("milk and eggs maybe tomorrow", source="iCloud", row_id=42)
        reminder_text = core.ensure_reminder.call_args.args[1]
        self.assertIn("Review Penny note", reminder_text)
        self.assertIn("milk and eggs", reminder_text)

    def test_unclear_raises_when_note_write_fails(self) -> None:
        with (
            patch.object(core, "detect_content_type", return_value="unclear"),
            patch.object(core, "ensure_note", side_effect=AppleEffectError("provider_error")),
        ):
            with self.assertRaises(core.RoutingError):
                core.classify_and_route("something", source="iCloud", row_id=42)

    def test_empty_transcript_returns_skip(self) -> None:
        result = core.classify_and_route("", source="iCloud")
        self.assertTrue(result.get("skip"))
        self.assertEqual(result.get("reason"), "empty transcript")

    def test_row_id_calls_mark_routed_on_success(self) -> None:
        classify_result = {"items": [{"item": "milk", "category": "groceries"}]}
        with (
            patch.object(core, "detect_content_type", return_value="action_items"),
            patch.object(core, "classify", return_value=classify_result),
            patch.object(core, "mark_routed") as mock_routed,
        ):
            core.classify_and_route("buy milk", source="iCloud", row_id=42)
            mock_routed.assert_called_once()

    def test_row_id_calls_mark_failed_on_error(self) -> None:
        with (
            patch.object(core, "detect_content_type", return_value="long_note"),
            patch.object(core, "ensure_note", side_effect=AppleEffectError("provider_error")),
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
            patch.object(core, "ensure_note", return_value=self.note_receipt) as note_mock,
            patch.object(core, "ensure_reminder", return_value=self.reminder_receipt) as reminder_mock,
            patch.object(core, "mark_routed", return_value=True),
        ):
            result = core.classify_and_route("maybe todo", source="iCloud", row_id=42)
        self.assertTrue(result.get("skip"))
        note_mock.assert_called_once()
        reminder_mock.assert_called_once()

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
            patch.object(core, "ensure_reminder", return_value=self.reminder_receipt) as reminder_mock,
            patch.object(core, "mark_routed", return_value=True),
        ):
            core.classify_and_route("milk and call dentist", source="iCloud", row_id=42)
        self.assertEqual(reminder_mock.call_count, 2)

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
        ):
            core.classify_and_route("buy milk", source="iCloud", duration_seconds=123.4, row_id=42)
        self.assertEqual(type_mock.call_args.kwargs["duration_seconds"], 123.4)
        self.assertEqual(classify_mock.call_args.kwargs["duration_seconds"], 123.4)

    def test_whisper_token_gibberish_returns_empty_transcript_skip(self) -> None:
        """Whisper tokens normalize to empty string, which returns skip immediately."""
        result = core.classify_and_route("SE<|hr|><|hr|><|hr|>", source="iCloud")
        self.assertTrue(result.get("skip"))
        self.assertEqual(result.get("reason"), "empty transcript")



    @patch("core.requests.post")
    def test_routes_to_maya_when_configured(self, mock_post):
        """Legacy Maya configuration cannot bypass the durable v2 outbox."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "ok": True, "routed_to": "clio", "routing_detail": "classified as actionable"
        }

        # Set Maya config
        core.cfg.maya.transcript_url = "http://maya:8200/ingest/transcript"
        core.cfg.maya.ingest_token = "test-token"

        with patch.object(core, "detect_content_type", return_value="long_note"):
            result = core.classify_and_route(
                "write a python script to parse CSV", source="test", row_id=42,
                allow_maya=True,
            )

        self.assertEqual(result.get("reason"), "long_note")
        mock_post.assert_not_called()

    @patch("core.requests.post")
    def test_legacy_maya_route_does_not_post_full_transcript(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "ok": True,
            "routed_to": "clio",
            "routing_detail": "accepted",
        }
        transcript = ("full transcript " * 30).strip()
        core.cfg.maya.transcript_url = "http://maya:8200/ingest/transcript"
        core.cfg.maya.ingest_token = "test-token"

        with (
            patch.object(
                core,
                "get_transcript",
                return_value={"transcript": transcript},
            ),
            patch.object(core, "_record_maya_route_state", return_value=True),
            patch.object(core, "mark_routed", return_value=True),
            patch.object(core, "detect_content_type", return_value="long_note"),
        ):
            core.classify_and_route(
                transcript,
                source="iCloud",
                row_id=468,
                allow_maya=True,
                duration_seconds=12.5,
            )

        mock_post.assert_not_called()

    @patch("core.requests.post")
    def test_legacy_maya_route_does_not_post_persisted_transcript(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "ok": True,
            "routed_to": "clio",
            "routing_detail": "accepted",
        }
        persisted_transcript = (
            "Penny contract   canary line one.\tTabbed tail  \n"
            "    Indented line two keeps punctuation, numbers 12345, and spacing exactly.\n"
            "Line three has  repeated  spaces and a trailing pad.  "
        )
        normalized_transcript = core.normalize_transcript_text(persisted_transcript)
        self.assertNotEqual(normalized_transcript, persisted_transcript)
        core.cfg.maya.transcript_url = "http://maya:8200/ingest/transcript"
        core.cfg.maya.ingest_token = "test-token"

        with (
            patch.object(core, "get_transcript", return_value={"transcript": persisted_transcript}),
            patch.object(core, "_record_maya_route_state", return_value=True),
            patch.object(core, "mark_routed", return_value=True),
            patch.object(core, "detect_content_type", return_value="long_note"),
        ):
            core.classify_and_route(
                persisted_transcript,
                source="iCloud",
                row_id=468,
                allow_maya=True,
            )

        mock_post.assert_not_called()

    def test_allow_maya_runs_only_local_receipt_path(self):
        core.cfg.maya.transcript_url = "http://maya:8200/ingest/transcript"
        core.cfg.maya.ingest_token = "test-token"
        events: list[str] = []

        response = unittest.mock.Mock()
        response.status_code = 200

        def response_json():
            events.append("json")
            return {"ok": True, "routed_to": "clio", "routing_detail": "accepted"}

        def record_mark_routed(*args, **kwargs):
            events.append("mark_routed")
            return True

        response.json.side_effect = response_json

        with (
            patch.object(core.requests, "post", return_value=response),
            patch.object(
                core,
                "get_transcript",
                return_value={"transcript": "buy milk"},
            ),
            patch.object(core, "_record_maya_route_state", return_value=True),
            patch.object(core, "mark_routed", side_effect=record_mark_routed),
            patch.object(core, "detect_content_type", return_value="long_note"),
        ):
            result = core.classify_and_route(
                "buy milk", source="test", row_id=468, allow_maya=True
            )

        self.assertEqual(result.get("reason"), "long_note")
        self.assertEqual(events, ["mark_routed"])

    def test_allow_maya_does_not_record_legacy_acceptance(self):
        core.cfg.maya.transcript_url = "http://maya:8200/ingest/transcript"
        core.cfg.maya.ingest_token = "test-token"

        response = unittest.mock.Mock()
        response.status_code = 200
        response.json.return_value = {
            "ok": True,
            "routed_to": "clio",
            "routing_detail": "accepted",
        }

        with (
            patch.object(core.requests, "post", return_value=response),
            patch.object(
                core,
                "get_transcript",
                return_value={"transcript": "buy milk"},
            ),
            patch.object(core, "_record_maya_route_state", return_value=True) as state_mock,
            patch.object(
                core,
                "mark_routed",
                return_value=True,
            ) as mark_routed_mock,
            patch.object(core, "detect_content_type", return_value="unclear"),
            patch.object(core, "ensure_note", return_value=self.note_receipt) as note_mock,
            patch.object(core, "ensure_reminder", return_value=self.reminder_receipt) as reminder_mock,
        ):
            result = core.classify_and_route(
                "buy milk", source="test", row_id=468, allow_maya=True
            )

        self.assertNotEqual(result.get("reason"), "routed_to_maya")
        self.assertEqual(mark_routed_mock.call_count, 1)
        states = [call.kwargs["state"] for call in state_mock.call_args_list]
        self.assertEqual(states, [])
        note_mock.assert_called_once()
        reminder_mock.assert_called_once()

    @patch("core.requests.post")
    def test_allow_maya_ignores_unavailable_legacy_endpoint(self, mock_post):
        """Legacy endpoint state cannot change local-first routing."""
        mock_post.return_value.status_code = 503
        mock_post.return_value.text = "Service Unavailable"

        core.cfg.maya.transcript_url = "http://maya:8200/ingest/transcript"
        core.cfg.maya.ingest_token = "test-token"

        with (
            patch.object(core, "detect_content_type", return_value="unclear"),
            patch.object(core, "mark_routed", return_value=True),
        ):
            result = core.classify_and_route(
                "buy milk", source="test", row_id=42, allow_maya=True
            )

        mock_post.assert_not_called()
        # Local routing should still happen
        self.assertNotEqual(result.get("reason"), "routed_to_maya")

    def test_falls_back_when_maya_times_out(self):
        core.cfg.maya.transcript_url = "http://maya:8200/ingest/transcript"
        core.cfg.maya.ingest_token = "test-token"

        with (
            patch.object(core.requests, "post", side_effect=core.requests.Timeout("timeout")),
            patch.object(
                core,
                "get_transcript",
                return_value={"transcript": "buy milk"},
            ),
            patch.object(core, "detect_content_type", return_value="unclear"),
            patch.object(core, "mark_routed", return_value=True),
            patch.object(core, "detect_content_type", return_value="long_note"),
        ):
            result = core.classify_and_route(
                "buy milk", source="test", row_id=468, allow_maya=True
            )

        self.assertNotEqual(result.get("reason"), "routed_to_maya")

    def test_falls_back_when_maya_transport_fails(self):
        core.cfg.maya.transcript_url = "http://maya:8200/ingest/transcript"
        core.cfg.maya.ingest_token = "test-token"

        with (
            patch.object(core.requests, "post", side_effect=core.requests.ConnectionError("boom")),
            patch.object(
                core,
                "get_transcript",
                return_value={"transcript": "buy milk"},
            ),
            patch.object(core, "detect_content_type", return_value="unclear"),
            patch.object(core, "mark_routed", return_value=True),
        ):
            result = core.classify_and_route(
                "buy milk", source="test", row_id=468, allow_maya=True
            )

        self.assertNotEqual(result.get("reason"), "routed_to_maya")

    def test_falls_back_when_maya_returns_malformed_200_json(self):
        core.cfg.maya.transcript_url = "http://maya:8200/ingest/transcript"
        core.cfg.maya.ingest_token = "test-token"

        response = unittest.mock.Mock()
        response.status_code = 200
        response.json.side_effect = ValueError("bad json")

        with (
            patch.object(core.requests, "post", return_value=response),
            patch.object(
                core,
                "get_transcript",
                return_value={"transcript": "buy milk"},
            ),
            patch.object(core, "detect_content_type", return_value="unclear"),
            patch.object(core, "mark_routed") as mark_routed_mock,
        ):
            result = core.classify_and_route("buy milk", source="test", row_id=468)

        self.assertNotEqual(result.get("reason"), "routed_to_maya")
        self.assertFalse(
            any(call.args[2] == "maya" for call in mark_routed_mock.call_args_list)
        )

    def test_falls_back_when_maya_200_body_is_not_acceptance(self):
        core.cfg.maya.transcript_url = "http://maya:8200/ingest/transcript"
        core.cfg.maya.ingest_token = "test-token"

        response = unittest.mock.Mock()
        response.status_code = 200
        response.json.return_value = {"ok": False, "error": "duplicate"}

        with (
            patch.object(core.requests, "post", return_value=response),
            patch.object(
                core,
                "get_transcript",
                return_value={"transcript": "buy milk"},
            ),
            patch.object(core, "detect_content_type", return_value="unclear"),
            patch.object(core, "mark_routed") as mark_routed_mock,
        ):
            result = core.classify_and_route("buy milk", source="test", row_id=468)

        self.assertNotEqual(result.get("reason"), "routed_to_maya")
        self.assertFalse(
            any(call.args[2] == "maya" for call in mark_routed_mock.call_args_list)
        )

    @patch("core.requests.post")
    def test_allow_maya_does_not_emit_legacy_client_refs(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "ok": True,
            "routed_to": "clio",
            "routing_detail": "duplicate accepted",
        }
        core.cfg.maya.transcript_url = "http://maya:8200/ingest/transcript"
        core.cfg.maya.ingest_token = "test-token"

        with (
            patch.object(
                core,
                "get_transcript",
                return_value={"transcript": "same transcript"},
            ),
            patch.object(core, "_record_maya_route_state", return_value=True),
            patch.object(core, "mark_routed", return_value=True),
            patch.object(core, "detect_content_type", return_value="long_note"),
        ):
            core.classify_and_route(
                "same transcript", source="iCloud", row_id=470, allow_maya=True
            )
            core.classify_and_route(
                "same transcript", source="iCloud", row_id=470, allow_maya=True
            )

        mock_post.assert_not_called()

    def test_does_not_call_maya_when_not_configured(self):
        """When Maya URL is empty, skip Maya entirely."""
        core.cfg.maya.transcript_url = ""
        core.cfg.maya.ingest_token = ""

        with (
            patch.object(core, "detect_content_type", return_value="unclear"),
        ):
            result = core.classify_and_route("hello", source="test", row_id=42)

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
                core.classify_and_route(
                    "buy milk", "test", row_id=42, allow_maya=False
                )

        assert calls["maya"] == 0

    def test_maya_origin_always_disallows_legacy_maya_routing(self):
        with (
            patch.object(core, "_route_to_maya") as route_to_maya,
            patch.object(core, "detect_content_type", return_value="long_note"),
        ):
            result = core.classify_and_route(
                "Keep this Maya-originated transcript local.",
                source="maya:icloud",
                row_id=42,
            )

        route_to_maya.assert_not_called()
        self.assertEqual(result["reason"], "long_note")


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

    def test_classifier_provider_errors_log_only_bounded_codes(self) -> None:
        sentinel = "CLASSIFIER_PROVIDER_BODY_SENTINEL"
        response = unittest.mock.Mock()
        response.raise_for_status = lambda: None
        response.json.return_value = {"unexpected": sentinel}
        with (
            patch.object(classifier.requests, "post", return_value=response),
            patch.object(classifier, "log") as log_mock,
        ):
            result = classifier.classify("buy milk", api_key="key", model="model")
        self.assertTrue(result.get("fallback"))
        self.assertNotIn(sentinel, repr(log_mock.mock_calls))

        with (
            patch.object(
                classifier.requests,
                "post",
                side_effect=RuntimeError(sentinel),
            ),
            patch.object(classifier, "log") as log_mock,
        ):
            result = classifier.classify("buy milk", api_key="key", model="model")
        self.assertTrue(result.get("fallback"))
        self.assertNotIn(sentinel, repr(log_mock.mock_calls))


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

    def test_content_type_provider_body_is_not_logged(self) -> None:
        sentinel = "CONTENT_TYPE_PROVIDER_BODY_SENTINEL"
        with (
            patch.object(classifier.requests, "post") as post_mock,
            patch.object(classifier, "log") as log_mock,
        ):
            post_mock.return_value.status_code = 200
            post_mock.return_value.raise_for_status = lambda: None
            post_mock.return_value.json.return_value = {
                "choices": [{"message": {"content": sentinel}}]
            }
            result = classifier.detect_content_type("text", api_key="key", model="model")
        self.assertEqual(result, "unclear")
        self.assertNotIn(sentinel, repr(log_mock.mock_calls))


if __name__ == "__main__":
    unittest.main()
