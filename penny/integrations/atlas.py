"""Atlas integration for Penny - URL ingestion.

Submits URLs to Atlas for ingestion into the knowledge base.
"""

import os
import httpx
from typing import Any, Optional

# Atlas configuration
ATLAS_API_URL = os.environ.get(
    "ATLAS_API_URL",
    "http://localhost:7444"
)


async def submit_url(
    url: str,
    tags: Optional[list[str]] = None,
    priority: str = "normal",
) -> dict[str, Any]:
    """Submit a URL to Atlas for ingestion.

    Args:
        url: The URL to ingest
        tags: Optional tags for categorization
        priority: Priority level (low, normal, high)

    Returns:
        dict with success status and details
    """
    payload = {
        "url": url,
        "priority": priority,
    }
    if tags:
        payload["tags"] = tags

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{ATLAS_API_URL}/api/v1/content/submit-url",
                json=payload,
                timeout=30,
            )
            if response.status_code in (200, 201, 202):
                data = response.json()
                return {
                    "success": True,
                    "url": url,
                    "status": data.get("status", "queued"),
                    "message": data.get("message", "URL submitted for ingestion"),
                }
            return {
                "success": False,
                "error": f"Atlas API returned {response.status_code}: {response.text}",
            }
    except httpx.ConnectError:
        return {
            "success": False,
            "error": "Cannot connect to Atlas API - is it running?",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def search_atlas(
    query: str,
    limit: int = 5,
) -> dict[str, Any]:
    """Search Atlas knowledge base.

    Args:
        query: The search query
        limit: Maximum results to return

    Returns:
        dict with search results
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{ATLAS_API_URL}/api/v1/search",
                params={"q": query, "limit": limit},
                timeout=30,
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "results": data.get("results", []),
                    "total": data.get("total", 0),
                }
            return {
                "success": False,
                "error": f"Search failed: {response.status_code}",
            }
    except httpx.ConnectError:
        return {
            "success": False,
            "error": "Cannot connect to Atlas API",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }
