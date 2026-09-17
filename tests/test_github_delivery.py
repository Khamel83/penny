import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from github_delivery import (
    _classify_triage_outcome,
    _run_janitor_triage,
    process_pending_github_deliveries,
)
from slack_delivery import SlackAPIError


class RunJanitorTriageTestCase(unittest.TestCase):
    def test_parses_filed_json_from_stdout(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"status": "filed", "repo": "Khamel83/x", "issue_url": "https://x/1"}\n',
            stderr="",
        )
        with patch("github_delivery.subprocess.run", return_value=completed):
            result = _run_janitor_triage("some note", "key123")
        self.assertEqual(result, {"status": "filed", "repo": "Khamel83/x", "issue_url": "https://x/1"})

    def test_timeout_returns_error_status(self):
        with patch("github_delivery.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[], timeout=105)):
            result = _run_janitor_triage("some note", "key123")
        self.assertEqual(result["status"], "error")

    def test_nonzero_exit_returns_error_status(self):
        completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
        with patch("github_delivery.subprocess.run", return_value=completed):
            result = _run_janitor_triage("some note", "key123")
        self.assertEqual(result["status"], "error")

    def test_invokes_janitor_runner_by_absolute_path(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout='{"status": "no_match"}', stderr="")
        with patch("github_delivery.subprocess.run", return_value=completed) as run:
            _run_janitor_triage("some note", "key123")
        command = run.call_args.args[0]
        self.assertEqual(command[0], "/Users/macmini/.local/bin/janitor-runner")
        self.assertIn("triage", command)


class ClassifyTriageOutcomeTestCase(unittest.TestCase):
    def test_filed_is_sent(self):
        self.assertEqual(_classify_triage_outcome({"status": "filed"}), "sent")

    def test_no_match_is_terminal_no_match(self):
        self.assertEqual(_classify_triage_outcome({"status": "no_match"}), "no_match")

    def test_error_is_retryable(self):
        self.assertEqual(_classify_triage_outcome({"status": "error", "reason": "x"}), "retryable")

    def test_unrecognized_shape_is_retryable(self):
        self.assertEqual(_classify_triage_outcome({"unexpected": True}), "retryable")


class ProcessPendingGithubDeliveriesTestCase(unittest.TestCase):
    def test_filed_outcome_marks_sent_and_posts_thread_reply(self):
        claimed = {
            "id": 1, "transcript_row_id": 42, "idempotency_key": "key123",
            "transcript_text": "fix the widget bug", "github_claim_token": "tok",
        }
        with (
            patch("github_delivery.claim_next_github_delivery", side_effect=[claimed, None]),
            patch(
                "github_delivery._run_janitor_triage",
                return_value={"status": "filed", "repo": "Khamel83/x", "issue_url": "https://x/1"},
            ),
            patch("github_delivery.mark_github_delivery_sent") as mark_sent,
            patch("github_delivery._reply_in_slack_thread") as reply,
        ):
            count = process_pending_github_deliveries(limit=20)
        self.assertEqual(count, 1)
        mark_sent.assert_called_once_with(
            1, "Khamel83/x", "https://x/1", claim_token="tok", claim_owner=unittest.mock.ANY,
        )
        reply.assert_called_once()
        self.assertIn("https://x/1", reply.call_args.args[-1])

    def test_no_match_outcome_marks_no_match_and_posts_thread_reply(self):
        claimed = {
            "id": 1, "transcript_row_id": 42, "idempotency_key": "key123",
            "transcript_text": "buy milk", "github_claim_token": "tok",
        }
        with (
            patch("github_delivery.claim_next_github_delivery", side_effect=[claimed, None]),
            patch("github_delivery._run_janitor_triage", return_value={"status": "no_match"}),
            patch("github_delivery.mark_github_delivery_no_match") as mark_no_match,
            patch("github_delivery._reply_in_slack_thread") as reply,
        ):
            process_pending_github_deliveries(limit=20)
        mark_no_match.assert_called_once()
        reply.assert_called_once()

    def test_error_outcome_marks_failed_and_does_not_post_thread_reply(self):
        claimed = {
            "id": 1, "transcript_row_id": 42, "idempotency_key": "key123",
            "transcript_text": "fix the widget bug", "github_claim_token": "tok",
        }
        with (
            patch("github_delivery.claim_next_github_delivery", side_effect=[claimed, None]),
            patch("github_delivery._run_janitor_triage", return_value={"status": "error", "reason": "boom"}),
            patch("github_delivery.mark_github_delivery_failed") as mark_failed,
            patch("github_delivery._reply_in_slack_thread") as reply,
        ):
            process_pending_github_deliveries(limit=20)
        mark_failed.assert_called_once()
        reply.assert_not_called()

    def test_nothing_pending_returns_zero(self):
        with patch("github_delivery.claim_next_github_delivery", return_value=None):
            count = process_pending_github_deliveries(limit=20)
        self.assertEqual(count, 0)

    def test_slack_reply_failure_does_not_propagate_and_ledger_write_stands(self):
        """A Slack post failure after a terminal ledger write must be swallowed:
        the item is already correctly marked sent, and this failure must not
        abort the rest of the drain pass (process_pending_github_deliveries
        must not raise)."""
        claimed = {
            "id": 1, "transcript_row_id": 42, "idempotency_key": "key123",
            "transcript_text": "fix the widget bug", "github_claim_token": "tok",
        }
        with (
            patch("github_delivery.claim_next_github_delivery", side_effect=[claimed, None]),
            patch(
                "github_delivery._run_janitor_triage",
                return_value={"status": "filed", "repo": "Khamel83/x", "issue_url": "https://x/1"},
            ),
            patch("github_delivery.mark_github_delivery_sent") as mark_sent,
            patch(
                "github_delivery._original_slack_thread",
                return_value=("C123", "1700000000.000100"),
            ),
            patch(
                "github_delivery._post_to_slack",
                side_effect=SlackAPIError("internal_error"),
            ) as post_to_slack,
        ):
            count = process_pending_github_deliveries(limit=20)
        # The whole pass must complete without raising, and the item still
        # counts as reaching a terminal state this pass.
        self.assertEqual(count, 1)
        # The ledger write must have happened, with the correct credentials,
        # before the (failed) reply attempt.
        mark_sent.assert_called_once_with(
            1, "Khamel83/x", "https://x/1", claim_token="tok", claim_owner=unittest.mock.ANY,
        )
        post_to_slack.assert_called_once()
