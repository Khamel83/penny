"""Route dispatcher for Penny - calls external APIs based on classification."""

import os
from typing import Any

# Import integrations (lazy import to handle missing dependencies gracefully)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


async def route(classification: str, text: str, data: dict[str, Any]) -> dict[str, Any]:
    """Route to appropriate service based on classification.

    Args:
        classification: The category (shopping, media, work, etc.)
        text: The original transcribed text
        data: Extracted routing data from LLM (items, title, task, etc.)

    Returns:
        dict with 'routed', 'service', 'error' keys
    """
    try:
        if classification == "shopping":
            return await route_shopping(text, data)
        elif classification == "media":
            return await route_media(text, data)
        elif classification == "work":
            return await route_work(text, data)
        elif classification == "smart_home":
            return await route_smart_home(text, data)
        elif classification == "personal":
            # Personal notes just stay in Penny
            return {"routed": False, "reason": "Stored in Penny only"}
        else:
            return {"routed": False, "reason": f"No route for {classification}"}
    except Exception as e:
        return {"routed": False, "error": str(e)}


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
    """Route work tasks to Telegram."""
    task = data.get("task", text)
    due = data.get("due", "")
    if due:
        message = f"📋 WORK TASK: {task}\n⏰ Due: {due}"
    else:
        message = f"📋 WORK TASK: {task}"
    return await send_telegram(message)


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
