"""Telegram Q&A integration for Claude Code builds.

Handles asking Omar questions via Telegram and waiting for responses
via webhook callback.
"""

import asyncio
from typing import Any, Optional

from . import telegram
from .. import database
from ..config.claude_code import TELEGRAM_TIMEOUT_SECONDS

# In-memory storage for pending question futures
# Key: build_id, Value: asyncio.Future that resolves with the answer
pending_questions: dict[str, asyncio.Future] = {}


async def ask_omar(
    question: str,
    build_id: str,
    context: Optional[str] = None,
) -> str:
    """Send question to Omar via Telegram and wait for response.

    Args:
        question: The question to ask
        build_id: The build session ID (used to match replies)
        context: Optional context about what the build is doing

    Returns:
        Omar's answer, or a reasonable default if timeout

    Note:
        This function blocks until either:
        1. Omar replies via Telegram (webhook triggers resolve_answer)
        2. Timeout occurs (10 minutes by default)
    """
    # Build the message
    message_parts = ["🔧 <b>Build needs your input:</b>"]
    if context:
        message_parts.append(f"\n<i>{context}</i>\n")
    message_parts.append(f"\n{question}")
    message_parts.append("\n\n<i>Reply to this message with your answer.</i>")
    message = "".join(message_parts)

    # Send the Telegram message
    try:
        result = await telegram.send_message(message)
        message_id = result.get("result", {}).get("message_id")
    except Exception as e:
        # If we can't send, make a default decision
        default = infer_reasonable_default(question)
        return default

    # Save pending question to database
    await database.save_pending_question(
        build_id=build_id,
        question=question,
        message_id=str(message_id) if message_id else None,
    )

    # Create future to wait for answer
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    pending_questions[build_id] = future

    try:
        # Wait for answer with timeout
        answer = await asyncio.wait_for(
            future,
            timeout=TELEGRAM_TIMEOUT_SECONDS,
        )
        return answer
    except asyncio.TimeoutError:
        # Make reasonable default and notify Omar
        default = infer_reasonable_default(question)
        timeout_msg = f"⏰ <b>Timeout</b> - no response after {TELEGRAM_TIMEOUT_SECONDS // 60} minutes.\n\nUsing default: <code>{default}</code>"
        try:
            await telegram.send_message(timeout_msg)
        except Exception:
            pass
        return default
    finally:
        # Clean up
        pending_questions.pop(build_id, None)
        await database.delete_pending_question(build_id)


def resolve_answer(build_id: str, answer: str) -> bool:
    """Resolve a pending question with Omar's answer.

    Args:
        build_id: The build session ID
        answer: Omar's answer from Telegram

    Returns:
        True if a pending question was resolved, False otherwise
    """
    future = pending_questions.get(build_id)
    if future and not future.done():
        future.set_result(answer)
        return True
    return False


def infer_reasonable_default(question: str) -> str:
    """Infer a reasonable default answer based on the question.

    Args:
        question: The question that was asked

    Returns:
        A reasonable default answer
    """
    question_lower = question.lower()

    # Yes/No questions - default to "yes" for proceeding
    if any(q in question_lower for q in ["should i", "do you want", "would you like", "can i"]):
        return "yes"

    # Choice questions with "or" - pick the first option
    if " or " in question_lower:
        # Try to extract first option
        parts = question.split(" or ")
        if parts:
            first = parts[0].split()[-1] if parts[0].split() else "first option"
            return first

    # Location/path questions - use sensible defaults
    if any(w in question_lower for w in ["where", "path", "directory", "folder"]):
        return "default location"

    # Name questions
    if any(w in question_lower for w in ["name", "call it", "title"]):
        return "default"

    # Deployment questions
    if "deploy" in question_lower:
        if "vercel" in question_lower:
            return "vercel"
        return "vercel"  # Default deployment target

    # Framework/library questions
    if any(w in question_lower for w in ["framework", "library", "use for"]):
        if "frontend" in question_lower:
            return "react with tailwind"
        if "backend" in question_lower:
            return "fastapi"
        if "database" in question_lower:
            return "sqlite"
        return "simplest option"

    # Generic fallback
    return "proceed with default"


async def notify_build_complete(
    build_id: str,
    success: bool,
    summary: str,
    deliverables: Optional[list[str]] = None,
    deployed_url: Optional[str] = None,
) -> dict[str, Any]:
    """Send build completion notification to Omar.

    Args:
        build_id: The build session ID
        success: Whether the build succeeded
        summary: Summary of what was built
        deliverables: List of deliverables (URLs, files, etc.)
        deployed_url: The URL where the build is deployed and accessible

    Returns:
        Telegram send result
    """
    emoji = "✅" if success else "❌"
    status = "completed" if success else "failed"

    message_parts = [f"{emoji} <b>Build {status}</b>"]

    # Show deployed URL prominently if available
    if deployed_url:
        message_parts.append(f"\n\n🌐 <b>Live at:</b> {deployed_url}")

    message_parts.append(f"\n\n{summary}")

    if deliverables:
        message_parts.append("\n\n<b>Deliverables:</b>")
        for item in deliverables:
            message_parts.append(f"\n• {item}")

    message = "".join(message_parts)
    return await telegram.send_message(message)
