"""Model selection logic for Claude Code builds.

Decides whether to use Z.AI's GLM-4.7 (cheap, fast) or Anthropic's Opus
(expensive, powerful) based on the transcript content and confidence.
"""

from .config.claude_code import (
    ANTHROPIC_API_KEY,
    COMPLEXITY_MARKERS,
    CONFIDENCE_THRESHOLD,
    OPUS_KEYWORDS,
    ZAI_API_KEY,
    ZAI_BASE_URL,
)


def select_model(transcript: str, classification_confidence: float) -> tuple[str, dict]:
    """Select the appropriate model based on transcript analysis.

    Args:
        transcript: The voice memo transcription
        classification_confidence: Confidence score from classifier (0.0-1.0)

    Returns:
        Tuple of (model_name, env_overrides) where:
        - model_name: "glm-4.7" or "claude-opus-4"
        - env_overrides: Dict of environment variables to set for this build

    Decision logic:
        USE OPUS IF:
        - Transcript contains urgency keywords (critical, urgent, asap, etc.)
        - Classification confidence < 0.70
        - Transcript contains complexity markers (auth, payments, migrations)

        OTHERWISE: Use GLM 4.7 via Z.AI
    """
    transcript_lower = transcript.lower()

    # Check for urgency keywords
    has_urgency = any(keyword in transcript_lower for keyword in OPUS_KEYWORDS)

    # Check for complexity markers
    has_complexity = any(marker in transcript_lower for marker in COMPLEXITY_MARKERS)

    # Low confidence suggests ambiguous request - use Opus for better understanding
    low_confidence = classification_confidence < CONFIDENCE_THRESHOLD

    # Decision: Use Opus if any escalation condition is met
    use_opus = has_urgency or has_complexity or low_confidence

    if use_opus and ANTHROPIC_API_KEY:
        return (
            "claude-opus-4",
            {
                "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
                # Remove Z.AI overrides to use default Anthropic endpoint
                "ANTHROPIC_BASE_URL": "",
                "ANTHROPIC_AUTH_TOKEN": "",
            },
        )
    else:
        # Default to GLM via Z.AI
        return (
            "glm-4.7",
            {
                "ANTHROPIC_AUTH_TOKEN": ZAI_API_KEY,
                "ANTHROPIC_BASE_URL": ZAI_BASE_URL,
                # Clear API key to avoid conflicts
                "ANTHROPIC_API_KEY": "",
            },
        )


def get_model_reason(transcript: str, classification_confidence: float) -> str:
    """Get human-readable reason for model selection.

    Args:
        transcript: The voice memo transcription
        classification_confidence: Confidence score from classifier (0.0-1.0)

    Returns:
        String explaining why the selected model was chosen
    """
    transcript_lower = transcript.lower()

    # Check conditions
    found_urgency = [kw for kw in OPUS_KEYWORDS if kw in transcript_lower]
    found_complexity = [m for m in COMPLEXITY_MARKERS if m in transcript_lower]
    low_confidence = classification_confidence < CONFIDENCE_THRESHOLD

    reasons = []

    if found_urgency:
        reasons.append(f"urgency keywords: {', '.join(found_urgency)}")
    if found_complexity:
        reasons.append(f"complexity markers: {', '.join(found_complexity)}")
    if low_confidence:
        reasons.append(f"low confidence ({classification_confidence:.0%})")

    if reasons:
        if ANTHROPIC_API_KEY:
            return f"Using Opus due to: {'; '.join(reasons)}"
        else:
            return f"Would use Opus ({'; '.join(reasons)}) but no API key configured"

    return "Using GLM-4.7 (standard build)"
