"""Google Keep integration for Penny - shopping lists.

Uses the unofficial gkeepapi library. Requires initial authentication
with Google credentials, after which a master token is stored.

To authenticate initially:
1. Run: python -c "import gkeepapi; k=gkeepapi.Keep(); k.login('email', 'password'); print(k.getMasterToken())"
2. Store the token in GOOGLE_KEEP_TOKEN environment variable
"""

import os
from typing import Any

GOOGLE_KEEP_EMAIL = os.environ.get("GOOGLE_KEEP_EMAIL", "")
GOOGLE_KEEP_TOKEN = os.environ.get("GOOGLE_KEEP_TOKEN", "")
SHOPPING_LIST_NAME = os.environ.get("GOOGLE_KEEP_SHOPPING_LIST", "Shopping")


async def add_to_shopping_list(items: list[str]) -> dict[str, Any]:
    """Add items to the Google Keep shopping list.

    Args:
        items: List of items to add to the shopping list

    Returns:
        Result of the operation
    """
    if not GOOGLE_KEEP_EMAIL or not GOOGLE_KEEP_TOKEN:
        raise ValueError("GOOGLE_KEEP_EMAIL and GOOGLE_KEEP_TOKEN must be set")

    try:
        import gkeepapi
    except ImportError:
        raise ImportError("gkeepapi not installed. Run: pip install gkeepapi")

    # gkeepapi is synchronous, so we run it in the default executor
    import asyncio

    def _add_items():
        keep = gkeepapi.Keep()
        keep.resume(GOOGLE_KEEP_EMAIL, GOOGLE_KEEP_TOKEN)
        keep.sync()

        # Find or create the shopping list
        shopping_list = None
        for note in keep.all():
            if isinstance(note, gkeepapi.node.List) and note.title == SHOPPING_LIST_NAME:
                shopping_list = note
                break

        if not shopping_list:
            # Create a new shopping list
            shopping_list = keep.createList(SHOPPING_LIST_NAME)

        # Add items (check for duplicates)
        existing_items = {item.text.lower() for item in shopping_list.items if not item.checked}
        added = []
        skipped = []

        for item in items:
            if item.lower() in existing_items:
                skipped.append(item)
            else:
                shopping_list.add(item, checked=False)
                added.append(item)
                existing_items.add(item.lower())

        keep.sync()

        return {
            "success": True,
            "added": added,
            "skipped": skipped,
            "list_name": SHOPPING_LIST_NAME,
        }

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _add_items)
    return result


async def get_shopping_list() -> dict[str, Any]:
    """Get all unchecked items from the shopping list.

    Returns:
        Dict with items list
    """
    if not GOOGLE_KEEP_EMAIL or not GOOGLE_KEEP_TOKEN:
        raise ValueError("GOOGLE_KEEP_EMAIL and GOOGLE_KEEP_TOKEN must be set")

    try:
        import gkeepapi
    except ImportError:
        raise ImportError("gkeepapi not installed")

    import asyncio

    def _get_items():
        keep = gkeepapi.Keep()
        keep.resume(GOOGLE_KEEP_EMAIL, GOOGLE_KEEP_TOKEN)
        keep.sync()

        for note in keep.all():
            if isinstance(note, gkeepapi.node.List) and note.title == SHOPPING_LIST_NAME:
                items = [item.text for item in note.items if not item.checked]
                return {"success": True, "items": items, "list_name": SHOPPING_LIST_NAME}

        return {"success": False, "error": f"Shopping list '{SHOPPING_LIST_NAME}' not found"}

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _get_items)
    return result
