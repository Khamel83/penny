#!/usr/bin/env python3
"""Tests for Penny AppleScript bridge (reminders.py)."""
import subprocess
import unittest
from unittest.mock import patch

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

import reminders  # noqa: E402

SUCCESS = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def _script(mock_run):
    """Extract the AppleScript string from the subprocess.run call."""
    call_args = mock_run.call_args
    # subprocess.run(["osascript", "-e", script], capture_output=True, ...)
    # call_args[0] is the positional args tuple: (["osascript", "-e", script],)
    return call_args[0][0][2]


class AddNoteTests(unittest.TestCase):
    @patch("reminders.subprocess.run")
    def test_add_note_success(self, mock_run):
        mock_run.return_value = SUCCESS
        result = reminders.add_note("buy milk", folder_name="Penny", source="test")
        self.assertTrue(result)
        script = _script(mock_run)
        self.assertIn("Penny", script)
        self.assertIn("buy milk", script)
        self.assertIn("Notes", script)

    @patch("reminders.subprocess.run")
    def test_add_note_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="AppleScript error"
        )
        result = reminders.add_note("test text")
        self.assertFalse(result)

    @patch("reminders.subprocess.run")
    def test_add_note_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="osascript", timeout=15)
        result = reminders.add_note("test text")
        self.assertFalse(result)

    @patch("reminders.subprocess.run")
    def test_add_note_generic_exception(self, mock_run):
        mock_run.side_effect = OSError("permission denied")
        result = reminders.add_note("test text")
        self.assertFalse(result)

    @patch("reminders.subprocess.run")
    def test_add_note_creates_folder_if_missing(self, mock_run):
        mock_run.return_value = SUCCESS
        reminders.add_note("test")
        script = _script(mock_run)
        self.assertIn("make new folder", script)

    @patch("reminders.subprocess.run")
    def test_add_note_escapes_special_chars(self, mock_run):
        mock_run.return_value = SUCCESS
        reminders.add_note('text with "quotes"')
        script = _script(mock_run)
        # The text should be HTML-escaped (quotes in body become &quot;)
        self.assertIn("&quot;quotes&quot;", script)

    @patch("reminders.subprocess.run")
    def test_add_note_custom_folder(self, mock_run):
        mock_run.return_value = SUCCESS
        reminders.add_note("test", folder_name="CustomFolder")
        script = _script(mock_run)
        self.assertIn("CustomFolder", script)


class AddReminderTests(unittest.TestCase):
    @patch("reminders.subprocess.run")
    def test_add_reminder_success(self, mock_run):
        mock_run.return_value = SUCCESS
        result = reminders.add_reminder("buy milk", "Groceries")
        self.assertTrue(result)
        script = _script(mock_run)
        self.assertIn("Groceries", script)
        self.assertIn("buy milk", script)

    @patch("reminders.subprocess.run")
    def test_add_reminder_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="list not found"
        )
        result = reminders.add_reminder("test item", "NonExistent")
        self.assertFalse(result)

    @patch("reminders.subprocess.run")
    def test_add_reminder_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="osascript", timeout=15)
        result = reminders.add_reminder("test", "Inbox")
        self.assertFalse(result)

    @patch("reminders.subprocess.run")
    def test_add_reminder_generic_exception(self, mock_run):
        mock_run.side_effect = OSError("boom")
        result = reminders.add_reminder("test", "Inbox")
        self.assertFalse(result)

    @patch("reminders.subprocess.run")
    def test_add_reminder_falls_back_on_missing_list(self, mock_run):
        mock_run.return_value = SUCCESS
        reminders.add_reminder("test item", "NonExistent", fallback_list="Inbox")
        script = _script(mock_run)
        # Script should check for the primary list first, then fallback
        self.assertIn("NonExistent", script)
        self.assertIn("Inbox", script)
        self.assertIn("else", script.lower())

    @patch("reminders.subprocess.run")
    def test_add_reminder_escapes_quotes_and_newlines(self, mock_run):
        mock_run.return_value = SUCCESS
        reminders.add_reminder('item with "quotes"\nand newlines', "Inbox")
        script = _script(mock_run)
        # Quotes should be escaped for AppleScript
        self.assertIn('\\"quotes\\"', script)
        # Newlines in the item text should be replaced with spaces
        # (the AppleScript template itself contains \n, so check the specific line)
        self.assertNotIn("and\nnewlines", script)

    @patch("reminders.subprocess.run")
    def test_add_reminder_uses_fallback_list_by_default(self, mock_run):
        mock_run.return_value = SUCCESS
        reminders.add_reminder("test", "Inbox")
        script = _script(mock_run)
        self.assertIn("Inbox", script)


class ReceiptTransportContractTests(unittest.TestCase):
    @patch("reminders.subprocess.run")
    def test_automation_denial_is_bounded_permission_error(self, run_mock):
        sentinel = "secret transcript provider stderr"
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=f"-1743 {sentinel}"
        )
        with self.assertRaisesRegex(reminders.AppleScriptError, "permission_denied") as raised:
            reminders._run_osascript("safe script")
        self.assertNotIn(sentinel, str(raised.exception))

    @patch("reminders.subprocess.run")
    def test_arbitrary_nonzero_is_bounded_provider_error(self, run_mock):
        sentinel = "secret transcript provider stderr"
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=sentinel
        )
        with self.assertRaisesRegex(reminders.AppleScriptError, "provider_error") as raised:
            reminders._run_osascript("safe script")
        self.assertNotIn(sentinel, str(raised.exception))

    def test_missing_notes_folder_is_an_empty_marker_search(self):
        with patch.object(
            reminders,
            "_run_osascript",
            return_value="",
        ):
            # The transport must distinguish a missing folder from an
            # Automation/permission failure; callers may then create it.
            self.assertEqual(reminders.find_note_by_marker("a" * 64, "Penny"), [])

    @patch("reminders._run_osascript", return_value="id-1\n")
    def test_note_marker_search_uses_explicit_line_delimiter(self, run_mock):
        matches = reminders.find_note_by_marker("a" * 64, "Penny")
        self.assertEqual(matches, ["id-1"])
        self.assertIn("linefeed", run_mock.call_args.args[0])

    @patch("reminders._run_osascript", return_value="id-1\tInbox")
    def test_reminder_marker_is_body_only_and_readback_has_target(self, run_mock):
        receipt = reminders.create_reminder_with_marker(
            "a" * 64, "buy milk", "Groceries", "Inbox"
        )
        script = run_mock.call_args.args[0]
        self.assertEqual(receipt.provider_id, "id-1")
        self.assertIn('body:', script)
        self.assertNotIn('name:"penny-effect:', script)


if __name__ == "__main__":
    unittest.main()
