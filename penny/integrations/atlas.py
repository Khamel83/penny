"""Atlas integration for Penny - knowledge base queries.

Supports two modes:
1. Direct import (if Atlas is installed as a library)
2. HTTP API fallback (if Atlas runs as a separate service)

Used by the orchestrator to query: "What do I already know about this?"
"""

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Configuration
ATLAS_API_URL = os.environ.get("ATLAS_API_URL", "http://localhost:7444")
ATLAS_DB_PATH = os.environ.get("ATLAS_DB_PATH")

# Try direct library import
ATLAS_LIBRARY_AVAILABLE = False
try:
    from atlas import Atlas as AtlasLibrary
    ATLAS_LIBRARY_AVAILABLE = True
    logger.info("Atlas library available for direct import")
except ImportError:
    AtlasLibrary = None
    logger.debug("Atlas library not installed, will use HTTP API")


class AtlasClient:
    """Unified Atlas client - library or HTTP."""

    def __init__(self):
        self._library: Optional["AtlasLibrary"] = None

        if ATLAS_LIBRARY_AVAILABLE and ATLAS_DB_PATH:
            try:
                self._library = AtlasLibrary(db_path=ATLAS_DB_PATH)
                logger.info(f"Atlas library initialized with DB: {ATLAS_DB_PATH}")
            except Exception as e:
                logger.warning(f"Failed to initialize Atlas library: {e}")
                self._library = None

    @property
    def mode(self) -> str:
        """Return current mode: 'library' or 'http'."""
        return "library" if self._library else "http"

    async def search(
        self,
        query: str,
        limit: int = 5,
        min_score: float = 0.5,
    ) -> dict[str, Any]:
        """Search the knowledge base.

        Args:
            query: The search query
            limit: Maximum results
            min_score: Minimum relevance score (0-1)

        Returns:
            dict with success, results, total, and source mode
        """
        if self._library:
            return await self._search_library(query, limit, min_score)
        return await search_atlas(query, limit)

    async def _search_library(
        self,
        query: str,
        limit: int,
        min_score: float,
    ) -> dict[str, Any]:
        """Search using direct library access."""
        try:
            # Run in executor since library may be synchronous
            import asyncio

            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: self._library.search(
                    query=query,
                    limit=limit,
                    min_score=min_score,
                )
            )

            return {
                "success": True,
                "results": results,
                "total": len(results),
                "source": "library",
            }
        except Exception as e:
            logger.warning(f"Library search failed, falling back to HTTP: {e}")
            # Fallback to HTTP
            return await search_atlas(query, limit)

    async def get_context_for_task(
        self,
        task_description: str,
        max_context_chars: int = 8000,
    ) -> str:
        """Get relevant context from Atlas for a task.

        This is the "what do I already know?" query before
        spending expensive reasoning tokens.

        Args:
            task_description: Description of the task
            max_context_chars: Maximum characters of context to return

        Returns:
            Formatted context string for LLM prompt, or empty string
        """
        result = await self.search(task_description, limit=5)

        if not result.get("success") or not result.get("results"):
            return ""

        context_parts = []
        total_chars = 0

        for item in result["results"]:
            # Extract content - handle different result formats
            content = (
                item.get("content")
                or item.get("summary")
                or item.get("text")
                or item.get("excerpt", "")
            )

            if not content:
                continue

            # Check length limit
            if total_chars + len(content) > max_context_chars:
                # Truncate this item if it's the first one
                if not context_parts:
                    remaining = max_context_chars - total_chars
                    content = content[:remaining] + "..."
                else:
                    break

            # Format the context entry
            title = item.get("title", "")
            source = item.get("source", item.get("url", ""))
            score = item.get("score", item.get("relevance", ""))

            if title:
                entry = f"### {title}\n{content}"
            else:
                entry = f"- {content}"

            if source:
                entry += f"\n(Source: {source})"

            context_parts.append(entry)
            total_chars += len(content)

        if not context_parts:
            return ""

        header = "## Relevant Knowledge from Atlas\n\n"
        return header + "\n\n".join(context_parts)

    async def submit_url(
        self,
        url: str,
        tags: Optional[list[str]] = None,
        priority: str = "normal",
    ) -> dict[str, Any]:
        """Submit a URL for ingestion. Delegates to module function."""
        return await submit_url(url, tags, priority)


# Singleton client instance
atlas_client = AtlasClient()


# =============================================================================
# HTTP API Functions (original implementation, kept for compatibility)
# =============================================================================


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
    """Search Atlas knowledge base via HTTP API.

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
                    "source": "http",
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
