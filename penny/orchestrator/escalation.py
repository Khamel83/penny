"""Confidence-based escalation logic.

Implements the "gather signal cheap, reason expensive" pattern:
- High confidence (>=0.8): Deliver findings directly
- Medium confidence (>=0.6): Quick escalation with Sonnet
- Low confidence (<0.6): Full escalation with Opus + Atlas context
"""

import json
import logging
import os
from typing import Any

from .. import database
from ..service_router import service_router
from ..integrations import atlas
from ..integrations import telegram

logger = logging.getLogger(__name__)

# Confidence thresholds
HIGH_CONFIDENCE = float(os.environ.get("PENNY_HIGH_CONFIDENCE", "0.8"))
MEDIUM_CONFIDENCE = float(os.environ.get("PENNY_MEDIUM_CONFIDENCE", "0.6"))


async def evaluate_and_escalate(task: dict) -> dict[str, Any]:
    """Evaluate findings and decide on escalation strategy.

    Args:
        task: Background task with accumulated findings

    Returns:
        dict with action taken and result
    """
    findings = task.get("findings", [])
    confidence = task.get("confidence", 0.0)
    input_data = task.get("input_data", {})

    original_query = input_data.get("query") or input_data.get("text", "")

    logger.info(f"Evaluating task {task['id']} (confidence: {confidence:.2f})")

    if confidence >= HIGH_CONFIDENCE:
        # Findings are sufficient - synthesize and deliver
        return await deliver_findings(task, findings, original_query)

    elif confidence >= MEDIUM_CONFIDENCE:
        # Moderate confidence - quick Claude check
        return await quick_escalation(task, findings, original_query)

    else:
        # Low confidence - full escalation with Atlas context
        return await full_escalation(task, findings, original_query)


async def deliver_findings(
    task: dict,
    findings: list,
    original_query: str,
) -> dict[str, Any]:
    """Synthesize findings and deliver directly via Telegram.

    Used when confidence is high enough that we don't need LLM reasoning.
    """
    task_id = task["id"]
    logger.info(f"Delivering findings directly for task {task_id}")

    summary = synthesize_findings(findings)

    message = (
        f"**Task Complete**\n\n"
        f"**Query:** {original_query[:200]}{'...' if len(original_query) > 200 else ''}\n\n"
        f"**Findings:**\n{summary}\n\n"
        f"_Confidence: {task.get('confidence', 0):.0%}_"
    )

    await telegram.send_message(message)
    await database.update_task_status(task_id, "completed")

    return {
        "action": "delivered",
        "task_id": task_id,
        "confidence": task.get("confidence"),
        "success": True,
    }


async def quick_escalation(
    task: dict,
    findings: list,
    original_query: str,
) -> dict[str, Any]:
    """Quick escalation with minimal context.

    Uses Sonnet for fast, cheaper reasoning when findings are almost sufficient.
    """
    task_id = task["id"]
    logger.info(f"Quick escalation for task {task_id}")

    prompt = f"""You have these findings about the following query. Provide a concise, actionable answer.

**Query:** {original_query}

**Findings from probes:**
{format_findings(findings)}

Provide a brief answer or recommendation. Be direct and actionable.
"""

    result = await service_router.dispatch(
        service="claude",
        prompt=prompt,
        model="sonnet",
        timeout=120,
    )

    if result.get("success"):
        message = (
            f"**Quick Analysis**\n\n"
            f"**Query:** {original_query[:150]}{'...' if len(original_query) > 150 else ''}\n\n"
            f"{result['output'][:3500]}"
        )
        await telegram.send_message(message)
        await database.update_task_status(task_id, "completed")

        return {
            "action": "quick_escalation",
            "task_id": task_id,
            "success": True,
            "service": "claude",
            "model": "sonnet",
        }

    # Fall back to full escalation if quick fails
    logger.warning(f"Quick escalation failed for {task_id}, trying full: {result.get('error')}")
    return await full_escalation(task, findings, original_query)


async def full_escalation(
    task: dict,
    findings: list,
    original_query: str,
) -> dict[str, Any]:
    """Full escalation with Atlas context and Opus model.

    Used when confidence is low - needs comprehensive analysis.
    """
    task_id = task["id"]
    logger.info(f"Full escalation for task {task_id}")

    # Get Atlas context - "What do I already know?"
    atlas_context = await atlas.atlas_client.get_context_for_task(original_query)

    prompt = f"""Analyze this task thoroughly and provide comprehensive guidance.

**Original Request:**
{original_query}

{atlas_context if atlas_context else "_(No relevant knowledge found in Atlas)_"}

**Probe Findings:**
{format_findings(findings)}

Provide:
1. Analysis of what the probes found
2. What's still unclear or needs investigation
3. Recommended next steps or solution

Be thorough but actionable.
"""

    result = await service_router.dispatch(
        service="claude",
        prompt=prompt,
        model="opus",
        timeout=300,
    )

    if result.get("success"):
        # Truncate for Telegram (4096 char limit)
        output = result["output"]
        if len(output) > 3500:
            output = output[:3500] + "\n\n_...truncated_"

        message = (
            f"**Full Analysis**\n\n"
            f"**Query:** {original_query[:100]}{'...' if len(original_query) > 100 else ''}\n\n"
            f"{output}"
        )
        await telegram.send_message(message)
        await database.update_task_status(task_id, "completed")

        return {
            "action": "full_escalation",
            "task_id": task_id,
            "success": True,
            "service": "claude",
            "model": "opus",
            "had_atlas_context": bool(atlas_context),
        }

    # Mark as failed
    error_msg = result.get("error", "Unknown error")
    await database.update_task_status(
        task_id,
        "failed",
        error_message=f"Full escalation failed: {error_msg}",
    )

    # Notify about failure
    await telegram.send_message(
        f"**Task Failed**\n\n"
        f"Query: {original_query[:100]}...\n\n"
        f"Error: {error_msg}"
    )

    return {
        "action": "full_escalation",
        "task_id": task_id,
        "success": False,
        "error": error_msg,
    }


def synthesize_findings(findings: list) -> str:
    """Synthesize probe findings into human-readable summary."""
    if not findings:
        return "No findings available."

    parts = []
    for f in findings:
        probe = f.get("probe", "unknown")

        if probe == "grep":
            matches = f.get("total_matches", 0)
            pattern = f.get("pattern", "?")
            if matches > 0:
                files = f.get("files", [])[:3]
                file_list = ", ".join(file.get("file", "?") for file in files)
                parts.append(f"- Code search for `{pattern}`: {matches} matches in {file_list}")
            else:
                parts.append(f"- Code search for `{pattern}`: No matches found")

        elif probe == "atlas":
            count = f.get("results_count", 0)
            query = f.get("query", "?")[:50]
            if count > 0:
                parts.append(f"- Knowledge base: {count} relevant entries for \"{query}\"")
            else:
                parts.append(f"- Knowledge base: No entries found for \"{query}\"")

        elif probe == "file_read":
            found = f.get("files_found", 0)
            checked = f.get("files_checked", 0)
            parts.append(f"- File analysis: {found}/{checked} files found and readable")

        elif probe == "api_check":
            healthy = f.get("healthy_count", 0)
            checked = f.get("urls_checked", 0)
            parts.append(f"- API health check: {healthy}/{checked} endpoints healthy")

        elif probe == "command":
            cmd = f.get("command", "?")[:30]
            success = f.get("success", False)
            if success:
                output = f.get("output", "")[:100]
                parts.append(f"- Command `{cmd}`: {output}")
            else:
                error = f.get("error", "failed")
                parts.append(f"- Command `{cmd}`: {error}")

        elif f.get("error"):
            parts.append(f"- {probe} probe: Error - {f.get('error')}")

    return "\n".join(parts) if parts else "Findings inconclusive."


def format_findings(findings: list) -> str:
    """Format findings for LLM consumption."""
    if not findings:
        return "No findings collected."

    return json.dumps(findings, indent=2, default=str)
