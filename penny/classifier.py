"""Simple keyword-based classifier for Penny."""

import re
from typing import Tuple

# Keywords for each classification
KEYWORDS = {
    "shopping": [
        "shopping", "grocery", "groceries", "buy", "pick up", "pickup",
        "store", "list", "eggs", "milk", "bread", "need to get", "run out of",
        "supermarket", "walmart", "target", "costco", "trader joe",
    ],
    "work": [
        "meeting", "meetings", "HR", "project", "deadline", "client", "clients",
        "work", "email", "emails", "call", "conference", "presentation",
        "report", "boss", "manager", "team", "sprint", "standup", "review",
        "one-on-one", "1:1", "sync", "agenda", "action item",
    ],
    "personal": [
        "remember", "idea", "ideas", "thought", "thoughts", "journal",
        "note to self", "remind me", "don't forget", "personal", "family",
        "birthday", "anniversary", "vacation", "trip", "hobby", "dream",
    ],
}


def classify(text: str) -> Tuple[str, float]:
    """
    Classify text into a category using keyword matching.

    Returns:
        Tuple of (classification, confidence)
        - classification: one of 'shopping', 'work', 'personal', 'unknown'
        - confidence: 0.0 to 1.0 based on keyword density
    """
    text_lower = text.lower()
    words = re.findall(r'\b\w+\b', text_lower)
    total_words = len(words) if words else 1

    scores = {}

    for category, keywords in KEYWORDS.items():
        matches = 0
        for keyword in keywords:
            # Handle multi-word keywords
            if " " in keyword:
                if keyword in text_lower:
                    matches += 2  # Boost multi-word matches
            else:
                matches += text_lower.count(keyword)

        # Score is matches per word, capped at 1.0
        scores[category] = min(matches / total_words, 1.0)

    # Find the best match
    best_category = max(scores, key=scores.get)
    best_score = scores[best_category]

    # Threshold: if best score is too low, classify as unknown
    if best_score < 0.05:  # At least 5% keyword density
        return "unknown", 0.0

    return best_category, best_score


def get_classification_emoji(classification: str) -> str:
    """Get an emoji for a classification."""
    emojis = {
        "shopping": "cart",
        "work": "briefcase",
        "personal": "thought",
        "unknown": "question",
    }
    return emojis.get(classification, "question")
