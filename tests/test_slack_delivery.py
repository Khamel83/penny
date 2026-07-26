from __future__ import annotations

import logging
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["HOME"] = "/tmp/penny_test_home"
os.environ["OPENROUTER_API_KEY"] = "test-key"
os.environ["TELEGRAM_BOT_TOKEN"] = "test-bot"
os.environ["TELEGRAM_CHAT_ID"] = "12345"
os.environ["GOOGLE_CREDENTIALS_FILE"] = (
    "/tmp/penny_test_home/.penny/google_credentials.json"
)
os.environ["GOOGLE_TOKEN_FILE"] = "/tmp/penny_test_home/.penny/google_token.json"
logging.disable(logging.CRITICAL)

import transcript_log  # noqa: E402


class SlackDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_dir = tempfile.mkdtemp()
        self.db_path = Path(self.db_dir) / "test_transcripts.db"
        patch.object(transcript_log, "TRANSCRIPT_DB_PATH", self.db_path).start()
        transcript_log.init_db()
        self.addCleanup(patch.stopall)

    @staticmethod
    def _render_log_calls(mock_log) -> str:
        rendered = []
        for log_call in mock_log.call_args_list:
            message, *args = log_call.args
            rendered.append(str(message) % tuple(args))
        return "\n".join(rendered)

    def test_process_pending_slack_deliveries_posts_verbatim_text(self) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        os.environ["PENNY_SLACK_CHANNEL_ID"] = "C123"
        row_id = transcript_log.insert_transcript(
            content_hash="deliver1",
            source="iCloud",
            transcript="Line one\nLine two, unchanged.",
        )
        import slack_delivery

        with patch.object(slack_delivery.requests, "post") as post_mock:
            post_mock.return_value.json.return_value = {"ok": True, "ts": "123.456"}
            delivered = slack_delivery.process_pending_slack_deliveries()

        self.assertEqual(delivered, 1)
        post_mock.assert_called_once()
        _, kwargs = post_mock.call_args
        self.assertEqual(
            kwargs["json"],
            {
                "channel": "C123",
                "client_msg_id": str(
                    uuid.uuid5(
                        uuid.UUID("bc6feeb4-d1e8-4e84-8483-699c02146a2f"),
                        "penny:slack-delivery:1",
                    )
                ),
                "text": "Line one\nLine two, unchanged.",
                "unfurl_links": False,
                "unfurl_media": False,
            },
        )
        self.assertEqual(
            str(uuid.UUID(kwargs["json"]["client_msg_id"])),
            kwargs["json"]["client_msg_id"],
        )
        self.assertEqual(
            kwargs["headers"]["Authorization"],
            "Bearer xoxb-test",
        )
        self.assertEqual(transcript_log.get_pending_slack_deliveries(), [])
        self.assertEqual(transcript_log.get_transcript(row_id)["status"], "pending")

    def test_process_pending_slack_deliveries_keeps_failed_rows_retryable(self) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        os.environ["PENNY_SLACK_CHANNEL_ID"] = "C123"
        transcript_log.insert_transcript(
            content_hash="deliver2",
            source="iCloud",
            transcript="retry me",
        )
        import slack_delivery

        with patch.object(slack_delivery.requests, "post") as post_mock:
            post_mock.return_value.json.return_value = {"ok": False, "error": "ratelimited"}
            delivered = slack_delivery.process_pending_slack_deliveries()

        self.assertEqual(delivered, 0)
        pending = transcript_log.get_pending_slack_deliveries()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "failed")
        self.assertEqual(pending[0]["attempt_count"], 1)
        self.assertEqual(pending[0]["last_error"], "ratelimited")

    def test_unrecognized_slack_error_field_is_replaced_with_safe_category(
        self,
    ) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        transcript_log.insert_transcript(
            content_hash="deliver-unrecognized-error",
            source="iCloud",
            transcript="sanitize provider-controlled error code",
        )
        import slack_delivery

        with patch.object(slack_delivery.requests, "post") as post_mock:
            post_mock.return_value.json.return_value = {
                "ok": False,
                "error": "unexpectedsecretvalue",
            }
            delivered = slack_delivery.process_pending_slack_deliveries()

        pending = transcript_log.get_pending_slack_deliveries()
        if pending[0]["last_error"] != "slack_api_error":
            self.fail("unrecognized Slack error was not replaced")
        self.assertEqual(delivered, 0)

    def test_uncertain_sent_ack_is_not_counted_and_retries_same_client_msg_id(
        self,
    ) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        os.environ["PENNY_SLACK_CHANNEL_ID"] = "C123"
        transcript_log.insert_transcript(
            content_hash="deliver3",
            source="iCloud",
            transcript="post once despite uncertain ack",
        )
        import slack_delivery

        with (
            patch.object(slack_delivery.requests, "post") as post_mock,
            patch.object(
                slack_delivery,
                "mark_slack_delivery_sent",
                side_effect=[OSError("database is locked"), None],
            ),
        ):
            post_mock.return_value.json.return_value = {"ok": True, "ts": "123.456"}

            first_delivered = slack_delivery.process_pending_slack_deliveries()
            second_delivered = slack_delivery.process_pending_slack_deliveries()

        self.assertEqual(first_delivered, 0)
        self.assertEqual(second_delivered, 1)
        self.assertEqual(post_mock.call_count, 2)
        first_client_msg_id = post_mock.call_args_list[0].kwargs["json"]["client_msg_id"]
        second_client_msg_id = post_mock.call_args_list[1].kwargs["json"][
            "client_msg_id"
        ]
        self.assertEqual(first_client_msg_id, second_client_msg_id)
        self.assertEqual(str(uuid.UUID(first_client_msg_id)), first_client_msg_id)

    def test_provider_exception_is_sanitized_in_database_and_logs(self) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        transcript_log.insert_transcript(
            content_hash="deliver4",
            source="iCloud",
            transcript="sanitize provider failure",
        )
        import slack_delivery

        secret = "xoxb-" + "private-test-value"
        provider_error = OSError("transport included bearer " + secret)
        with (
            patch.object(
                slack_delivery.requests,
                "post",
                side_effect=provider_error,
            ),
            patch.object(slack_delivery.log, "warning") as warning_mock,
            patch.object(slack_delivery.log, "error") as error_mock,
        ):
            delivered = slack_delivery.process_pending_slack_deliveries()

        pending = transcript_log.get_pending_slack_deliveries()
        if pending[0]["last_error"] != "provider_error:OSError":
            self.fail("provider failure was not stored as a safe category")
        rendered_logs = self._render_log_calls(warning_mock)
        rendered_logs += self._render_log_calls(error_mock)
        if secret in rendered_logs:
            self.fail("provider failure logs contained sensitive material")
        self.assertEqual(delivered, 0)

    def test_acknowledgement_exceptions_are_sanitized_in_database_and_logs(
        self,
    ) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        transcript_log.insert_transcript(
            content_hash="deliver5",
            source="iCloud",
            transcript="sanitize acknowledgement failure",
        )
        import slack_delivery

        secret = "xoxb-" + "private-test-value"
        acknowledgement_error = OSError("database included bearer " + secret)
        with (
            patch.object(slack_delivery.requests, "post") as post_mock,
            patch.object(
                slack_delivery,
                "mark_slack_delivery_sent",
                side_effect=acknowledgement_error,
            ),
            patch.object(slack_delivery.log, "warning") as warning_mock,
            patch.object(slack_delivery.log, "error") as error_mock,
        ):
            post_mock.return_value.json.return_value = {"ok": True, "ts": "123.456"}
            delivered = slack_delivery.process_pending_slack_deliveries()

        pending = transcript_log.get_pending_slack_deliveries()
        if pending[0]["last_error"] != "acknowledgement_error:OSError":
            self.fail("acknowledgement failure was not stored as a safe category")
        rendered_logs = self._render_log_calls(warning_mock)
        rendered_logs += self._render_log_calls(error_mock)
        if secret in rendered_logs:
            self.fail("acknowledgement logs contained sensitive material")
        self.assertEqual(delivered, 0)

    def test_failed_acknowledgement_logging_never_renders_exception_text(
        self,
    ) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        transcript_log.insert_transcript(
            content_hash="deliver6",
            source="iCloud",
            transcript="sanitize failed acknowledgement logging",
        )
        import slack_delivery

        secret = "xoxb-" + "private-test-value"
        acknowledgement_error = OSError("database included bearer " + secret)
        with (
            patch.object(slack_delivery.requests, "post") as post_mock,
            patch.object(
                slack_delivery,
                "mark_slack_delivery_failed",
                side_effect=acknowledgement_error,
            ),
            patch.object(slack_delivery.log, "warning") as warning_mock,
            patch.object(slack_delivery.log, "error") as error_mock,
        ):
            post_mock.return_value.json.return_value = {
                "ok": False,
                "error": "ratelimited",
            }
            delivered = slack_delivery.process_pending_slack_deliveries()

        rendered_logs = self._render_log_calls(warning_mock)
        rendered_logs += self._render_log_calls(error_mock)
        if secret in rendered_logs:
            self.fail("failed acknowledgement logs contained sensitive material")
        self.assertEqual(delivered, 0)


if __name__ == "__main__":
    unittest.main()
