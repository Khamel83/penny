"""TrojanHorse integration for Penny - work notes.

Writes notes to TrojanHorse's inbox folder for AI-powered processing,
categorization, and searchable storage.
"""

import os
import httpx
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# TrojanHorse configuration
TROJANHORSE_INBOX = os.environ.get(
    "TROJANHORSE_INBOX",
    "/home/khamel83/github/trojanhorse/vault/Inbox"
)
TROJANHORSE_API_URL = os.environ.get(
    "TROJANHORSE_API_URL",
    "http://localhost:8765"
)


async def add_work_note(
    content: str,
    title: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Add a work note to TrojanHorse inbox.

    Args:
        content: The note content
        title: Optional title (auto-generated if not provided)
        tags: Optional list of tags

    Returns:
        dict with success status and details
    """
    # Generate title from first line if not provided
    if not title:
        first_line = content.split("\n")[0][:50]
        title = first_line if first_line else "Voice Note"

    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title)
    safe_title = safe_title.strip().replace(" ", "-")[:30]
    filename = f"{timestamp}_{safe_title}.md"

    # Build markdown content
    tags_str = ", ".join(tags) if tags else "work, voice-note"
    md_content = f"""---
title: {title}
created: {datetime.now().isoformat()}
source: penny
tags: [{tags_str}]
---

{content}
"""

    # Ensure inbox directory exists
    inbox_path = Path(TROJANHORSE_INBOX)
    try:
        inbox_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {
            "success": False,
            "error": f"Cannot create inbox directory: {e}",
        }

    # Write the note
    file_path = inbox_path / filename
    try:
        file_path.write_text(md_content)
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to write note: {e}",
        }

    # Optionally trigger processing
    process_triggered = False
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{TROJANHORSE_API_URL}/process",
                timeout=10,
            )
            if response.status_code == 200:
                process_triggered = True
    except Exception:
        # Processing is optional - note was already saved
        pass

    return {
        "success": True,
        "note": title,
        "file": str(file_path),
        "processed": process_triggered,
    }


async def ask_trojanhorse(question: str) -> dict[str, Any]:
    """Ask a question to TrojanHorse's RAG system.

    Args:
        question: The question to ask

    Returns:
        dict with answer and sources
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{TROJANHORSE_API_URL}/ask",
                json={"question": question},
                timeout=30,
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "answer": data.get("answer", ""),
                    "sources": data.get("sources", []),
                }
            return {
                "success": False,
                "error": f"API returned {response.status_code}",
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }
