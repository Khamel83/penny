"""Background task orchestrator for Penny.

Implements the "gather signal cheap, reason expensive" pattern:
1. Accept tasks from various sources
2. Run cheap probes while human is away
3. Accumulate findings into a problem map
4. Escalate to expensive reasoning only when needed
5. Deliver results via Telegram when ready
"""

from .loop import BackgroundOrchestrator

__all__ = ["BackgroundOrchestrator"]
