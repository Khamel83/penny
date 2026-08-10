from __future__ import annotations

import importlib
import logging
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["HOME"] = "/tmp/penny_test_home"
os.environ["OPENROUTER_API_KEY"] = "test-key"
os.environ["TELEGRAM_BOT_TOKEN"] = "test-bot"
os.environ["TELEGRAM_CHAT_ID"] = "12345"
os.environ["GOOGLE_CREDENTIALS_FILE"] = "/tmp/penny_test_home/.penny/google_credentials.json"
os.environ["GOOGLE_TOKEN_FILE"] = "/tmp/penny_test_home/.penny/google_token.json"
logging.disable(logging.CRITICAL)

import tasks_poller  # noqa: E402
from transcript_log import InsertOutcome, TranscriptInsertResult  # noqa: E402


def _inserted(row_id: int) -> TranscriptInsertResult:
    return TranscriptInsertResult(InsertOutcome.INSERTED, row_id=row_id)


class _Exec:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _TasksAPI:
    def __init__(self, items):
        self._items = items
        self.updated = []

    def list(self, **kwargs):
        return _Exec({"items": list(self._items)})

    def update(self, **kwargs):
        self.updated.append(kwargs)
        return _Exec({})


class _Service:
    def __init__(self, items):
        self._tasks_api = _TasksAPI(items)

    def tasks(self):
        return self._tasks_api


class TasksPollerTests(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(tasks_poller)

    def test_poll_once_does_not_complete_on_routing_failure(self) -> None:
        service = _Service([{"id": "t1", "title": "buy milk"}])

        with (
            patch.object(
                tasks_poller, "insert_transcript_result", return_value=_inserted(1)
            ),
            patch.object(
                tasks_poller,
                "classify_and_route",
                side_effect=RuntimeError("route failed"),
            ),
        ):
            count = tasks_poller.poll_once(service, "list-1")

        self.assertEqual(count, 0)
        self.assertEqual(service.tasks().updated, [])

    def test_google_task_is_not_completed_when_persistence_fails(self) -> None:
        service = _Service([{"id": "persist-failed", "title": "buy milk"}])
        failed = TranscriptInsertResult(
            InsertOutcome.FAILED, error_code="database_unavailable"
        )

        with (
            patch.object(
                tasks_poller,
                "insert_transcript_result",
                return_value=failed,
            ),
            patch.object(tasks_poller, "_mark_task_complete") as complete,
        ):
            count = tasks_poller.poll_once(service, "list-1")

        self.assertEqual(count, 0)
        complete.assert_not_called()

    def test_poll_once_routes_and_completes_on_success(self) -> None:
        service = _Service([{"id": "t2", "title": "call dentist"}])

        with (
            patch.object(
                tasks_poller, "insert_transcript_result", return_value=_inserted(1)
            ),
            patch.object(
                tasks_poller,
                "get_transcript_by_hash",
                return_value={"id": 1, "status": "routed"},
            ),
            patch.object(
                tasks_poller,
                "classify_and_route",
                return_value={"items": [{"item": "call dentist", "category": "health"}]},
            ),
        ):
            count = tasks_poller.poll_once(service, "list-1")

        self.assertEqual(count, 1)
        self.assertEqual(len(service.tasks().updated), 1)
        self.assertEqual(service.tasks().updated[0]["task"], "t2")

    def test_new_google_task_declares_archive_not_applicable(self) -> None:
        service = _Service([{"id": "t-archive", "title": "call dentist"}])
        with (
            patch.object(
                tasks_poller, "insert_transcript_result", return_value=_inserted(1)
            ) as insert,
            patch.object(
                tasks_poller,
                "get_transcript_by_hash",
                return_value={"id": 1, "status": "routed"},
            ),
            patch.object(tasks_poller, "classify_and_route", return_value={"items": []}),
        ):
            self.assertEqual(tasks_poller.poll_once(service, "list-1"), 1)
        self.assertEqual(
            insert.call_args.kwargs["archive_unavailable_reason"], "no_raw_audio"
        )

    def test_poll_once_disables_slack_enqueue_for_google_tasks(self) -> None:
        service = _Service([{"id": "t4", "title": "schedule oil change"}])

        with (
            patch.object(
                tasks_poller, "insert_transcript_result", return_value=_inserted(1)
            ) as insert_mock,
            patch.object(
                tasks_poller,
                "get_transcript_by_hash",
                return_value={"id": 1, "status": "routed"},
            ),
            patch.object(
                tasks_poller,
                "classify_and_route",
                return_value={"items": [{"item": "schedule oil change"}]},
            ),
        ):
            count = tasks_poller.poll_once(service, "list-1")

        self.assertEqual(count, 1)
        self.assertFalse(insert_mock.call_args.kwargs["enqueue_slack"])

    def test_poll_once_completes_only_a_durably_routed_duplicate(self) -> None:
        service = _Service([{"id": "t3", "title": "already done"}])

        with (
            patch.object(
                tasks_poller,
                "insert_transcript_result",
                return_value=TranscriptInsertResult(
                    InsertOutcome.DUPLICATE, row_id=3, existing_status="routed"
                ),
            ),
            patch.object(
                tasks_poller,
                "get_transcript_by_hash",
                return_value={"id": 3, "status": "routed", "transcript": "already done", "source": "Google Tasks"},
            ),
            patch.object(tasks_poller, "record_archive_unavailable"),
        ):
            count = tasks_poller.poll_once(service, "list-1")

        self.assertEqual(count, 1)
        self.assertEqual(len(service.tasks().updated), 1)

    def test_pending_duplicate_is_routed_before_google_task_is_completed(self) -> None:
        service = _Service([{"id": "t5", "title": "retry me"}])
        canonical = {
            "id": 5,
            "status": "pending",
            "transcript": "retry me",
            "source": "Google Tasks",
        }
        routed = {**canonical, "status": "routed"}

        with (
            patch.object(
                tasks_poller,
                "insert_transcript_result",
                return_value=TranscriptInsertResult(
                    InsertOutcome.DUPLICATE, row_id=5, existing_status="pending"
                ),
            ),
            patch.object(
                tasks_poller, "get_transcript_by_hash", side_effect=[canonical, routed]
            ),
            patch.object(tasks_poller, "classify_and_route") as route,
            patch.object(tasks_poller, "record_archive_unavailable") as archive_marker,
        ):
            count = tasks_poller.poll_once(service, "list-1")

        self.assertEqual(count, 1)
        route.assert_called_once_with(
            "retry me", source="Google Tasks", row_id=5, allow_maya=False
        )
        archive_marker.assert_called_once_with(
            5,
            availability_status="not_applicable",
            reason_code="no_raw_audio",
        )

    def test_task_body_and_provider_error_never_appear_in_logs(self) -> None:
        task_body = "TASK_BODY_PRIVACY_SENTINEL"
        provider_error = "GOOGLE_PROVIDER_BODY_SENTINEL"
        service = _Service([{"id": "task-privacy", "title": task_body}])
        with (
            patch.object(
                tasks_poller, "insert_transcript_result", return_value=_inserted(1)
            ),
            patch.object(
                tasks_poller,
                "classify_and_route",
                side_effect=RuntimeError(provider_error),
            ),
            patch.object(tasks_poller.log, "error") as error_log,
            patch.object(tasks_poller.log, "info") as info_log,
            patch.object(tasks_poller.log, "warning") as warning_log,
        ):
            self.assertEqual(tasks_poller.poll_once(service, "list-1"), 0)

        calls = repr(error_log.mock_calls + info_log.mock_calls + warning_log.mock_calls)
        self.assertNotIn(task_body, calls)
        self.assertNotIn(provider_error, calls)

    def test_task_routing_is_explicitly_local_first(self) -> None:
        service = _Service([{"id": "task-local", "title": "call dentist"}])
        with (
            patch.object(
                tasks_poller, "insert_transcript_result", return_value=_inserted(1)
            ),
            patch.object(
                tasks_poller,
                "get_transcript_by_hash",
                return_value={"id": 1, "status": "routed"},
            ),
            patch.object(
                tasks_poller,
                "classify_and_route",
                return_value={"items": [{"item": "call dentist"}]},
            ) as route,
        ):
            self.assertEqual(tasks_poller.poll_once(service, "list-1"), 1)
        self.assertEqual(route.call_args.kwargs["allow_maya"], False)

    def test_duplicate_archive_marker_failure_stops_routing_and_completion(self) -> None:
        service = _Service([{"id": "task-archive-fail", "title": "call dentist"}])
        canonical = {
            "id": 1,
            "status": "pending",
            "transcript": "call dentist",
            "source": "Google Tasks",
        }
        with (
            patch.object(
                tasks_poller,
                "insert_transcript_result",
                return_value=TranscriptInsertResult(
                    InsertOutcome.DUPLICATE, row_id=1, existing_status="pending"
                ),
            ),
            patch.object(tasks_poller, "get_transcript_by_hash", return_value=canonical),
            patch.object(
                tasks_poller,
                "record_archive_unavailable",
                side_effect=RuntimeError("ARCHIVE_MARKER_SENTINEL"),
            ),
            patch.object(tasks_poller, "classify_and_route") as route,
            patch.object(tasks_poller, "_mark_task_complete") as complete,
        ):
            self.assertEqual(tasks_poller.poll_once(service, "list-1"), 0)
        route.assert_not_called()
        complete.assert_not_called()

    def test_task_completion_logs_only_id(self) -> None:
        service = _Service([])
        task_body = "TASK_COMPLETION_BODY_SENTINEL"
        with patch.object(tasks_poller.log, "info") as info_log:
            self.assertTrue(
                tasks_poller._mark_task_complete(
                    service,
                    "list-1",
                    {"id": "task-id", "title": task_body},
                    task_body,
                )
            )
        self.assertNotIn(task_body, repr(info_log.mock_calls))
        self.assertIn("task-id", repr(info_log.mock_calls))
        self.assertEqual(len(service.tasks().updated), 1)


if __name__ == "__main__":
    unittest.main()
