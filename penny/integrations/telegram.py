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


async def send_build_approval_request(
    build_id: str,
    transcript: str,
) -> dict[str, Any]:
    """Send a build approval request with inline buttons.

    Args:
        build_id: The build session ID (used for callback data)
        transcript: The voice memo transcription

    Returns:
        dict with success status and message_id
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram credentials not configured")
        return {"success": False, "error": "Telegram not configured"}

    # Truncate transcript for display
    transcript_display = transcript[:500] + "..." if len(transcript) > 500 else transcript

    message = f"""🔐 **Build Approval Required**

**Transcript:**
{transcript_display}

This voice memo was classified as a "build" request.
Before any code runs, please approve or reject.

⏰ _Auto-reject in 5 minutes if no response._"""

    # Inline keyboard with Approve/Reject buttons
    inline_keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"build_approve:{build_id}"},
                {"text": "❌ Reject", "callback_data": f"build_reject:{build_id}"},
            ]
        ]
    }

    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
                "reply_markup": inline_keyboard,
            }

            response = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json=payload,
                timeout=10,
            )

            # If Markdown fails, retry without
            if response.status_code == 400:
                logger.warning("Markdown parsing failed, retrying without formatting")
                payload.pop("parse_mode", None)
                plain_text = message.replace("**", "").replace("*", "").replace("`", "").replace("_", "")
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


async def answer_callback_query(
    callback_query_id: str,
    text: str = "",
) -> dict[str, Any]:
    """Answer a callback query (acknowledge button press).

    Args:
        callback_query_id: The callback query ID from Telegram
        text: Optional text to show as a notification

    Returns:
        dict with success status
    """
    if not TELEGRAM_BOT_TOKEN:
        return {"success": False, "error": "Telegram not configured"}

    try:
        async with httpx.AsyncClient() as client:
            payload = {"callback_query_id": callback_query_id}
            if text:
                payload["text"] = text

            response = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            return {"success": True}

    except Exception as e:
        logger.error(f"Telegram callback answer error: {e}")
        return {"success": False, "error": str(e)}


async def edit_message_text(
    message_id: int,
    text: str,
    parse_mode: str = "Markdown",
) -> dict[str, Any]:
    """Edit an existing message text.

    Args:
        message_id: The message ID to edit
        text: New text for the message
        parse_mode: Parsing mode (Markdown, HTML, or None)

    Returns:
        dict with success status
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return {"success": False, "error": "Telegram not configured"}

    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "message_id": message_id,
                "text": text,
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode

            response = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText",
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            return {"success": True}

    except Exception as e:
        logger.error(f"Telegram edit message error: {e}")
        return {"success": False, "error": str(e)}
