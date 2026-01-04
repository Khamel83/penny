"""Route dispatcher for Penny - calls external APIs based on classification."""

import os
from typing import Any, Optional

# Import integrations (lazy import to handle missing dependencies gracefully)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Confidence threshold - below this, ask for confirmation via Telegram
CONFIDENCE_THRESHOLD = float(os.environ.get("PENNY_CONFIDENCE_THRESHOLD", "0.7"))


async def route(
    classification: str,
    text: str,
    data: dict[str, Any],
    item_id: Optional[str] = None,
    confidence: float = 1.0,
    background: bool = False,
) -> dict[str, Any]:
    """Route to appropriate service based on classification.

    Args:
        classification: The category (shopping, media, work, etc.)
        text: The original transcribed text
        data: Extracted routing data from LLM (items, title, task, etc.)
        item_id: The item ID (for confirmation requests)
        confidence: Classification confidence (0-1)
        background: If True, queue as background task instead of immediate routing

    Returns:
        dict with 'routed', 'service', 'error', 'needs_confirmation', 'queued' keys
    """
    # If background requested, queue for async processing
    if background:
        return await queue_background_task(
            classification=classification,
            text=text,
            data=data,
            item_id=item_id,
        )

    # Check if we need confirmation for low-confidence classifications
    if confidence < CONFIDENCE_THRESHOLD and classification not in ("unknown", "personal"):
        return await request_confirmation(item_id, classification, text, confidence)

    try:
        if classification == "shopping":
            return await route_shopping(text, data)
        elif classification == "media":
            return await route_media(text, data)
        elif classification == "work":
            return await route_work(text, data)
        elif classification == "smart_home":
            return await route_smart_home(text, data)
        elif classification == "reminder":
            return await route_reminder(text, data)
        elif classification == "calendar":
            return await route_calendar(text, data)
        elif classification == "notes":
            return await route_notes(text, data)
        elif classification == "build":
            return await route_build(text, data)
        elif classification == "url":
            return await route_url(text, data)
        elif classification == "personal":
            # Personal notes just stay in Penny
            return {"routed": False, "reason": "Stored in Penny only"}
        else:
            return {"routed": False, "reason": f"No route for {classification}"}
    except Exception as e:
        return {"routed": False, "error": str(e)}


async def queue_background_task(
    classification: str,
    text: str,
    data: dict[str, Any],
    item_id: Optional[str] = None,
) -> dict[str, Any]:
    """Queue a task for background processing.

    Uses the "gather signal cheap, reason expensive" pattern.
    """
    try:
        from . import database

        # Determine task type based on classification
        if classification == "build":
            task_type = "build"
            priority = 1
        else:
            task_type = "probe"
            priority = 0

        # Build input data for the orchestrator
        input_data = {
            "text": text,
            "classification": classification,
            "data": data,
            "query": text,  # Use text as the query for probing
        }

        # Add search patterns for code-related tasks
        if classification == "build":
            input_data["search_pattern"] = data.get("description", text)[:50]

        task = await database.create_background_task(
            task_type=task_type,
            input_data=input_data,
            item_id=item_id,
            priority=priority,
        )

        # Notify via Telegram
        try:
            from .integrations import telegram
            await telegram.send_task_started(
                task_id=task["id"],
                query=text[:150],
                task_type=task_type,
            )
        except Exception:
            pass

        return {
            "routed": False,
            "queued": True,
            "task_id": task["id"],
            "service": "orchestrator",
            "message": "Queued for background processing",
        }

    except Exception as e:
        # Fall back to immediate routing if queuing fails
        return {
            "routed": False,
            "queued": False,
            "error": f"Failed to queue: {e}",
        }


async def request_confirmation(
    item_id: Optional[str],
    classification: str,
    text: str,
    confidence: float
) -> dict[str, Any]:
    """Send a Telegram message requesting confirmation for low-confidence classification."""
    preview = text[:100] + "..." if len(text) > 100 else text
    confidence_pct = int(confidence * 100)

    emoji_map = {
        "shopping": "🛒",
        "media": "🎬",
        "work": "📋",
        "smart_home": "🏠",
        "reminder": "⏰",
        "calendar": "📅",
        "notes": "📝",
        "build": "🔧",
        "url": "🔗",
    }
    emoji = emoji_map.get(classification, "❓")

    message = (
        f"⚠️ <b>Low confidence ({confidence_pct}%)</b>\n\n"
        f"I think this is <b>{emoji} {classification}</b>:\n"
        f"<i>\"{preview}\"</i>\n\n"
        f"Reply with:\n"
        f"• <code>/confirm {item_id}</code> to proceed\n"
        f"• <code>/reclassify {item_id} shopping|media|work|personal</code> to change"
    )

    result = await send_telegram(message)
    if result.get("routed"):
        return {
            "routed": False,
            "needs_confirmation": True,
            "service": "telegram",
            "message": f"Awaiting confirmation (confidence: {confidence_pct}%)",
        }
    return result


async def route_shopping(text: str, data: dict[str, Any]) -> dict[str, Any]:
    """Route shopping items to Google Keep."""
    try:
        from .integrations import google_keep
        items = data.get("items", [])
        if not items:
            # If LLM didn't extract items, use the full text
            items = [text]
        result = await google_keep.add_to_shopping_list(items)
        return {"routed": True, "service": "google_keep", "result": result}
    except ImportError:
        # Fall back to Telegram
        return await send_telegram(f"🛒 SHOPPING: {', '.join(data.get('items', [text]))}")
    except Exception as e:
        # Fall back to Telegram on any error
        return await send_telegram(f"🛒 SHOPPING (Keep failed): {', '.join(data.get('items', [text]))}")


async def route_media(text: str, data: dict[str, Any]) -> dict[str, Any]:
    """Route media requests to Jellyseerr."""
    try:
        from .integrations import jellyseerr
        title = data.get("title", text)
        media_type = data.get("type", "movie")
        result = await jellyseerr.request_media(title, media_type)
        return {"routed": True, "service": "jellyseerr", "result": result}
    except ImportError:
        return await send_telegram(f"🎬 MEDIA REQUEST: {data.get('title', text)} ({data.get('type', 'movie')})")
    except Exception as e:
        return await send_telegram(f"🎬 MEDIA (Jellyseerr failed): {data.get('title', text)}")


async def route_work(text: str, data: dict[str, Any]) -> dict[str, Any]:
    """Route work tasks to TrojanHorse for processing and storage."""
    try:
        from .integrations import trojanhorse

        task = data.get("task", text)
        tags = data.get("tags", ["work", "voice-note"])

        result = await trojanhorse.add_work_note(
            content=task,
            tags=tags if isinstance(tags, list) else [tags],
        )
        if result.get("success"):
            # Also notify via Telegram
            await send_telegram(f"📋 WORK NOTE saved to TrojanHorse: {task[:100]}...")
            return {"routed": True, "service": "trojanhorse", "result": result}
        else:
            raise Exception(result.get("error", "Unknown error"))
    except ImportError:
        # Fall back to Telegram only
        task = data.get("task", text)
        return await send_telegram(f"📋 WORK TASK: {task}")
    except Exception as e:
        # Fall back to Telegram on any error
        task = data.get("task", text)
        return await send_telegram(f"📋 WORK (TrojanHorse failed): {task}")


async def route_smart_home(text: str, data: dict[str, Any]) -> dict[str, Any]:
    """Route smart home commands to Home Assistant."""
    try:
        from .integrations import home_assistant
        action = data.get("action", "")
        entity = data.get("entity", "")
        result = await home_assistant.execute(action, entity)
        return {"routed": True, "service": "home_assistant", "result": result}
    except ImportError:
        return await send_telegram(f"🏠 SMART HOME: {data.get('action', '')} {data.get('entity', text)}")
    except Exception as e:
        return await send_telegram(f"🏠 SMART HOME (HA failed): {text}")


async def route_reminder(text: str, data: dict[str, Any]) -> dict[str, Any]:
    """Route reminders to Apple Reminders."""
    try:
        from .integrations import reminders
        from .utils import parse_datetime

        task = data.get("task", text)
        due_date = data.get("due_date")
        due_time = data.get("due_time")

        # Parse natural language date/time
        parsed_date = None
        if due_date or due_time:
            parsed_date = parse_datetime(date_str=due_date, time_str=due_time)

        result = await reminders.create_reminder(
            title=task,
            due_date=parsed_date,
            notes=text if text != task else None,
        )
        if result.get("success"):
            return {"routed": True, "service": "reminders", "result": result}
        else:
            raise Exception(result.get("error", "Unknown error"))
    except ImportError as e:
        if "reminders" in str(e):
            return await send_telegram(f"⏰ REMINDER: {data.get('task', text)}")
        raise
    except Exception as e:
        return await send_telegram(f"⏰ REMINDER (Apple Reminders failed): {data.get('task', text)}")


async def route_calendar(text: str, data: dict[str, Any]) -> dict[str, Any]:
    """Route calendar events to Apple Calendar."""
    try:
        from .integrations import calendar as cal
        from .utils import parse_datetime

        title = data.get("title", text)
        date_str = data.get("date")
        time_str = data.get("time")
        location = data.get("location")
        duration = data.get("duration")  # e.g., "1 hour", "30 minutes"

        # Parse date/time
        start_date = None
        if date_str or time_str:
            # Try combined first, then separate
            combined = f"{date_str or ''} {time_str or ''}".strip()
            start_date = parse_datetime(combined=combined) if combined else None

        if not start_date:
            # Can't create event without a date - send to Telegram instead
            return await send_telegram(
                f"📅 CALENDAR: {title}\n"
                f"Date: {date_str or 'not specified'}\n"
                f"Time: {time_str or 'not specified'}\n"
                f"Location: {location or 'not specified'}"
            )

        result = await cal.create_event(
            title=title,
            start_date=start_date,
            location=location,
            notes=text if text != title else None,
        )
        if result.get("success"):
            return {"routed": True, "service": "calendar", "result": result}
        else:
            raise Exception(result.get("error", "Unknown error"))
    except ImportError as e:
        if "calendar" in str(e):
            return await send_telegram(f"📅 CALENDAR: {data.get('title', text)}")
        raise
    except Exception as e:
        return await send_telegram(f"📅 CALENDAR (failed): {data.get('title', text)}")


async def route_notes(text: str, data: dict[str, Any]) -> dict[str, Any]:
    """Route notes to Apple Notes."""
    try:
        from .integrations import notes

        title = data.get("title")
        content = data.get("content", text)

        if title:
            # Create a new note with specific title
            result = await notes.create_note(title=title, body=content)
        else:
            # Append to daily note
            result = await notes.append_to_daily_note(content=text)

        if result.get("success"):
            return {"routed": True, "service": "notes", "result": result}
        else:
            raise Exception(result.get("error", "Unknown error"))
    except ImportError:
        return await send_telegram(f"📝 NOTE: {text[:200]}...")
    except Exception as e:
        return await send_telegram(f"📝 NOTE (Apple Notes failed): {text[:200]}...")


async def route_url(text: str, data: dict[str, Any]) -> dict[str, Any]:
    """Route URLs to Atlas for ingestion."""
    try:
        from .integrations import atlas

        url = data.get("url", "")
        if not url:
            # Try to extract URL from text
            import re
            url_match = re.search(r'https?://[^\s]+', text)
            if url_match:
                url = url_match.group(0)

        if not url:
            return await send_telegram(f"🔗 URL not found in: {text[:100]}...")

        tags = data.get("tags", [])
        result = await atlas.submit_url(url, tags=tags)

        if result.get("success"):
            await send_telegram(f"🔗 URL queued for Atlas: {url}")
            return {"routed": True, "service": "atlas", "result": result}
        else:
            raise Exception(result.get("error", "Unknown error"))
    except ImportError:
        return await send_telegram(f"🔗 URL (Atlas not available): {data.get('url', text)}")
    except Exception as e:
        return await send_telegram(f"🔗 URL (Atlas failed): {data.get('url', text)[:100]}...")


async def route_build(text: str, data: dict[str, Any]) -> dict[str, Any]:
    """Route build requests to Claude Code."""
    try:
        from .integrations import claude_code

        description = data.get("description", text)
        result = await claude_code.handle_build(description, data)

        if result.get("success"):
            return {"routed": True, "service": "claude_code", "result": result}
        else:
            # Build failed - notify via Telegram
            error = result.get("error", "Unknown error")
            await send_telegram(f"🔧 BUILD FAILED: {description[:100]}...\n\nError: {error}")
            return {"routed": False, "service": "claude_code", "error": error}
    except ImportError:
        # Claude Code not available - send to Telegram
        return await send_telegram(f"🔧 BUILD REQUEST: {text[:200]}...")
    except Exception as e:
        # Any other error - send to Telegram
        return await send_telegram(f"🔧 BUILD (failed): {text[:100]}...\n\nError: {str(e)}")


async def send_telegram(message: str) -> dict[str, Any]:
    """Send a message via Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return {"routed": False, "error": "Telegram not configured"}

    try:
        from .integrations import telegram
        result = await telegram.send_message(message)
        return {"routed": True, "service": "telegram", "result": result}
    except ImportError:
        # Direct API call if integration not available
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
                timeout=10,
            )
            resp.raise_for_status()
            return {"routed": True, "service": "telegram", "result": resp.json()}
    except Exception as e:
        return {"routed": False, "error": str(e)}
