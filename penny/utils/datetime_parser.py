"""Natural language date/time parsing for Penny.

Uses dateparser library to handle expressions like:
- "tomorrow at 3pm"
- "next Tuesday"
- "in 2 hours"
- "December 25th at noon"
"""

from datetime import datetime, timedelta
from typing import Optional, Tuple

import dateparser


def parse_datetime(
    date_str: Optional[str] = None,
    time_str: Optional[str] = None,
    combined: Optional[str] = None,
) -> Optional[datetime]:
    """Parse natural language date/time into a datetime object.

    Args:
        date_str: Natural language date ("tomorrow", "next Tuesday", "December 25")
        time_str: Natural language time ("3pm", "noon", "14:30")
        combined: Combined date/time string ("tomorrow at 3pm")

    Returns:
        datetime object or None if parsing fails
    """
    # If combined string provided, parse it directly
    if combined:
        result = dateparser.parse(
            combined,
            settings={
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": datetime.now(),
            },
        )
        return result

    # Parse date and time separately
    parsed_date = None
    parsed_time = None

    if date_str:
        parsed_date = dateparser.parse(
            date_str,
            settings={
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": datetime.now(),
            },
        )

    if time_str:
        # Try parsing time - dateparser handles "3pm", "noon", "14:30", etc.
        parsed_time = dateparser.parse(
            time_str,
            settings={
                "PREFER_DATES_FROM": "future",
            },
        )

    # Combine date and time
    if parsed_date and parsed_time:
        return parsed_date.replace(
            hour=parsed_time.hour,
            minute=parsed_time.minute,
            second=0,
            microsecond=0,
        )
    elif parsed_date:
        # Default to 9:00 AM if no time specified
        return parsed_date.replace(hour=9, minute=0, second=0, microsecond=0)
    elif parsed_time:
        # If only time, assume today (or tomorrow if time has passed)
        now = datetime.now()
        result = now.replace(
            hour=parsed_time.hour,
            minute=parsed_time.minute,
            second=0,
            microsecond=0,
        )
        if result < now:
            result += timedelta(days=1)
        return result

    return None


def parse_date(date_str: str) -> Optional[datetime]:
    """Parse a natural language date string.

    Args:
        date_str: Natural language date ("tomorrow", "next week", "December 25")

    Returns:
        datetime object (at midnight) or None if parsing fails
    """
    result = dateparser.parse(
        date_str,
        settings={
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": datetime.now(),
        },
    )
    if result:
        return result.replace(hour=0, minute=0, second=0, microsecond=0)
    return None


def parse_time(time_str: str) -> Optional[Tuple[int, int]]:
    """Parse a natural language time string.

    Args:
        time_str: Natural language time ("3pm", "noon", "14:30", "in 2 hours")

    Returns:
        Tuple of (hour, minute) or None if parsing fails
    """
    result = dateparser.parse(
        time_str,
        settings={
            "PREFER_DATES_FROM": "future",
        },
    )
    if result:
        return (result.hour, result.minute)
    return None
