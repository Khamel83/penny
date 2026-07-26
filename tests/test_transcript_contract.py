from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import unittest
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

import core  # noqa: E402
import slack_delivery  # noqa: E402
import transcript_log  # noqa: E402


class _SlackResponse:
    def __init__(
        self,
        payload: dict[str, object],
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self) -> dict[str, object]:
        return self._payload


class TranscriptContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_dir = tempfile.mkdtemp()
        self.db_path = Path(self.db_dir) / "test_transcripts.db"
        patch.object(transcript_log, "TRANSCRIPT_DB_PATH", self.db_path).start()
        transcript_log.init_db()
        self.addCleanup(patch.stopall)

        self.original_channel = os.environ.get("PENNY_SLACK_CHANNEL_ID")
        self.original_bot_token = os.environ.get("PENNY_SLACK_BOT_TOKEN")
        os.environ["PENNY_SLACK_CHANNEL_ID"] = "C0BKS0QT7FU"
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        self.addCleanup(self._restore_slack_env)

        self.original_maya_url = core.cfg.maya.transcript_url
        self.original_maya_token = core.cfg.maya.ingest_token
        core.cfg.maya.transcript_url = "http://maya:8200/ingest/transcript"
        core.cfg.maya.ingest_token = "test-token"
        self.addCleanup(self._restore_maya_config)

    def _restore_slack_env(self) -> None:
        if self.original_channel is None:
            os.environ.pop("PENNY_SLACK_CHANNEL_ID", None)
        else:
            os.environ["PENNY_SLACK_CHANNEL_ID"] = self.original_channel
        if self.original_bot_token is None:
            os.environ.pop("PENNY_SLACK_BOT_TOKEN", None)
        else:
            os.environ["PENNY_SLACK_BOT_TOKEN"] = self.original_bot_token

    def _restore_maya_config(self) -> None:
        core.cfg.maya.transcript_url = self.original_maya_url
        core.cfg.maya.ingest_token = self.original_maya_token

    def test_icloud_transcript_contract_preserves_exact_body_across_maya_and_slack_retry(
        self,
    ) -> None:
        transcript = (
            "Penny contract canary line one.\n"
            "Line two keeps punctuation, numbers 12345, and spacing exactly.\n"
            "Line three proves this is the full durable body."
        )

        row_id = transcript_log.insert_transcript(
            content_hash="task5-contract-hash",
            source="iCloud",
            transcript=transcript,
        )

        self.assertIsNotNone(row_id)
        stored_row = transcript_log.get_transcript(row_id)
        self.assertEqual(stored_row["source"], "iCloud")
        self.assertEqual(stored_row["transcript"], transcript)

        maya_response = unittest.mock.Mock()
        maya_response.status_code = 200
        maya_response.json.return_value = {
            "ok": True,
            "routed_to": "clio",
            "routing_detail": "accepted",
        }

        with patch.object(core.requests, "post", return_value=maya_response) as maya_post:
            route_result = core.classify_and_route(
                transcript,
                source="iCloud",
                row_id=row_id,
            )

        self.assertEqual(route_result, {"skip": True, "reason": "routed_to_maya"})
        maya_payload = maya_post.call_args.kwargs["json"]
        self.assertEqual(maya_payload["transcript"], transcript)
        self.assertEqual(maya_payload["source"], "iCloud")
        self.assertEqual(maya_payload["client_ref"], f"penny:{row_id}")

        routed_row = transcript_log.get_transcript(row_id)
        self.assertEqual(routed_row["routed_to"], "maya")
        routing_progress = json.loads(routed_row["routing_progress"])
        self.assertEqual(routing_progress["maya_route"]["state"], "accepted")
        self.assertEqual(routing_progress["maya_route"]["client_ref"], f"penny:{row_id}")

        pending = transcript_log.get_pending_slack_deliveries(transcript_id=row_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["channel_id"], "C0BKS0QT7FU")
        self.assertEqual(pending[0]["message_text"], transcript)

        with patch.object(slack_delivery.requests, "post") as slack_post:
            slack_post.side_effect = [
                _SlackResponse(
                    {"ok": False, "error": "ratelimited"},
                    headers={"Retry-After": "17"},
                ),
                _SlackResponse({"ok": True, "ts": "999.001"}),
            ]

            first_delivered = slack_delivery.process_pending_slack_deliveries()
            self.assertEqual(first_delivered, 0)

            conn = transcript_log._get_conn()
            try:
                first_attempt = conn.execute(
                    "SELECT status, attempt_count, last_error, next_attempt_at, message_text, channel_id "
                    "FROM slack_deliveries WHERE transcript_row_id = ?",
                    (row_id,),
                ).fetchone()
                conn.execute(
                    "UPDATE slack_deliveries "
                    "SET next_attempt_at = datetime('now', '-1 second') "
                    "WHERE transcript_row_id = ?",
                    (row_id,),
                )
                conn.commit()
            finally:
                conn.close()

            second_delivered = slack_delivery.process_pending_slack_deliveries()

        self.assertEqual(second_delivered, 1)
        first_attempt_row = dict(first_attempt)
        self.assertEqual(first_attempt_row["status"], "pending")
        self.assertEqual(first_attempt_row["attempt_count"], 1)
        self.assertEqual(first_attempt_row["last_error"], "ratelimited")
        self.assertIsNotNone(first_attempt_row["next_attempt_at"])
        self.assertEqual(first_attempt_row["message_text"], transcript)
        self.assertEqual(first_attempt_row["channel_id"], "C0BKS0QT7FU")

        self.assertEqual(slack_post.call_count, 2)
        first_payload = slack_post.call_args_list[0].kwargs["json"]
        second_payload = slack_post.call_args_list[1].kwargs["json"]
        self.assertEqual(first_payload["channel"], "C0BKS0QT7FU")
        self.assertEqual(second_payload["channel"], "C0BKS0QT7FU")
        self.assertEqual(first_payload["text"], transcript)
        self.assertEqual(second_payload["text"], transcript)

        conn = transcript_log._get_conn()
        try:
            delivery_row = conn.execute(
                "SELECT status, attempt_count, provider_ts, message_text, channel_id "
                "FROM slack_deliveries WHERE transcript_row_id = ?",
                (row_id,),
            ).fetchone()
        finally:
            conn.close()

        final_delivery = dict(delivery_row)
        self.assertEqual(final_delivery["status"], "sent")
        self.assertEqual(final_delivery["attempt_count"], 1)
        self.assertEqual(final_delivery["provider_ts"], "999.001")
        self.assertEqual(final_delivery["message_text"], transcript)
        self.assertEqual(final_delivery["channel_id"], "C0BKS0QT7FU")
        self.assertEqual(transcript_log.get_pending_slack_deliveries(transcript_id=row_id), [])

