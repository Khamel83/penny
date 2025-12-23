"""Apple Notes integration for Penny.

Uses AppleScript via SSH to create/append notes on the Mac mini.
"""

import os
import asyncio
from datetime import datetime
from typing import Any, Optional

# SSH connection to Mac mini
MAC_MINI_HOST = os.environ.get("MAC_MINI_HOST", "macmini")
MAC_MINI_USER = os.environ.get("MAC_MINI_USER", "macmini")

# Default notes folder
NOTES_FOLDER = os.environ.get("PENNY_NOTES_FOLDER", "Penny")


async def create_note(
    title: str,
    body: str,
    folder_name: Optional[str] = None,
) -> dict[str, Any]:
    """Create a new note in Apple Notes.

    Args:
        title: The note title
        body: The note content
        folder_name: Which folder to add to (default: Penny)

    Returns:
        dict with success status and details
    """
    folder_name = folder_name or NOTES_FOLDER

    # Build AppleScript
    applescript = f'''
tell application "Notes"
    set targetFolder to folder "{folder_name}"
    set newNote to make new note at targetFolder with properties {{name:"{_escape(title)}", body:"{_escape(body)}"}}
    return name of newNote
end tell
'''

    try:
        result = await _run_applescript(applescript)
        return {
            "success": True,
            "note": title,
            "folder": folder_name,
            "result": result,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "note": title,
        }


async def append_to_daily_note(
    content: str,
    folder_name: Optional[str] = None,
) -> dict[str, Any]:
    """Append content to today's daily note.

    Creates the note if it doesn't exist.

    Args:
        content: The content to append
        folder_name: Which folder to use (default: Penny)

    Returns:
        dict with success status and details
    """
    folder_name = folder_name or NOTES_FOLDER
    today = datetime.now().strftime("%Y-%m-%d")
    note_title = f"Daily Note - {today}"
    timestamp = datetime.now().strftime("%H:%M")

    # Build AppleScript that finds or creates the daily note and appends
    applescript = f'''
tell application "Notes"
    set targetFolder to folder "{folder_name}"
    set noteTitle to "{note_title}"
    set appendContent to "\\n\\n[{timestamp}] {_escape(content)}"

    -- Try to find existing note
    set existingNote to missing value
    try
        set existingNote to first note of targetFolder whose name is noteTitle
    end try

    if existingNote is missing value then
        -- Create new daily note
        set newNote to make new note at targetFolder with properties {{name:noteTitle, body:"# " & noteTitle & appendContent}}
        return "Created: " & name of newNote
    else
        -- Append to existing note
        set body of existingNote to (body of existingNote) & appendContent
        return "Appended to: " & name of existingNote
    end if
end tell
'''

    try:
        result = await _run_applescript(applescript)
        return {
            "success": True,
            "note": note_title,
            "folder": folder_name,
            "action": "appended" if "Appended" in result else "created",
            "result": result,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "note": note_title,
        }


async def _run_applescript(script: str) -> str:
    """Run AppleScript on the Mac mini via SSH."""
    # Escape the script for shell
    escaped_script = script.replace("'", "'\"'\"'")
    cmd = f"osascript -e '{escaped_script}'"

    # Run via SSH
    ssh_cmd = ["ssh", f"{MAC_MINI_USER}@{MAC_MINI_HOST}", cmd]

    proc = await asyncio.create_subprocess_exec(
        *ssh_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"AppleScript failed: {stderr.decode()}")

    return stdout.decode().strip()


def _escape(text: str) -> str:
    """Escape text for AppleScript strings."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
