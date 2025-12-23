"""Apple Calendar integration for Penny.

Uses AppleScript via SSH to create calendar events on the Mac mini.
"""

import os
import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional

# SSH connection to Mac mini
MAC_MINI_HOST = os.environ.get("MAC_MINI_HOST", "macmini")
MAC_MINI_USER = os.environ.get("MAC_MINI_USER", "macmini")

# Default calendar
DEFAULT_CALENDAR = os.environ.get("PENNY_CALENDAR", "Calendar")


async def create_event(
    title: str,
    start_date: datetime,
    end_date: Optional[datetime] = None,
    location: Optional[str] = None,
    notes: Optional[str] = None,
    calendar_name: Optional[str] = None,
) -> dict[str, Any]:
    """Create a calendar event in Apple Calendar.

    Args:
        title: The event title
        start_date: Event start time
        end_date: Event end time (default: 1 hour after start)
        location: Optional location
        notes: Optional notes/description
        calendar_name: Which calendar to add to (default: Calendar)

    Returns:
        dict with success status and details
    """
    calendar_name = calendar_name or DEFAULT_CALENDAR

    # Default to 1 hour duration
    if not end_date:
        end_date = start_date + timedelta(hours=1)

    # Format dates for AppleScript
    start_str = start_date.strftime("%B %d, %Y at %I:%M %p")
    end_str = end_date.strftime("%B %d, %Y at %I:%M %p")

    # Build AppleScript
    script_parts = [
        'tell application "Calendar"',
        f'    set targetCalendar to calendar "{calendar_name}"',
        f'    set newEvent to make new event at end of events of targetCalendar with properties {{',
        f'        summary:"{_escape(title)}",',
        f'        start date:date "{start_str}",',
        f'        end date:date "{end_str}"',
    ]

    if location:
        script_parts[-1] += f',\n        location:"{_escape(location)}"'

    if notes:
        script_parts[-1] += f',\n        description:"{_escape(notes)}"'

    script_parts.append("    }")
    script_parts.append("    return summary of newEvent")
    script_parts.append("end tell")

    applescript = "\n".join(script_parts)

    try:
        result = await _run_applescript(applescript)
        return {
            "success": True,
            "event": title,
            "calendar": calendar_name,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "result": result,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "event": title,
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
