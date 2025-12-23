"""Apple Reminders integration for Penny.

Uses AppleScript via SSH to create reminders on the Mac mini.
"""

import os
import asyncio
from datetime import datetime
from typing import Any, Optional

# SSH connection to Mac mini
MAC_MINI_HOST = os.environ.get("MAC_MINI_HOST", "macmini")
MAC_MINI_USER = os.environ.get("MAC_MINI_USER", "macmini")

# Default reminders list
REMINDERS_LIST = os.environ.get("PENNY_REMINDERS_LIST", "Reminders")


async def create_reminder(
    title: str,
    due_date: Optional[datetime] = None,
    notes: Optional[str] = None,
    list_name: Optional[str] = None,
) -> dict[str, Any]:
    """Create a reminder in Apple Reminders.

    Args:
        title: The reminder title
        due_date: Optional due date
        notes: Optional notes/body
        list_name: Which list to add to (default: Reminders)

    Returns:
        dict with success status and details
    """
    list_name = list_name or REMINDERS_LIST

    # Build AppleScript
    script_parts = [
        'tell application "Reminders"',
        f'    set targetList to list "{list_name}"',
        f'    set newReminder to make new reminder at targetList with properties {{name:"{_escape(title)}"',
    ]

    if notes:
        script_parts[-1] += f', body:"{_escape(notes)}"'

    if due_date:
        # Format date for AppleScript
        date_str = due_date.strftime("%B %d, %Y at %I:%M %p")
        script_parts[-1] += f', due date:date "{date_str}"'

    script_parts[-1] += "}"
    script_parts.append("    return name of newReminder")
    script_parts.append("end tell")

    applescript = "\n".join(script_parts)

    try:
        result = await _run_applescript(applescript)
        return {
            "success": True,
            "reminder": title,
            "list": list_name,
            "due_date": due_date.isoformat() if due_date else None,
            "result": result,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "reminder": title,
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
    return text.replace("\\", "\\\\").replace('"', '\\"')
