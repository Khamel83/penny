"""Telegram integration for Penny.

Provides message sending with support for:
- Markdown formatting
- Task result notifications
- Graceful fallback on formatting errors
"""

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Telegram message limit
MAX_MESSAGE_LENGTH = 4096


async def send_message(
    text: str,
    parse_mode: str = "Markdown",
    disable_preview: bool = True,
) -> dict[str, Any]:
    """Send a message via Telegram bot.

    Args:
        text: The message to send
        parse_mode: Parsing mode (Markdown, HTML, or None)
        disable_preview: Disable link previews

    Returns:
        dict with success status and response
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram credentials not configured")
        return {"success": False, "error": "Telegram not configured"}

    # Truncate if too long
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH - 20] + "\n\n_...truncated_"

    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "disable_web_page_preview": disable_preview,
            }

            if parse_mode:
                payload["parse_mode"] = parse_mode

            response = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json=payload,
                timeout=10,
            )

            # If Markdown parsing fails, retry without formatting
            if response.status_code == 400 and parse_mode:
                logger.warning("Markdown parsing failed, retrying without formatting")
                payload.pop("parse_mode", None)
                # Remove markdown characters
                plain_text = text.replace("**", "").replace("*", "").replace("`", "").replace("_", "")
                payload["text"] = plain_text
                response = await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json=payload,
                    timeout=10,
                )

            response.raise_for_status()
            data = response.json()

            return {
                "success": True,
                "message_id": data.get("result", {}).get("message_id"),
                "response": data,
            }

    except httpx.HTTPStatusError as e:
        logger.error(f"Telegram API error: {e.response.status_code} - {e.response.text}")
        return {
            "success": False,
            "error": f"HTTP {e.response.status_code}: {e.response.text}",
        }
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return {"success": False, "error": str(e)}


async def send_task_result(
    task_id: str,
    query: str,
    result: str,
    confidence: float,
    source: str = "probe",
    findings_count: int = 0,
) -> dict[str, Any]:
    """Send a formatted task result notification.

    Args:
        task_id: The background task ID
        query: Original query/request
        result: The result or analysis
        confidence: Confidence score (0-1)
        source: Source of the result (probe, quick, full)
        findings_count: Number of probe findings used

    Returns:
        dict with success status
    """
    # Confidence indicator
    if confidence >= 0.8:
        confidence_indicator = "High"
    elif confidence >= 0.6:
        confidence_indicator = "Medium"
    else:
        confidence_indicator = "Low"

    # Truncate query and result
    query_display = query[:200] + "..." if len(query) > 200 else query
    result_display = result[:3000] + "\n\n_...truncated_" if len(result) > 3000 else result

    message = f"""**Task Result** ({confidence_indicator} confidence)

**Query:** {query_display}

**Source:** {source}
**Findings used:** {findings_count}
**Confidence:** {confidence:.0%}

**Result:**
{result_display}

_Task ID: {task_id[:8]}..._"""

    return await send_message(message)


async def send_task_started(
    task_id: str,
    query: str,
    task_type: str,
) -> dict[str, Any]:
    """Notify that a background task has started.

    Args:
        task_id: The background task ID
        query: The query being processed
        task_type: Type of task (probe, build, etc.)

    Returns:
        dict with success status
    """
    query_display = query[:150] + "..." if len(query) > 150 else query

    message = f"""**Background Task Started**

**Type:** {task_type}
**Query:** {query_display}

I'll notify you when I have findings.

_Task ID: {task_id[:8]}..._"""

    return await send_message(message)


async def send_task_failed(
    task_id: str,
    query: str,
    error: str,
) -> dict[str, Any]:
    """Notify that a background task has failed.

    Args:
        task_id: The background task ID
        query: The query that failed
        error: Error message

    Returns:
        dict with success status
    """
    query_display = query[:150] + "..." if len(query) > 150 else query
    error_display = error[:500] + "..." if len(error) > 500 else error

    message = f"""**Task Failed**

**Query:** {query_display}

**Error:** {error_display}

_Task ID: {task_id[:8]}..._"""

    return await send_message(message)
