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
        os.environ["PENNY_SLACK_CHANNEL_ID"] = "C-MISMATCHED"
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
                "channel": "C0BKS0QT7FU",
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
        conn = transcript_log._get_conn()
        try:
            delivery = conn.execute(
                "SELECT provider_ts FROM slack_deliveries WHERE transcript_row_id = ?",
                (row_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(dict(delivery)["provider_ts"], "123.456")

    def test_process_pending_slack_deliveries_schedules_retryable_failure(self) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        os.environ["PENNY_SLACK_CHANNEL_ID"] = "C-MISMATCHED"
        row_id = transcript_log.insert_transcript(
            content_hash="deliver2",
            source="iCloud",
            transcript="retry me",
        )
        import slack_delivery

        with patch.object(slack_delivery.requests, "post") as post_mock:
            post_mock.return_value = _SlackResponse(
                {"ok": False, "error": "ratelimited"},
                headers={"Retry-After": "17"},
            )
            delivered = slack_delivery.process_pending_slack_deliveries()

        self.assertEqual(delivered, 0)
        self.assertEqual(
            transcript_log.get_pending_slack_deliveries(transcript_id=row_id),
            [],
        )
        health = transcript_log.get_slack_delivery_health()
        self.assertEqual(health["pending_count"], 1)
        self.assertEqual(health["failed_count"], 0)
        conn = transcript_log._get_conn()
        try:
            row = conn.execute(
                "SELECT status, attempt_count, last_error, next_attempt_at "
                "FROM slack_deliveries WHERE transcript_row_id = ?",
                (row_id,),
            ).fetchone()
        finally:
            conn.close()
        stored = dict(row)
        self.assertEqual(stored["status"], "pending")
        self.assertEqual(stored["attempt_count"], 1)
        self.assertEqual(stored["last_error"], "ratelimited")
        self.assertIsNotNone(stored["next_attempt_at"])

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
            post_mock.return_value = _SlackResponse(
                {
                    "ok": False,
                    "error": "unexpectedsecretvalue",
                }
            )
            delivered = slack_delivery.process_pending_slack_deliveries()

        conn = transcript_log._get_conn()
        try:
            row = conn.execute(
                "SELECT last_error FROM slack_deliveries WHERE transcript_row_id = 1"
            ).fetchone()
        finally:
            conn.close()
        if dict(row)["last_error"] != "slack_api_error":
            self.fail("unrecognized Slack error was not replaced")
        self.assertEqual(delivered, 0)

    def test_uncertain_sent_ack_is_not_counted_and_retries_same_client_msg_id(
        self,
    ) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        os.environ["PENNY_SLACK_CHANNEL_ID"] = "C-MISMATCHED"
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
                "mark_slack_delivery_chunk_sent",
                side_effect=[OSError("database is locked"), None],
            ),
        ):
            post_mock.return_value = _SlackResponse({"ok": True, "ts": "123.456"})

            first_delivered = slack_delivery.process_pending_slack_deliveries()
            conn = transcript_log._get_conn()
            try:
                conn.execute(
                    "UPDATE slack_deliveries "
                    "SET next_attempt_at = datetime('now', '-1 second') "
                    "WHERE id = 1"
                )
                conn.commit()
            finally:
                conn.close()
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

    def test_long_transcript_sends_one_chunk_per_pass_and_retries_current_chunk(
        self,
    ) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        transcript = ("A" * 39_999) + "\n" + ("B" * 40_000) + "tail"
        row_id = transcript_log.insert_transcript(
            content_hash="deliver-long",
            source="iCloud",
            transcript=transcript,
        )
        import slack_delivery

        with patch.object(slack_delivery.requests, "post") as post_mock:
            post_mock.side_effect = [
                _SlackResponse({"ok": True, "ts": "100.001"}),
                _SlackResponse(
                    {"ok": False, "error": "ratelimited"},
                    headers={"Retry-After": "1"},
                ),
                _SlackResponse({"ok": True, "ts": "100.002"}),
                _SlackResponse({"ok": True, "ts": "100.003"}),
            ]

            first_delivered = slack_delivery.process_pending_slack_deliveries()
            conn = transcript_log._get_conn()
            try:
                after_first_pass = conn.execute(
                    """
                    SELECT status, next_chunk_index, chunk_attempt_count,
                           chunk_provider_ts, message_text
                    FROM slack_deliveries
                    WHERE transcript_row_id = ?
                    """,
                    (row_id,),
                ).fetchone()
            finally:
                conn.close()

            self.assertEqual(first_delivered, 0)
            self.assertEqual(post_mock.call_count, 1)
            first_pass_state = dict(after_first_pass)
            self.assertEqual(first_pass_state["status"], "pending")
            self.assertEqual(first_pass_state["next_chunk_index"], 1)
            self.assertEqual(first_pass_state["chunk_attempt_count"], 0)
            self.assertEqual(first_pass_state["chunk_provider_ts"], '["100.001"]')

            second_delivered = slack_delivery.process_pending_slack_deliveries()
            conn = transcript_log._get_conn()
            try:
                after_failure = conn.execute(
                    """
                    SELECT status, next_chunk_index, chunk_attempt_count,
                           chunk_provider_ts, message_text
                    FROM slack_deliveries
                    WHERE transcript_row_id = ?
                    """,
                    (row_id,),
                ).fetchone()
                conn.execute(
                    """
                    UPDATE slack_deliveries
                    SET next_attempt_at = datetime('now', '-1 second')
                    WHERE transcript_row_id = ?
                    """,
                    (row_id,),
                )
                conn.commit()
            finally:
                conn.close()

            third_delivered = slack_delivery.process_pending_slack_deliveries()
            fourth_delivered = slack_delivery.process_pending_slack_deliveries()

        self.assertEqual(second_delivered, 0)
        self.assertEqual(third_delivered, 0)
        self.assertEqual(fourth_delivered, 1)
        failed_state = dict(after_failure)
        self.assertEqual(failed_state["status"], "pending")
        self.assertEqual(failed_state["next_chunk_index"], 1)
        self.assertEqual(failed_state["chunk_attempt_count"], 1)
        self.assertEqual(failed_state["message_text"], transcript)
        self.assertEqual(
            failed_state["chunk_provider_ts"],
            '["100.001"]',
        )

        payloads = [call.kwargs["json"] for call in post_mock.call_args_list]
        self.assertEqual(len(payloads), 4)
        self.assertTrue(all(len(payload["text"]) < 40_000 for payload in payloads))
        self.assertEqual(payloads[1]["text"], payloads[2]["text"])
        self.assertEqual(payloads[1]["client_msg_id"], payloads[2]["client_msg_id"])
        self.assertNotEqual(payloads[0]["client_msg_id"], payloads[1]["client_msg_id"])
        self.assertNotEqual(payloads[1]["client_msg_id"], payloads[3]["client_msg_id"])
        self.assertEqual(
            payloads[0]["text"] + payloads[2]["text"] + payloads[3]["text"],
            transcript,
        )
        self.assertTrue(
            all(payload["channel"] == "C0BKS0QT7FU" for payload in payloads)
        )

        conn = transcript_log._get_conn()
        try:
            final_row = conn.execute(
                """
                SELECT status, next_chunk_index, chunk_attempt_count,
                       chunk_provider_ts, message_text
                FROM slack_deliveries
                WHERE transcript_row_id = ?
                """,
                (row_id,),
            ).fetchone()
        finally:
            conn.close()
        final_state = dict(final_row)
        self.assertEqual(final_state["status"], "sent")
        self.assertEqual(final_state["next_chunk_index"], 3)
        self.assertEqual(final_state["chunk_attempt_count"], 0)
        self.assertEqual(
            final_state["chunk_provider_ts"],
            '["100.001", "100.002", "100.003"]',
        )
        self.assertEqual(final_state["message_text"], transcript)

    def test_slack_warning_never_marks_delivery_sent(self) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        row_id = transcript_log.insert_transcript(
            content_hash="deliver-warning",
            source="iCloud",
            transcript="warning must fail closed",
        )
        import slack_delivery

        with patch.object(slack_delivery.requests, "post") as post_mock:
            post_mock.return_value = _SlackResponse(
                {
                    "ok": True,
                    "ts": "200.001",
                    "response_metadata": {
                        "warnings": ["message_truncated"],
                    },
                }
            )
            delivered = slack_delivery.process_pending_slack_deliveries()

        self.assertEqual(delivered, 0)
        conn = transcript_log._get_conn()
        try:
            row = conn.execute(
                """
                SELECT status, attempt_count, next_chunk_index, last_error
                FROM slack_deliveries
                WHERE transcript_row_id = ?
                """,
                (row_id,),
            ).fetchone()
        finally:
            conn.close()
        state = dict(row)
        self.assertEqual(state["status"], "pending")
        self.assertEqual(state["attempt_count"], 1)
        self.assertEqual(state["next_chunk_index"], 0)
        self.assertEqual(state["last_error"], "message_truncated")

    def test_wrong_stored_destination_fails_without_posting(self) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        row_id = transcript_log.insert_transcript(
            content_hash="deliver-wrong-destination",
            source="iCloud",
            transcript="never post outside Penny",
        )
        conn = transcript_log._get_conn()
        try:
            conn.execute(
                """
                UPDATE slack_deliveries
                SET channel_id = 'C-WRONG'
                WHERE transcript_row_id = ?
                """,
                (row_id,),
            )
            conn.commit()
        finally:
            conn.close()
        import slack_delivery

        with patch.object(slack_delivery.requests, "post") as post_mock:
            delivered = slack_delivery.process_pending_slack_deliveries()

        self.assertEqual(delivered, 0)
        post_mock.assert_not_called()
        conn = transcript_log._get_conn()
        try:
            row = conn.execute(
                """
                SELECT status, attempt_count, last_error
                FROM slack_deliveries
                WHERE transcript_row_id = ?
                """,
                (row_id,),
            ).fetchone()
        finally:
            conn.close()
        state = dict(row)
        self.assertEqual(state["status"], "pending")
        self.assertEqual(state["attempt_count"], 1)
        self.assertEqual(state["last_error"], "destination_mismatch")

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

        conn = transcript_log._get_conn()
        try:
            row = conn.execute(
                "SELECT status, last_error FROM slack_deliveries WHERE transcript_row_id = 1"
            ).fetchone()
        finally:
            conn.close()
        stored = dict(row)
        if stored["last_error"] != "provider_error:OSError":
            self.fail("provider failure was not stored as a safe category")
        self.assertEqual(stored["status"], "pending")
        rendered_logs = self._render_log_calls(warning_mock)
        rendered_logs += self._render_log_calls(error_mock)
        if secret in rendered_logs:
            self.fail("provider failure logs contained sensitive material")
        self.assertEqual(delivered, 0)

    def test_http_429_retry_after_is_respected(self) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        row_id = transcript_log.insert_transcript(
            content_hash="deliver-http429",
            source="iCloud",
            transcript="please retry after header",
        )
        import slack_delivery

        with patch.object(slack_delivery.requests, "post") as post_mock:
            post_mock.return_value = _SlackResponse(
                {"ok": False, "error": "ratelimited"},
                status_code=429,
                headers={"Retry-After": "33"},
            )
            delivered = slack_delivery.process_pending_slack_deliveries()

        self.assertEqual(delivered, 0)
        conn = transcript_log._get_conn()
        try:
            row = conn.execute(
                "SELECT attempt_count, next_attempt_at FROM slack_deliveries "
                "WHERE transcript_row_id = ?",
                (row_id,),
            ).fetchone()
        finally:
            conn.close()
        stored = dict(row)
        self.assertEqual(stored["attempt_count"], 1)
        self.assertIsNotNone(stored["next_attempt_at"])

    def test_terminal_failures_stop_retrying_after_max_attempts(self) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        row_id = transcript_log.insert_transcript(
            content_hash="deliver-terminal",
            source="iCloud",
            transcript="eventually stop retrying",
        )
        import slack_delivery

        with patch.object(slack_delivery.requests, "post") as post_mock:
            post_mock.return_value = _SlackResponse(
                {"ok": False, "error": "internal_error"}
            )
            for _ in range(6):
                slack_delivery.process_pending_slack_deliveries()
                conn = transcript_log._get_conn()
                try:
                    conn.execute(
                        "UPDATE slack_deliveries "
                        "SET next_attempt_at = datetime('now', '-1 second') "
                        "WHERE transcript_row_id = ?",
                        (row_id,),
                    )
                    conn.commit()
                finally:
                    conn.close()

        health = transcript_log.get_slack_delivery_health()
        self.assertEqual(health["pending_count"], 0)
        self.assertEqual(health["failed_count"], 1)
        pending = transcript_log.get_pending_slack_deliveries(transcript_id=row_id)
        self.assertEqual(pending, [])
        self.assertLessEqual(post_mock.call_count, 5)

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
                "mark_slack_delivery_chunk_sent",
                side_effect=acknowledgement_error,
            ),
            patch.object(slack_delivery.log, "warning") as warning_mock,
            patch.object(slack_delivery.log, "error") as error_mock,
        ):
            post_mock.return_value.json.return_value = {"ok": True, "ts": "123.456"}
            delivered = slack_delivery.process_pending_slack_deliveries()

        conn = transcript_log._get_conn()
        try:
            row = conn.execute(
                "SELECT status, last_error FROM slack_deliveries WHERE transcript_row_id = 1"
            ).fetchone()
        finally:
            conn.close()
        stored = dict(row)
        if stored["last_error"] != "acknowledgement_error:OSError":
            self.fail("acknowledgement failure was not stored as a safe category")
        self.assertEqual(stored["status"], "pending")
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
