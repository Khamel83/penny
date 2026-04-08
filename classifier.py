#!/usr/bin/env python3
"""
LLM-based transcript classifier using OpenRouter.

Extracts actionable items from voice memo transcripts and classifies
each into a reminder category. Returns structured JSON.
"""
import json
import logging
from typing import Dict, Any

import requests

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

CATEGORIES = ["groceries", "errands", "home", "health", "work", "kids", "inbox"]

CONTENT_TYPE_PROMPT = """You are analyzing a voice memo or text note. Classify it into exactly one type:

- "action_items": Short, focused notes with clear actionable items (to-dos, reminders, shopping lists). The speaker is clearly asking themselves to do specific things.
- "long_note": Long entries that are primarily journal entries, brainstorming sessions, meeting notes, stories, or rambling thoughts. May contain some actionable items buried in lots of other content.
- "unclear": You genuinely cannot tell, or the text is very short and ambiguous.

Rules:
- Under 150 words with clear action verbs (buy, call, schedule, pick up, remind, etc.) = action_items
- Over 150 words, or primarily narrative/reflective/brainstorming = long_note
- Very short text (under 20 words) that could go either way = unclear

Respond with ONLY the type name, nothing else."""

SYSTEM_PROMPT = """You are a personal assistant that extracts actionable reminders from voice memo transcripts.

Categories (pick exactly one per item):
- groceries: items to buy at the grocery store or food shopping
- errands: tasks requiring leaving home (appointments, store visits, pickups, drop-offs)
- home: household tasks, repairs, maintenance, cleaning, home improvement
- health: medical/dental appointments, medications, exercise, wellness, self-care
- work: professional tasks, meetings, deadlines, career-related items
- kids: anything related to children (school, activities, supplies, appointments)
- inbox: anything actionable that doesn't clearly fit the above categories

Rules:
1. If the transcript has NO actionable items (journal entry, note to someone, music idea, random thought, etc.) respond with: {"skip": true, "reason": "<brief reason>"}
2. Extract ALL distinct actionable items, even if there are many in one memo
3. Use short, clear descriptions. For groceries, use just the item name (e.g. "milk" not "buy milk"). For other categories, use a brief action phrase (e.g. "call dentist" not "I need to call the dentist").
4. When in doubt about category, use inbox
5. Respond ONLY with valid JSON — no explanation, no markdown fences

Output for reminders:
{"items": [{"item": "milk", "category": "groceries"}, {"item": "call dentist", "category": "health"}]}

Output for non-reminders:
{"skip": true, "reason": "journal entry about the day"}"""


def classify(transcript: str, api_key: str, model: str) -> Dict[str, Any]:
    """
    Classify a transcript into actionable reminder items.

    Returns one of:
      {"items": [{"item": str, "category": str}, ...]}
      {"skip": True, "reason": str}
      {"items": [...], "fallback": True}  — on API/parse failure, raw text goes to Inbox
    """
    if not transcript.strip():
        return {"skip": True, "reason": "empty transcript"}

    # Safety truncation — long notes should be caught by detect_content_type,
    # but if they slip through, don't burn tokens.
    if len(transcript) > 4000:
        transcript = transcript[:4000] + "\n[...truncated]"

    if not api_key:
        log.warning("OPENROUTER_API_KEY not set — falling back to Inbox")
        return _fallback(transcript)

    try:
        resp = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Transcript: {transcript}"},
                ],
                "temperature": 0.1,
                "max_tokens": 512,
            },
            timeout=30,
        )
        resp.raise_for_status()

        content = resp.json()["choices"][0]["message"]["content"].strip()

        # Strip markdown code fences if the model wraps the response
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        result = json.loads(content)

        if "skip" in result:
            return {"skip": True, "reason": result.get("reason", "not a reminder")}

        if "items" in result and isinstance(result["items"], list):
            valid = []
            for item in result["items"]:
                if isinstance(item, dict) and "item" in item and "category" in item:
                    cat = item["category"].lower().strip()
                    if cat not in CATEGORIES:
                        cat = "inbox"
                    valid.append({"item": item["item"], "category": cat})
            if valid:
                return {"items": valid}

        log.warning(f"Unexpected classifier response structure: {result}")
        return _fallback(transcript)

    except json.JSONDecodeError as e:
        log.error(f"Classifier returned invalid JSON: {e}")
        return _fallback(transcript)
    except requests.RequestException as e:
        log.error(f"Classifier API call failed: {e}")
        return _fallback(transcript)
    except Exception as e:
        log.error(f"Classifier unexpected error: {e}", exc_info=True)
        return _fallback(transcript)


def _fallback(transcript: str) -> Dict[str, Any]:
    """Fallback: put raw transcript in Inbox so nothing is lost."""
    log.warning("Classification failed — falling back to Inbox with raw transcript")
    # Keep the full transcript so an API outage does not silently drop details.
    item_text = transcript.strip()
    return {"items": [{"item": item_text, "category": "inbox"}], "fallback": True}


def detect_content_type(transcript: str, api_key: str, model: str) -> str:
    """
    Pre-classify a transcript as 'action_items', 'long_note', or 'unclear'.

    Returns 'unclear' on API failure (safest default).
    """
    if not api_key:
        return "unclear"

    valid_types = {"action_items", "long_note", "unclear"}

    try:
        resp = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": CONTENT_TYPE_PROMPT},
                    {"role": "user", "content": f"Transcript: {transcript}"},
                ],
                "temperature": 0.1,
                "max_tokens": 16,
            },
            timeout=15,
        )
        resp.raise_for_status()

        content = resp.json()["choices"][0]["message"]["content"].strip().lower()
        if content in valid_types:
            return content

        log.warning("Unexpected content type response: %s", content)
        return "unclear"

    except Exception as e:
        log.error("Content type detection failed: %s", e)
        return "unclear"
