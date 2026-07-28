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

    @staticmethod
    def _section_text(payload: dict[str, object]) -> str:
        return "".join(
            block["text"]["text"]
            for block in payload["blocks"]
            if block["type"] == "section"
        )

    def test_process_pending_slack_deliveries_posts_verbatim_text(self) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        os.environ["PENNY_SLACK_CHANNEL_ID"] = "C-MISMATCHED"
        row_id = transcript_log.insert_transcript(
            content_hash="deliver1",
            source="iCloud",
            transcript="Line one\nLine two, unchanged.",
            ingest_state="routed",
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
                "blocks": [
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "plain_text",
                                "text": f"Penny transcript {row_id}",
                                "emoji": False,
                            }
                        ],
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "plain_text",
                            "text": "Line one\nLine two, unchanged.",
                            "emoji": False,
                        },
                    },
                ],
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

    def test_5406_character_transcript_uses_one_block_kit_parent(self) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        transcript = ("word " * 1081) + "!"
        self.assertEqual(len(transcript), 5_406)
        row_id = transcript_log.insert_transcript(
            content_hash="deliver-block-kit-5406",
            source="iCloud",
            transcript=transcript,
            ingest_state="routed",
        )
        import slack_delivery

        with patch.object(slack_delivery.requests, "post") as post_mock:
            post_mock.return_value = _SlackResponse(
                {"ok": True, "ts": "5406.001"}
            )
            delivered = slack_delivery.process_pending_slack_deliveries()

        self.assertEqual(delivered, 1)
        post_mock.assert_called_once()
        payload = post_mock.call_args.kwargs["json"]
        self.assertNotIn("thread_ts", payload)
        self.assertLessEqual(len(payload["text"]), 4_000)
        self.assertEqual(payload["blocks"][0]["type"], "context")
        self.assertEqual(
            payload["blocks"][0]["elements"][0]["text"],
            f"Penny transcript {row_id}",
        )
        section_blocks = [
            block for block in payload["blocks"] if block["type"] == "section"
        ]
        self.assertGreater(len(section_blocks), 1)
        self.assertTrue(
            all(block["text"]["type"] == "plain_text" for block in section_blocks)
        )
        self.assertTrue(
            all(len(block["text"]["text"]) <= 3_000 for block in section_blocks)
        )
        self.assertEqual(
            "".join(block["text"]["text"] for block in section_blocks),
            transcript,
        )

        conn = transcript_log._get_conn()
        try:
            delivery = conn.execute(
                """
                SELECT status, provider_ts, chunk_provider_ts
                FROM slack_deliveries
                WHERE transcript_row_id = ?
                """,
                (row_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(dict(delivery)["status"], "sent")
        self.assertEqual(dict(delivery)["provider_ts"], "5406.001")
        self.assertEqual(dict(delivery)["chunk_provider_ts"], '["5406.001"]')

    def test_process_pending_slack_waits_for_local_routing(self) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        row_id = transcript_log.insert_transcript(
            content_hash="deliver-after-routing",
            source="iCloud",
            transcript="route before provider delivery",
            ingest_state="transcribed",
        )
        import slack_delivery

        with patch.object(slack_delivery.requests, "post") as post_mock:
            before_routing = slack_delivery.process_pending_slack_deliveries()
            transcript_log.update_transcript_stages(row_id, ingest_state="routed")
            post_mock.return_value = _SlackResponse(
                {"ok": True, "ts": "123.456"}
            )
            after_routing = slack_delivery.process_pending_slack_deliveries()

        self.assertEqual(before_routing, 0)
        self.assertEqual(after_routing, 1)
        post_mock.assert_called_once()

    def test_process_pending_slack_safely_defers_legacy_null_routing_state(
        self,
    ) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        row_id = transcript_log.insert_transcript(
            content_hash="deliver-legacy-null-state",
            source="iCloud",
            transcript="legacy pending delivery",
        )
        import slack_delivery

        with patch.object(slack_delivery.requests, "post") as post_mock:
            delivered = slack_delivery.process_pending_slack_deliveries()

        self.assertEqual(delivered, 0)
        post_mock.assert_not_called()
        self.assertEqual(
            len(
                transcript_log.get_pending_slack_deliveries(
                    transcript_id=row_id,
                )
            ),
            1,
        )
        self.assertEqual(
            transcript_log.get_pending_slack_deliveries(
                transcript_id=row_id,
                routed_only=True,
            ),
            [],
        )

    def test_process_pending_slack_deliveries_schedules_retryable_failure(self) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        os.environ["PENNY_SLACK_CHANNEL_ID"] = "C-MISMATCHED"
        row_id = transcript_log.insert_transcript(
            content_hash="deliver2",
            source="iCloud",
            transcript="retry me",
            ingest_state="routed",
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
        row_id = transcript_log.insert_transcript(
            content_hash="deliver-unrecognized-error",
            source="iCloud",
            transcript="sanitize provider-controlled error code",
            ingest_state="routed",
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
                "SELECT last_error FROM slack_deliveries WHERE transcript_row_id = ?",
                (row_id,),
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
            ingest_state="routed",
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

    def test_uncertain_extreme_parent_ack_retries_same_logical_parent(
        self,
    ) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        transcript = "U" * ((3_000 * 49) + 1)
        row_id = transcript_log.insert_transcript(
            content_hash="deliver-uncertain-extreme-parent",
            source="iCloud",
            transcript=transcript,
            ingest_state="routed",
        )
        import slack_delivery

        real_ack = transcript_log.mark_slack_delivery_chunk_sent
        ack_attempts = 0

        def fail_first_ack(*args, **kwargs) -> None:
            nonlocal ack_attempts
            ack_attempts += 1
            if ack_attempts == 1:
                raise OSError("database is locked")
            real_ack(*args, **kwargs)

        with (
            patch.object(slack_delivery.requests, "post") as post_mock,
            patch.object(
                slack_delivery,
                "mark_slack_delivery_chunk_sent",
                side_effect=fail_first_ack,
            ),
        ):
            post_mock.side_effect = [
                _SlackResponse({"ok": True, "ts": "parent.001"}),
                _SlackResponse({"ok": True, "ts": "parent.001"}),
                _SlackResponse({"ok": True, "ts": "continuation.001"}),
            ]

            first_delivered = slack_delivery.process_pending_slack_deliveries()
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
            second_delivered = slack_delivery.process_pending_slack_deliveries()
            third_delivered = slack_delivery.process_pending_slack_deliveries()

        self.assertEqual(first_delivered, 0)
        self.assertEqual(second_delivered, 0)
        self.assertEqual(third_delivered, 1)
        self.assertEqual(post_mock.call_count, 3)
        payloads = [call.kwargs["json"] for call in post_mock.call_args_list]
        self.assertNotIn("thread_ts", payloads[0])
        self.assertNotIn("thread_ts", payloads[1])
        self.assertEqual(payloads[0], payloads[1])
        self.assertEqual(
            payloads[0]["client_msg_id"],
            payloads[1]["client_msg_id"],
        )
        self.assertNotEqual(
            payloads[1]["client_msg_id"],
            payloads[2]["client_msg_id"],
        )
        self.assertEqual(payloads[2]["thread_ts"], "parent.001")
        self.assertEqual(
            self._section_text(payloads[0]) + self._section_text(payloads[2]),
            transcript,
        )

    def test_extreme_transcript_persists_and_resumes_threaded_continuations(
        self,
    ) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        transcript = "E" * ((3_000 * 99) + 17)
        row_id = transcript_log.insert_transcript(
            content_hash="deliver-extreme-threaded-continuations",
            source="iCloud",
            transcript=transcript,
            ingest_state="routed",
        )
        import slack_delivery

        with patch.object(slack_delivery.requests, "post") as post_mock:
            post_mock.side_effect = [
                _SlackResponse({"ok": True, "ts": "parent.100"}),
                _SlackResponse({"ok": True, "ts": "continuation.101"}),
                _SlackResponse(
                    {"ok": False, "error": "ratelimited"},
                    headers={"Retry-After": "1"},
                ),
                _SlackResponse({"ok": True, "ts": "continuation.102"}),
            ]

            first_delivered = slack_delivery.process_pending_slack_deliveries()
            conn = transcript_log._get_conn()
            try:
                after_parent = dict(
                    conn.execute(
                        """
                        SELECT status, provider_ts, next_chunk_index,
                               chunk_provider_ts
                        FROM slack_deliveries
                        WHERE transcript_row_id = ?
                        """,
                        (row_id,),
                    ).fetchone()
                )
            finally:
                conn.close()

            second_delivered = slack_delivery.process_pending_slack_deliveries()
            conn = transcript_log._get_conn()
            try:
                after_first_continuation = dict(
                    conn.execute(
                        """
                        SELECT status, provider_ts, next_chunk_index,
                               chunk_provider_ts
                        FROM slack_deliveries
                        WHERE transcript_row_id = ?
                        """,
                        (row_id,),
                    ).fetchone()
                )
            finally:
                conn.close()

            third_delivered = slack_delivery.process_pending_slack_deliveries()
            conn = transcript_log._get_conn()
            try:
                after_failure = dict(
                    conn.execute(
                        """
                        SELECT status, provider_ts, next_chunk_index,
                               chunk_attempt_count, chunk_provider_ts
                        FROM slack_deliveries
                        WHERE transcript_row_id = ?
                        """,
                        (row_id,),
                    ).fetchone()
                )
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

            fourth_delivered = slack_delivery.process_pending_slack_deliveries()

        self.assertEqual(first_delivered, 0)
        self.assertEqual(second_delivered, 0)
        self.assertEqual(third_delivered, 0)
        self.assertEqual(fourth_delivered, 1)
        self.assertEqual(
            after_parent,
            {
                "status": "pending",
                "provider_ts": "parent.100",
                "next_chunk_index": 1,
                "chunk_provider_ts": '["parent.100"]',
            },
        )
        self.assertEqual(
            after_first_continuation,
            {
                "status": "pending",
                "provider_ts": "parent.100",
                "next_chunk_index": 2,
                "chunk_provider_ts": '["parent.100", "continuation.101"]',
            },
        )
        self.assertEqual(after_failure["status"], "pending")
        self.assertEqual(after_failure["provider_ts"], "parent.100")
        self.assertEqual(after_failure["next_chunk_index"], 2)
        self.assertEqual(after_failure["chunk_attempt_count"], 1)
        self.assertEqual(
            after_failure["chunk_provider_ts"],
            '["parent.100", "continuation.101"]',
        )

        payloads = [call.kwargs["json"] for call in post_mock.call_args_list]
        top_level_payloads = [
            payload for payload in payloads if "thread_ts" not in payload
        ]
        self.assertEqual(len(top_level_payloads), 1)
        self.assertTrue(
            all(payload["thread_ts"] == "parent.100" for payload in payloads[1:])
        )
        self.assertEqual(
            payloads[1]["blocks"][0]["elements"][0]["text"],
            f"Penny transcript {row_id} continuation 1 of 2",
        )
        self.assertEqual(
            payloads[2]["blocks"][0]["elements"][0]["text"],
            f"Penny transcript {row_id} continuation 2 of 2",
        )
        self.assertEqual(payloads[2], payloads[3])
        self.assertNotEqual(
            payloads[0]["client_msg_id"],
            payloads[1]["client_msg_id"],
        )
        self.assertNotEqual(
            payloads[1]["client_msg_id"],
            payloads[2]["client_msg_id"],
        )
        self.assertEqual(
            payloads[2]["client_msg_id"],
            payloads[3]["client_msg_id"],
        )
        self.assertTrue(all(len(payload["blocks"]) <= 50 for payload in payloads))
        self.assertTrue(
            all(
                len(block["text"]["text"]) <= 3_000
                for payload in payloads
                for block in payload["blocks"]
                if block["type"] == "section"
            )
        )
        self.assertEqual(
            self._section_text(payloads[0])
            + self._section_text(payloads[1])
            + self._section_text(payloads[3]),
            transcript,
        )

        conn = transcript_log._get_conn()
        try:
            final_state = dict(
                conn.execute(
                    """
                    SELECT status, provider_ts, next_chunk_index,
                           chunk_attempt_count, chunk_provider_ts, message_text
                    FROM slack_deliveries
                    WHERE transcript_row_id = ?
                    """,
                    (row_id,),
                ).fetchone()
            )
        finally:
            conn.close()
        self.assertEqual(final_state["status"], "sent")
        self.assertEqual(final_state["provider_ts"], "parent.100")
        self.assertEqual(final_state["next_chunk_index"], 3)
        self.assertEqual(final_state["chunk_attempt_count"], 0)
        self.assertEqual(
            final_state["chunk_provider_ts"],
            '["parent.100", "continuation.101", "continuation.102"]',
        )
        self.assertEqual(final_state["message_text"], transcript)

    def test_slack_warning_never_marks_delivery_sent(self) -> None:
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        row_id = transcript_log.insert_transcript(
            content_hash="deliver-warning",
            source="iCloud",
            transcript="warning must fail closed",
            ingest_state="routed",
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
            ingest_state="routed",
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
        row_id = transcript_log.insert_transcript(
            content_hash="deliver4",
            source="iCloud",
            transcript="sanitize provider failure",
            ingest_state="routed",
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
                "SELECT status, last_error FROM slack_deliveries "
                "WHERE transcript_row_id = ?",
                (row_id,),
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
            ingest_state="routed",
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
            ingest_state="routed",
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
        row_id = transcript_log.insert_transcript(
            content_hash="deliver5",
            source="iCloud",
            transcript="sanitize acknowledgement failure",
            ingest_state="routed",
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
                "SELECT status, last_error FROM slack_deliveries "
                "WHERE transcript_row_id = ?",
                (row_id,),
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
            ingest_state="routed",
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
