"""Claude Code integration configuration."""

import os

# Z.AI API configuration
ZAI_BASE_URL = "https://api.z.ai/api/anthropic"
ZAI_API_KEY = os.environ.get("ZAI_API_KEY", os.environ.get("ANTHROPIC_AUTH_TOKEN", ""))

# Anthropic API configuration (for Opus escalation)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Model selection keywords that trigger Opus instead of GLM
OPUS_KEYWORDS = frozenset([
    "critical",
    "urgent",
    "asap",
    "production",
    "important",
    "security",
    "emergency",
    "immediately",
])

# Complexity markers that suggest using Opus
COMPLEXITY_MARKERS = frozenset([
    "authentication",
    "auth",
    "oauth",
    "payment",
    "stripe",
    "database migration",
    "migration",
    "multi-service",
    "microservice",
    "kubernetes",
    "k8s",
])

# Confidence threshold for escalation to Opus
CONFIDENCE_THRESHOLD = float(os.environ.get("PENNY_CONFIDENCE_THRESHOLD", "0.7"))

# Telegram Q&A settings
TELEGRAM_TIMEOUT_SECONDS = 600  # 10 minutes
MAX_QUESTIONS_PER_REQUEST = 1

# Build settings
BUILDS_WORK_DIR = os.environ.get("PENNY_BUILDS_WORK_DIR", "/app/builds")
PREFERENCES_FILE = os.environ.get("PENNY_PREFERENCES_FILE", "/app/data/omar-preferences.md")

# Claude Agent SDK tools to enable
ALLOWED_TOOLS = [
    "Read",
    "Write",
    "Edit",
    "Bash",
    "Glob",
    "Grep",
    "WebSearch",
    "WebFetch",
]

# Collected config dict for easy access
CLAUDE_CODE_CONFIG = {
    "zai_base_url": ZAI_BASE_URL,
    "zai_api_key": ZAI_API_KEY,
    "anthropic_api_key": ANTHROPIC_API_KEY,
    "opus_keywords": OPUS_KEYWORDS,
    "complexity_markers": COMPLEXITY_MARKERS,
    "confidence_threshold": CONFIDENCE_THRESHOLD,
    "telegram_timeout_seconds": TELEGRAM_TIMEOUT_SECONDS,
    "max_questions_per_request": MAX_QUESTIONS_PER_REQUEST,
    "builds_work_dir": BUILDS_WORK_DIR,
    "preferences_file": PREFERENCES_FILE,
    "allowed_tools": ALLOWED_TOOLS,
}
