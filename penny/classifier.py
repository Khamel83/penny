"""LLM-powered classifier and router for Penny using OpenRouter."""

import json
import os
import re
from typing import Any

import requests

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODEL = "google/gemini-2.5-flash-lite"  # $0.25/million tokens

SYSTEM_PROMPT = """You are Penny, an intelligent voice memo router. Analyze the memo and respond with JSON.

CATEGORIES:
- shopping: Items to buy. Extract individual items as a list.
- media: Movie/TV show requests. Extract title and type (movie/tv).
- smart_home: Light/thermostat/device control. Extract action and entity.
- reminder: Tasks with due dates, things to remember. Extract task and due date/time.
- calendar: Meetings, appointments, scheduled events. Extract title, date, time, duration, location.
- work: Work-related tasks without specific dates. Extract task description.
- notes: Longer thoughts, ideas, journal entries to save. Extract title and content.
- personal: Quick thoughts that just need to be stored.

EXAMPLES:

"Add milk and eggs to my shopping list"
{"classification": "shopping", "confidence": 0.95, "items": ["milk", "eggs"]}

"Can you download the movie Inception"
{"classification": "media", "confidence": 0.9, "title": "Inception", "type": "movie"}

"Add Breaking Bad to my watch list"
{"classification": "media", "confidence": 0.9, "title": "Breaking Bad", "type": "tv"}

"Turn off all the lights"
{"classification": "smart_home", "confidence": 0.95, "action": "turn_off", "entity": "all_lights"}

"Remind me to call the dentist tomorrow at 2pm"
{"classification": "reminder", "confidence": 0.95, "task": "Call the dentist", "due_date": "tomorrow", "due_time": "2pm"}

"Schedule a meeting with John next Tuesday at 3pm at the coffee shop"
{"classification": "calendar", "confidence": 0.9, "title": "Meeting with John", "date": "next Tuesday", "time": "3pm", "location": "coffee shop"}

"I need to finish that report for the client"
{"classification": "work", "confidence": 0.8, "task": "Finish report for client"}

"I had a great idea for a new app feature that could help users track their habits"
{"classification": "notes", "confidence": 0.85, "title": "App feature idea", "content": "New feature to help users track their habits"}

"Just testing, one two three"
{"classification": "personal", "confidence": 0.9, "summary": "Test message"}

Respond with ONLY valid JSON. No explanation, no markdown, just JSON.
"""


def classify_with_llm(text: str) -> dict[str, Any]:
    """Classify and extract routing data using OpenRouter's Gemini Flash."""
    if not OPENROUTER_API_KEY:
        return classify_keywords(text)

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                "max_tokens": 200,
                "temperature": 0,
            },
            timeout=15,
        )
        response.raise_for_status()

        result = response.json()["choices"][0]["message"]["content"].strip()

        # Clean up markdown code blocks if present
        if result.startswith("```"):
            result = re.sub(r"^```(?:json)?\n?", "", result)
            result = re.sub(r"\n?```$", "", result)

        # Parse JSON
        data = json.loads(result)

        # Validate required fields
        if "classification" not in data:
            data["classification"] = "unknown"
        if "confidence" not in data:
            data["confidence"] = 0.8

        # Validate classification category
        valid_categories = {"shopping", "media", "smart_home", "reminder", "calendar", "work", "notes", "personal"}
        if data["classification"] not in valid_categories:
            data["classification"] = "unknown"

        return data

    except json.JSONDecodeError as e:
        print(f"LLM returned invalid JSON: {e}, falling back to keywords")
        return classify_keywords(text)
    except Exception as e:
        print(f"LLM classification failed: {e}, falling back to keywords")
        return classify_keywords(text)


# Fallback keyword-based classifier
KEYWORDS = {
    "shopping": [
        "shopping", "grocery", "groceries", "buy", "pick up", "pickup",
        "store", "list", "eggs", "milk", "bread", "need to get", "shopping list",
    ],
    "media": [
        "movie", "film", "show", "series", "watch", "download", "request",
        "netflix", "streaming", "episode", "season",
    ],
    "smart_home": [
        "lights", "light", "turn on", "turn off", "thermostat", "temperature",
        "blinds", "curtains", "fan", "ac", "heater",
    ],
    "reminder": [
        "remind me", "reminder", "don't forget", "remember to",
        "tomorrow", "next week", "at noon", "at midnight",
    ],
    "calendar": [
        "meeting", "schedule", "appointment", "calendar", "event",
        "conference", "block time", "book",
    ],
    "work": [
        "work", "project", "deadline", "client", "report",
        "email", "presentation", "task", "todo",
    ],
    "notes": [
        "idea", "thought", "journal", "note", "write down",
        "document", "save this", "log",
    ],
    "personal": [
        "test", "testing", "thank you", "thanks",
        "family", "birthday", "vacation",
    ],
}


def classify_keywords(text: str) -> dict[str, Any]:
    """Fallback keyword-based classification."""
    text_lower = text.lower()
    words = re.findall(r'\b\w+\b', text_lower)
    total_words = len(words) if words else 1

    scores = {}
    for category, keywords in KEYWORDS.items():
        matches = sum(1 for kw in keywords if kw in text_lower)
        scores[category] = min(matches / total_words, 1.0)

    best_category = max(scores, key=scores.get)
    best_score = scores[best_category]

    if best_score < 0.05:
        return {"classification": "unknown", "confidence": 0.0}

    result = {"classification": best_category, "confidence": best_score}

    # Extract basic data based on category
    if best_category == "shopping":
        # Try to extract items (simple word extraction)
        result["items"] = [w for w in words if len(w) > 2 and w not in
                         {"the", "and", "for", "add", "get", "buy", "some", "need", "list", "shopping"}]
    elif best_category == "work":
        result["task"] = text

    return result


def classify(text: str) -> dict[str, Any]:
    """Main classify function - uses LLM if available, else keywords."""
    return classify_with_llm(text)
