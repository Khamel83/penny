#!/usr/bin/env python3
"""
LLM-based transcript classifier.

Configured pipeline callers use the explicit LangExtract provider registry.
The legacy request path remains available for existing direct callers during
the transitional migration.

"""
import logging
import json
from typing import Any, Dict

import requests

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

CATEGORIES = ["groceries", "errands", "home", "health", "work", "kids", "inbox", "project"]


def _safe_exception_class(exc: BaseException) -> str:
    name = type(exc).__name__
    if name and len(name) <= 48 and name[0].isalpha() and all(
        character.isalnum() or character == "_" for character in name
    ):
        return name
    return "Exception"

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
- project: a software/code task, bug, or idea for one of the user's own software projects or repositories — something that belongs in a GitHub issue, not a personal to-do
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


def _build_context(transcript: str, duration_seconds: float | None = None) -> str:
    metadata = []
    if duration_seconds is not None:
        metadata.append(f"Approximate audio duration: {duration_seconds:.1f} seconds")
    metadata.append(f"Transcript length: {len(transcript.split())} words")
    metadata_blob = "\n".join(metadata)
    return (
        f"{metadata_blob}\nTranscript: {transcript}"
        if metadata_blob
        else f"Transcript: {transcript}"
    )
def _provider_content(provider: Any, prompt: str) -> str:
    """Return one provider completion without exposing its response."""
    batches = provider.infer([prompt])
    if isinstance(batches, (str, bytes)):
        output = batches
    else:
        try:
            batch = next(iter(batches))
        except TypeError:
            batch = batches
        if isinstance(batch, (str, bytes)):
            output = batch
        elif isinstance(batch, dict):
            output = batch.get("output")
        else:
            try:
                first = next(iter(batch))
            except TypeError:
                first = batch
            output = getattr(first, "output", first)
    if not isinstance(output, str) or not output.strip():
        raise ValueError("provider returned no text")
    return output.strip()


def _provider_prompt(system_prompt: str, context: str) -> str:
    return f"{system_prompt}\n\n{context}\n\nRespond with only the requested output."


def classify(
    transcript: str,
    api_key: str,
    model: str,
    *,
    duration_seconds: float | None = None,
    provider: Any | None = None,
) -> Dict[str, Any]:
    """
    Classify a transcript into actionable reminder items.

    A configured LangExtract provider is used when supplied. The request-based
    arguments remain supported for existing callers during the migration.
    """
    if not transcript.strip():
        return {"skip": True, "reason": "empty transcript"}

    if len(transcript) > 4000:
        transcript = transcript[:4000] + "\n[...truncated]"

    if provider is None and not api_key:
        log.warning("Classifier credentials missing — falling back to Inbox")
        return _fallback(transcript)

    try:
        context = _build_context(transcript, duration_seconds=duration_seconds)
        if provider is not None:
            content = _provider_content(
                provider, _provider_prompt(SYSTEM_PROMPT, context)
            )
        else:
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
                        {"role": "user", "content": context},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 512,
                },
                timeout=30,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()

        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(
                lines[1:-1] if lines[-1].startswith("```") else lines[1:]
            )

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

        log.warning("Classifier response rejected code=unexpected_shape")
        return _fallback(transcript)

    except json.JSONDecodeError as exc:
        log.error(
            "Classifier provider response rejected code=invalid_json class=%s",
            _safe_exception_class(exc),
        )
        return _fallback(transcript)
    except Exception as exc:
        log.error(
            "Classifier provider failure class=%s",
            _safe_exception_class(exc),
        )
        return _fallback(transcript)


def _fallback(transcript: str) -> Dict[str, Any]:
    """Fallback: put raw transcript in Inbox so nothing is lost."""
    log.warning("Classification failed — falling back to Inbox with raw transcript")
    # Keep the full transcript so an API outage does not silently drop details.
    item_text = transcript.strip()
    return {"items": [{"item": item_text, "category": "inbox"}], "fallback": True}


def detect_content_type(
    transcript: str,
    api_key: str,
    model: str,
    *,
    duration_seconds: float | None = None,
    provider: Any | None = None,
) -> str:
    """
    Pre-classify a transcript as 'action_items', 'long_note', or 'unclear'.

    Returns 'unclear' on provider failure (safest default).
    """
    if provider is None and not api_key:
        return "unclear"

    valid_types = {"action_items", "long_note", "unclear"}

    try:
        context = _build_context(transcript, duration_seconds=duration_seconds)
        if provider is not None:
            content = _provider_content(
                provider, _provider_prompt(CONTENT_TYPE_PROMPT, context)
            ).lower()
        else:
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
                        {"role": "user", "content": context},
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

        log.warning("Content type response rejected code=unexpected_value")
        return "unclear"

    except Exception as exc:
        log.error(
            "Content type provider failure class=%s",
            _safe_exception_class(exc),
        )
        return "unclear"
