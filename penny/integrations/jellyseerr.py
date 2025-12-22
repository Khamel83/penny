"""Jellyseerr integration for Penny - media requests."""

import os
from typing import Any

import httpx

JELLYSEERR_URL = os.environ.get("JELLYSEERR_URL", "http://jellyseerr:5055")
JELLYSEERR_API_KEY = os.environ.get("JELLYSEERR_API_KEY", "")


async def request_media(title: str, media_type: str = "movie") -> dict[str, Any]:
    """Search for media and create a request.

    Args:
        title: The movie or TV show title to search for
        media_type: Either "movie" or "tv"

    Returns:
        Result of the request operation
    """
    if not JELLYSEERR_API_KEY:
        raise ValueError("JELLYSEERR_API_KEY must be set")

    headers = {"X-Api-Key": JELLYSEERR_API_KEY}

    async with httpx.AsyncClient() as client:
        # Search for the media
        search_resp = await client.get(
            f"{JELLYSEERR_URL}/api/v1/search",
            params={"query": title, "page": 1, "language": "en"},
            headers=headers,
            timeout=15,
        )
        search_resp.raise_for_status()
        search_data = search_resp.json()

        if not search_data.get("results"):
            return {"success": False, "error": f"No results found for '{title}'"}

        # Find the best match (prefer exact matches and requested type)
        results = search_data["results"]
        best_match = None
        for result in results:
            result_type = result.get("mediaType", "")
            if result_type == media_type:
                best_match = result
                break
        if not best_match:
            best_match = results[0]  # Take first result if no type match

        media_id = best_match["id"]
        actual_type = best_match.get("mediaType", media_type)
        found_title = best_match.get("title") or best_match.get("name", title)

        # Create the request
        request_resp = await client.post(
            f"{JELLYSEERR_URL}/api/v1/request",
            headers=headers,
            json={
                "mediaType": actual_type,
                "mediaId": media_id,
            },
            timeout=15,
        )

        if request_resp.status_code == 409:
            return {
                "success": True,
                "message": f"'{found_title}' already requested or available",
                "mediaId": media_id,
                "mediaType": actual_type,
            }

        request_resp.raise_for_status()
        request_data = request_resp.json()

        return {
            "success": True,
            "message": f"Requested '{found_title}' ({actual_type})",
            "mediaId": media_id,
            "mediaType": actual_type,
            "requestId": request_data.get("id"),
        }
