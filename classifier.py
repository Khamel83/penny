#!/usr/bin/env python3
"""
LLM-based transcript classifier using OpenRouter.

Extracts actionable items from voice memo transcripts and classifies
each into a reminder category. Returns structured JSON.
"""

import logging
from typing import Any, Dict

import langextract as lx
from langextract.providers.openai import OpenAILanguageModel
import requests
log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

CATEGORIES = ["groceries", "errands", "home", "health", "work", "kids", "inbox", "project"]
CLASSIFIER_OUTPUT_SCHEMA = lx.schema.extractions_schema(
    lx.schema.extraction_item_schema(
        "reminder",
        attributes={
            "category": {
                "type": "string",
                "enum": CATEGORIES,
            }
        },
    )
)


class _OpenRouterLanguageModel(OpenAILanguageModel):
    """OpenAI-compatible LangExtract provider configured for OpenRouter."""

    def __init__(self, *, timeout: float = 30.0, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        import openai

        self._client = openai.OpenAI(
            api_key=kwargs["api_key"],
            base_url=kwargs["base_url"],
            timeout=timeout,
        )



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

SYSTEM_PROMPT = """Extract every distinct actionable reminder from the transcript.

Create one `reminder` extraction per actionable item. Put its category in the
`category` attribute, choosing exactly one of: groceries, errands, home,
health, work, kids, project, inbox.

Use short, clear descriptions. For groceries, use just the item name (for
example, "milk" rather than "buy milk"). For other categories, use a brief
action phrase (for example, "call dentist" rather than "I need to call the
dentist"). Use exact text from the transcript for each extraction. When no
actionable items are present, return no extractions."""


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


def classify(
    transcript: str,
    api_key: str,
    model: str,
    *,
    duration_seconds: float | None = None,
) -> Dict[str, Any]:
    """
    Classify a transcript into actionable reminder items.

    Returns one of:
      {"items": [{"item": str, "category": str}, ...]}
      {"skip": True, "reason": str}
      {"items": [...], "fallback": True}  — on provider/extraction failure
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
        context = _build_context(transcript, duration_seconds=duration_seconds)
        language_model = _OpenRouterLanguageModel(
            model_id=model,
            api_key=api_key,
            base_url=OPENROUTER_URL.removesuffix("/chat/completions"),
            timeout=30.0,
            temperature=0.1,
            max_output_tokens=512,
            max_workers=1,
        )
        result = lx.extract(
            text_or_documents=context,
            prompt_description=SYSTEM_PROMPT,
            model=language_model,
            output_schema=CLASSIFIER_OUTPUT_SCHEMA,
            fence_output=False,
            max_char_buffer=len(context),
            max_workers=1,
            show_progress=False,
        )
        extractions = getattr(result, "extractions", None)
        if not isinstance(extractions, list):
            raise ValueError("extractions missing")
        if not extractions:
            return {"skip": True, "reason": "no actionable items"}

        items = []
        for extraction in extractions:
            if getattr(extraction, "extraction_class", None) != "reminder":
                raise ValueError("unexpected extraction class")
            item_text = getattr(extraction, "extraction_text", None)
            attributes = getattr(extraction, "attributes", None)
            category = attributes.get("category") if isinstance(attributes, dict) else None
            if (
                not isinstance(item_text, str)
                or not item_text.strip()
                or not isinstance(category, str)
                or category not in CATEGORIES
            ):
                raise ValueError("malformed reminder extraction")
            items.append({"item": item_text, "category": category})
        return {"items": items}
    except Exception as e:
        log.error(
            "Classifier provider failure class=%s",
            _safe_exception_class(e),
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
) -> str:
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
                    {
                        "role": "user",
                        "content": _build_context(
                            transcript, duration_seconds=duration_seconds
                        ),
                    },
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

    except Exception as e:
        log.error(
            "Content type provider failure class=%s",
            _safe_exception_class(e),
        )
        return "unclear"
