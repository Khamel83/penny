#!/usr/bin/env python3
"""
Apple Reminders and Notes integration via AppleScript.

Adds items to named Reminders lists, and creates notes in Apple Notes,
using osascript on macOS.
"""
import html
import subprocess
import logging
from datetime import datetime

log = logging.getLogger(__name__)

FIELD_SEPARATOR = chr(31)
RECORD_SEPARATOR = chr(30)
LIST_NOT_FOUND_MARKER = "__PENNY_LIST_NOT_FOUND__"


def _escape_apple_script_string(value: str) -> str:
    """Escape a Python string for use in an AppleScript string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _provider_id(result: subprocess.CompletedProcess, item_type: str) -> str | None:
    provider_id = (result.stdout or "").strip()
    if not provider_id:
        log.error("AppleScript adding %s returned no provider id", item_type)
        return None
    return provider_id


def add_note(
    text: str,
    folder_name: str = "Penny",
    source: str = "",
    title: str | None = None,
) -> str | None:
    """
    Create a new note in the named Apple Notes folder.

    Falls back to the default Notes account root if the folder doesn't exist.
    Returns the provider id on success, or None on failure.
    """
    safe_folder = _escape_apple_script_string(folder_name)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    note_title = timestamp if title is None else title
    safe_title = _escape_apple_script_string(note_title).replace("\n", " ").replace("\r", " ")
    # Add a blank first line so Notes shows spacing between the note title and body text.
    body_html = "<br>" + html.escape(text).replace(chr(10), "<br>").replace(chr(13), "")
    safe_body_html = _escape_apple_script_string(body_html)

    script = f'''
tell application "Notes"
    set targetFolder to missing value
    repeat with f in folders
        if name of f is "{safe_folder}" then
            set targetFolder to f
            exit repeat
        end if
    end repeat
    if targetFolder is missing value then
        set targetFolder to (make new folder with properties {{name:"{safe_folder}"}})
    end if
    set createdNote to (make new note at targetFolder with properties {{name:"{safe_title}", body:"{safe_body_html}"}})
    return id of createdNote
end tell
'''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            log.error(f"AppleScript error adding note: {result.stderr.strip()}")
            return None
        provider_id = _provider_id(result, "note")
        if provider_id is None:
            return None
        log.info(f"Added note to {folder_name}: '{text[:60]}' (id={provider_id})")
        return provider_id
    except subprocess.TimeoutExpired:
        log.error("AppleScript timed out adding note")
        return None
    except Exception as e:
        log.error(f"Failed to add note: {e}")
        return None


def add_reminder(
    item_text: str,
    list_name: str,
    fallback_list: str = "Inbox",
    notes: str = "",
    create_if_missing: bool = False,
) -> str | None:
    """
    Add a reminder to the named Reminders list via AppleScript.

    Falls back to fallback_list if the named list doesn't exist in Reminders.
    When create_if_missing is set, the named list is created instead of falling
    back — Maya's own dedicated lists are self-provisioning, mirroring the way
    add_note() creates its target folder. Legacy transcript callers leave this
    off and keep the Inbox fallback.

    Returns the provider id on success, or None on failure.
    """
    # Escape for AppleScript string literals
    safe_item = _escape_apple_script_string(item_text).replace("\n", " ").replace("\r", " ")
    safe_list = _escape_apple_script_string(list_name)
    safe_fallback = _escape_apple_script_string(fallback_list)
    safe_notes = _escape_apple_script_string(notes).replace("\n", " ").replace("\r", " ")
    properties = f'name:"{safe_item}"'
    if notes:
        properties += f', body:"{safe_notes}"'

    if create_if_missing:
        missing_branch = (
            f'set targetList to (make new list with properties {{name:"{safe_list}"}})'
        )
    else:
        missing_branch = (
            f'log "List \'{safe_list}\' not found, using \'{safe_fallback}\'"\n'
            f'        set targetList to list "{safe_fallback}"'
        )

    script = f'''
tell application "Reminders"
    if exists list "{safe_list}" then
        set targetList to list "{safe_list}"
    else
        {missing_branch}
    end if
    set createdReminder to (make new reminder at end of targetList with properties {{{properties}}})
    return id of createdReminder
end tell
'''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            log.error(
                f"AppleScript error adding '{item_text}' to '{list_name}': "
                f"{result.stderr.strip()}"
            )
            return None
        provider_id = _provider_id(result, "reminder")
        if provider_id is None:
            return None
        log.info(f"Added reminder: '{item_text}' → {list_name} (id={provider_id})")
        return provider_id
    except subprocess.TimeoutExpired:
        log.error(f"AppleScript timed out adding '{item_text}' to '{list_name}'")
        return None
    except Exception as e:
        log.error(f"Failed to add reminder '{item_text}': {e}")
        return None


def read_reminders(list_name: str) -> list[dict] | None:
    """Read reminder completion state from one named Reminders list.

    Returns None only when the requested list does not exist. AppleScript or
    output-format failures are raised so callers can distinguish them from a
    valid, empty list.
    """
    safe_list = _escape_apple_script_string(list_name)

    script = f'''
tell application "Reminders"
    if not (exists list "{safe_list}") then
        return "{LIST_NOT_FOUND_MARKER}"
    end if
    set targetList to list "{safe_list}"
    set fieldDelimiter to ASCII character 31
    set recordDelimiter to ASCII character 30
    set recordsText to ""
    repeat with R in reminders of targetList
        set completionText to ""
        try
            set completionValue to completion date of R
            if completionValue is not missing value then
                set completionText to ((completionValue as «class isot») as string)
            end if
        end try
        set completedText to "false"
        if completed of R then
            set completedText to "true"
        end if
        set notesText to ""
        try
            set notesValue to body of R
            if notesValue is not missing value then
                set notesText to notesValue as text
            end if
        end try
        set recordsText to recordsText & (id of R as text) & fieldDelimiter & (name of R as text) & fieldDelimiter & completedText & fieldDelimiter & completionText & fieldDelimiter & notesText & recordDelimiter
    end repeat
    return recordsText
end tell
'''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        log.error(f"AppleScript timed out reading reminders from '{list_name}'")
        raise
    except Exception as e:
        log.error(f"Failed to read reminders from '{list_name}': {e}")
        raise

    if result.returncode != 0:
        log.error(
            f"AppleScript error reading reminders from '{list_name}': "
            f"{result.stderr.strip()}"
        )
        raise RuntimeError("AppleScript failed reading reminders")

    output = (result.stdout or "").rstrip("\r\n")
    if output == LIST_NOT_FOUND_MARKER:
        return None
    if not output:
        return []

    reminders = []
    for record in output.split(RECORD_SEPARATOR):
        if not record:
            continue
        fields = record.split(FIELD_SEPARATOR, 4)
        if len(fields) != 5:
            log.error("Malformed AppleScript reminder record")
            raise RuntimeError("Malformed AppleScript reminder output")
        provider_id, title, completed, completion_date, notes = fields
        completion_date_value = completion_date
        if completion_date.strip().lower() in {"", "missing value"}:
            completion_date_value = None
        reminders.append(
            {
                "provider_id": provider_id,
                "title": title,
                "completed": completed.strip().lower() == "true",
                "completion_date": completion_date_value,
                "notes": notes,
            }
        )
    return reminders
