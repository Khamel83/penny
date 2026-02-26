#!/usr/bin/env python3
"""
Apple Reminders and Notes integration via AppleScript.

Adds items to named Reminders lists, and creates notes in Apple Notes,
using osascript on macOS.
"""
import subprocess
import logging
from datetime import datetime

log = logging.getLogger(__name__)


def add_note(text: str, folder_name: str = "Penny", source: str = "") -> bool:
    """
    Create a new note in the named Apple Notes folder.

    Falls back to the default Notes account root if the folder doesn't exist.
    Returns True on success, False on failure.
    """
    safe_text = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")
    safe_folder = folder_name.replace("\\", "\\\\").replace('"', '\\"')
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = f"Penny — {timestamp}"
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')

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
    make new note at targetFolder with properties {{name:"{safe_title}", body:"<b>{safe_title}</b><br><br>{safe_text}"}}
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
            return False
        log.info(f"Added note to {folder_name}: '{text[:60]}'")
        return True
    except subprocess.TimeoutExpired:
        log.error("AppleScript timed out adding note")
        return False
    except Exception as e:
        log.error(f"Failed to add note: {e}")
        return False


def add_reminder(item_text: str, list_name: str, fallback_list: str = "Inbox") -> bool:
    """
    Add a reminder to the named Reminders list via AppleScript.

    Falls back to fallback_list if the named list doesn't exist in Reminders.
    Returns True on success, False on failure.
    """
    # Escape for AppleScript string literals
    safe_item = item_text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")
    safe_list = list_name.replace("\\", "\\\\").replace('"', '\\"')
    safe_fallback = fallback_list.replace("\\", "\\\\").replace('"', '\\"')

    script = f'''
tell application "Reminders"
    if exists list "{safe_list}" then
        set targetList to list "{safe_list}"
    else
        log "List '{safe_list}' not found, using '{safe_fallback}'"
        set targetList to list "{safe_fallback}"
    end if
    make new reminder at end of targetList with properties {{name:"{safe_item}"}}
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
            return False
        log.info(f"Added reminder: '{item_text}' → {list_name}")
        return True
    except subprocess.TimeoutExpired:
        log.error(f"AppleScript timed out adding '{item_text}' to '{list_name}'")
        return False
    except Exception as e:
        log.error(f"Failed to add reminder '{item_text}': {e}")
        return False
