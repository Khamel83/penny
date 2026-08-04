#!/usr/bin/env python3
"""Tests for Penny AppleScript bridge (reminders.py)."""
import subprocess
import unittest
from unittest.mock import patch

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

import reminders  # noqa: E402

REMINDER_ID = "x-apple-reminder://5A5D350F-05AD-42E6-886A-DB3FFA0BFEAE"
NOTE_ID = "x-coredata://12345678-1234-1234-1234-123456789abc/ICNote/p823"
SUCCESS = subprocess.CompletedProcess(args=[], returncode=0, stdout=REMINDER_ID + "\n", stderr="")


def _script(mock_run):
    """Extract the AppleScript string from the subprocess.run call."""
    call_args = mock_run.call_args
    # subprocess.run(["osascript", "-e", script], capture_output=True, ...)
    # call_args[0] is the positional args tuple: (["osascript", "-e", script],)
    return call_args[0][0][2]


class AddNoteTests(unittest.TestCase):
    @patch("reminders.subprocess.run")
    def test_add_note_success(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=NOTE_ID + "\n", stderr=""
        )
        result = reminders.add_note("buy milk", folder_name="Penny", source="test")
        self.assertEqual(result, NOTE_ID)
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
        self.assertIsNone(result)

    @patch("reminders.subprocess.run")
    def test_add_note_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="osascript", timeout=15)
        result = reminders.add_note("test text")
        self.assertIsNone(result)

    @patch("reminders.subprocess.run")
    def test_add_note_generic_exception(self, mock_run):
        mock_run.side_effect = OSError("permission denied")
        result = reminders.add_note("test text")
        self.assertIsNone(result)

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
        self.assertEqual(result, REMINDER_ID)
        script = _script(mock_run)
        self.assertIn("Groceries", script)
        self.assertIn("buy milk", script)

    @patch("reminders.subprocess.run")
    def test_add_reminder_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="list not found"
        )
        result = reminders.add_reminder("test item", "NonExistent")
        self.assertIsNone(result)

    @patch("reminders.subprocess.run")
    def test_add_reminder_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="osascript", timeout=15)
        result = reminders.add_reminder("test", "Inbox")
        self.assertIsNone(result)

    @patch("reminders.subprocess.run")
    def test_add_reminder_generic_exception(self, mock_run):
        mock_run.side_effect = OSError("boom")
        result = reminders.add_reminder("test", "Inbox")
        self.assertIsNone(result)

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
        reminders.add_reminder('item with "quotes" and \\slash\nand newlines', "Inbox")
        script = _script(mock_run)
        # Quotes should be escaped for AppleScript
        self.assertIn('\\"quotes\\"', script)
        self.assertIn("and \\\\slash", script)
        # Newlines in the item text should be replaced with spaces
        # (the AppleScript template itself contains \n, so check the specific line)
        self.assertNotIn("and\nnewlines", script)

    @patch("reminders.subprocess.run")
    def test_add_reminder_uses_fallback_list_by_default(self, mock_run):
        mock_run.return_value = SUCCESS
        reminders.add_reminder("test", "Inbox")
        script = _script(mock_run)
        self.assertIn("Inbox", script)

    @patch("reminders.subprocess.run")
    def test_add_reminder_creates_list_when_requested(self, mock_run):
        """Maya's dedicated lists are self-provisioning, like add_note's folder."""
        mock_run.return_value = SUCCESS
        reminders.add_reminder("test", "Maya — Mine", create_if_missing=True)
        script = _script(mock_run)
        self.assertIn('make new list with properties {name:"Maya — Mine"}', script)
        # It must NOT silently divert into the fallback list.
        self.assertNotIn("Inbox", script)

    @patch("reminders.subprocess.run")
    def test_add_reminder_legacy_path_never_creates_a_list(self, mock_run):
        """Existing transcript callers must keep the Inbox fallback, not create lists."""
        mock_run.return_value = SUCCESS
        reminders.add_reminder("test", "NonExistent")
        script = _script(mock_run)
        self.assertNotIn("make new list", script)
        self.assertIn("Inbox", script)

    @patch("reminders.subprocess.run")
    def test_read_reminders_coerces_completion_date_to_a_string(self, mock_run):
        """A bare `as «class isot»` yields «data isot…», which cannot concatenate.

        Verified live: the coercion must be wrapped in `as string` or the whole
        read fails with AppleScript error -1700.
        """
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        reminders.read_reminders("Maya — Mine")
        script = _script(mock_run)
        self.assertIn('as «class isot») as string', script)

    @patch("reminders.subprocess.run")
    def test_read_reminders_guards_a_missing_body(self, mock_run):
        """An empty reminder body must not surface as the literal 'missing value'."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        reminders.read_reminders("Maya — Mine")
        script = _script(mock_run)
        self.assertIn("if notesValue is not missing value then", script)


class ReadRemindersTests(unittest.TestCase):
    @patch("reminders.subprocess.run")
    def test_read_reminders_parses_multiple_records_and_body_newline(self, mock_run):
        field = "\x1f"
        record = "\x1e"
        stdout = (
            REMINDER_ID
            + field
            + "Review URL"
            + field
            + "false"
            + field
            + "missing value"
            + field
            + "https://example.test/a|b\nsecond line"
            + record
            + "x-apple-reminder://done"
            + field
            + "Done"
            + field
            + "true"
            + field
            + "2026-08-04T12:34:56Z"
            + field
            + "finished"
            + record
            + "\n"
        )
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=stdout, stderr=""
        )

        result = reminders.read_reminders("Maya — Mine")

        self.assertEqual(
            result,
            [
                {
                    "provider_id": REMINDER_ID,
                    "title": "Review URL",
                    "completed": False,
                    "completion_date": None,
                    "notes": "https://example.test/a|b\nsecond line",
                },
                {
                    "provider_id": "x-apple-reminder://done",
                    "title": "Done",
                    "completed": True,
                    "completion_date": "2026-08-04T12:34:56Z",
                    "notes": "finished",
                },
            ],
        )
        script = _script(mock_run)
        self.assertIn("Maya — Mine", script)
        self.assertIn("ASCII character 31", script)
        self.assertIn("ASCII character 30", script)

    @patch("reminders.subprocess.run")
    def test_read_reminders_returns_none_for_nonexistent_list(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="__PENNY_LIST_NOT_FOUND__\n", stderr=""
        )

        self.assertIsNone(reminders.read_reminders("Missing"))

    @patch("reminders.subprocess.run")
    def test_read_reminders_returns_empty_list_for_empty_existing_list(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="\n", stderr=""
        )

        self.assertEqual(reminders.read_reminders("Empty"), [])


if __name__ == "__main__":
    unittest.main()
