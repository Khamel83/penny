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


if __name__ == "__main__":
    unittest.main()
