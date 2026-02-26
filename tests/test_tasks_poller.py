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

os.environ["HOME"] = "/tmp/penny_test_home"
os.environ["OPENROUTER_API_KEY"] = "test-key"
os.environ["TELEGRAM_BOT_TOKEN"] = "test-bot"
os.environ["TELEGRAM_CHAT_ID"] = "12345"
os.environ["GOOGLE_CREDENTIALS_FILE"] = "/tmp/penny_test_home/.penny/google_credentials.json"
os.environ["GOOGLE_TOKEN_FILE"] = "/tmp/penny_test_home/.penny/google_token.json"
logging.disable(logging.CRITICAL)

import tasks_poller  # noqa: E402


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

    def test_poll_once_does_not_mark_processed_on_routing_failure(self) -> None:
        service = _Service([{"id": "t1", "title": "buy milk"}])

        with patch.object(tasks_poller, "is_processed", return_value=False), patch.object(
            tasks_poller, "classify_and_route", side_effect=RuntimeError("route failed")
        ), patch.object(tasks_poller, "mark_processed") as mark_processed_mock:
            count = tasks_poller.poll_once(service, "list-1")

        self.assertEqual(count, 0)
        mark_processed_mock.assert_not_called()
        self.assertEqual(service.tasks().updated, [])

    def test_poll_once_marks_and_completes_on_success(self) -> None:
        service = _Service([{"id": "t2", "title": "call dentist"}])

        with patch.object(tasks_poller, "is_processed", return_value=False), patch.object(
            tasks_poller, "classify_and_route", return_value={"items": [{"item": "call dentist", "category": "health"}]}
        ), patch.object(tasks_poller, "mark_processed") as mark_processed_mock:
            count = tasks_poller.poll_once(service, "list-1")

        self.assertEqual(count, 1)
        mark_processed_mock.assert_called_once_with("t2", tasks_poller.SYNCED_TASKS_FILE)
        self.assertEqual(len(service.tasks().updated), 1)
        self.assertEqual(service.tasks().updated[0]["task"], "t2")


if __name__ == "__main__":
    unittest.main()
