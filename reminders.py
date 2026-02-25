#!/usr/bin/env python3
"""
Apple Reminders integration via AppleScript.

Adds items to named Reminders lists on macOS using osascript.
"""
import subprocess
import logging

log = logging.getLogger(__name__)


def add_reminder(item_text: str, list_name: str, fallback_list: str = "Inbox") -> bool:
    """
    Add a reminder to the named Reminders list via AppleScript.

    Falls back to fallback_list if the named list doesn't exist in Reminders.
    Returns True on success, False on failure.
    """
    # Escape for AppleScript string literals
    safe_item = item_text.replace("\\", "\\\\").replace('"', '\\"')
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
