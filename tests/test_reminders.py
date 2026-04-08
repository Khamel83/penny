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


if __name__ == "__main__":
    unittest.main()
