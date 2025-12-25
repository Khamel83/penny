"""Claude Code integration for Penny.

Routes build requests to Claude Code via the Claude Agent SDK,
using Z.AI's GLM-4.7 for most builds or Anthropic's Opus for critical ones.

Integrates with ONE_SHOT build system for autonomous project development.

After build completes, automatically deploys:
- Static sites → penny-builds nginx → <project>.builds.khamel.com
- Backend services → OCI-Dev → <project>.deer-panga.ts.net
"""

import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional

from .. import database
from ..config.claude_code import (
    ALLOWED_TOOLS,
    BUILDS_WORK_DIR,
    PREFERENCES_FILE,
)
from ..model_selector import get_model_reason, select_model
from . import deploy, telegram_qa

logger = logging.getLogger(__name__)

# ONE_SHOT paths
ONESHOT_AGENTS_MD = Path.home() / "github/oneshot/AGENTS.md"
ONESHOT_SKILLS_DIR = Path.home() / ".claude/skills/oneshot"


def load_preferences() -> str:
    """Load Omar's preferences from file.

    Returns:
        Preferences content as string, or empty string if not found
    """
    try:
        path = Path(PREFERENCES_FILE)
        if path.exists():
            return path.read_text()
    except Exception:
        pass
    return ""


def load_oneshot_agents() -> str:
    """Load the ONE_SHOT AGENTS.md orchestrator.

    Returns:
        AGENTS.md content, or empty string if not found
    """
    try:
        if ONESHOT_AGENTS_MD.exists():
            return ONESHOT_AGENTS_MD.read_text()
    except Exception as e:
        logger.warning(f"Failed to load AGENTS.md: {e}")
    return ""


def load_oneshot_skill(skill_name: str) -> str:
    """Load a specific ONE_SHOT skill.

    Args:
        skill_name: Name of the skill directory (e.g., 'oneshot-core')

    Returns:
        Skill content, or empty string if not found
    """
    try:
        skill_path = ONESHOT_SKILLS_DIR / skill_name / "SKILL.md"
        if skill_path.exists():
            return skill_path.read_text()
    except Exception as e:
        logger.warning(f"Failed to load skill {skill_name}: {e}")
    return ""


def build_prompt(transcript: str, preferences: str) -> str:
    """Build the prompt for Claude Code using ONE_SHOT methodology.

    Integrates AGENTS.md skill router and oneshot-core skill for
    autonomous project development.

    Args:
        transcript: The voice memo transcription
        preferences: Omar's preferences content

    Returns:
        Full prompt string for Claude with ONE_SHOT context
    """
    prompt_parts = []

    # Load ONE_SHOT orchestrator (AGENTS.md)
    agents_md = load_oneshot_agents()
    if agents_md:
        prompt_parts.append("# ONE_SHOT Build System\n\n")
        prompt_parts.append(agents_md)
        prompt_parts.append("\n\n---\n\n")

    # Load oneshot-core skill for build requests
    oneshot_skill = load_oneshot_skill("oneshot-core")
    if oneshot_skill:
        prompt_parts.append("# Active Skill: oneshot-core\n\n")
        prompt_parts.append(oneshot_skill)
        prompt_parts.append("\n\n---\n\n")

    # Add Omar's preferences
    if preferences:
        prompt_parts.append("# Omar's Preferences\n\n")
        prompt_parts.append(preferences)
        prompt_parts.append("\n\n---\n\n")

    # Add the build request with ONE_SHOT trigger
    prompt_parts.append("# Build Request (ONE_SHOT)\n\n")
    prompt_parts.append(transcript)
    prompt_parts.append("\n\n---\n\n")

    # Add Penny-specific instructions
    prompt_parts.append("# Penny Integration Instructions\n\n")
    prompt_parts.append("You are being invoked via Penny (Omar's voice assistant).\n\n")
    prompt_parts.append("**Important context:**\n")
    prompt_parts.append("- This request came from a voice memo transcription\n")
    prompt_parts.append("- Follow the ONE_SHOT methodology above\n")
    prompt_parts.append("- Use YOLO mode for faster execution when appropriate\n")
    prompt_parts.append("- Deploy static sites to penny-builds (*.builds.khamel.com)\n")
    prompt_parts.append("- Deploy backend services to OCI-Dev\n")
    prompt_parts.append("- If you need clarification, ask ONE specific question\n")
    prompt_parts.append("- Return a summary of what was built and deliverables (URLs)\n")

    return "".join(prompt_parts)


async def handle_build(
    transcript: str,
    metadata: Optional[dict] = None,
) -> dict[str, Any]:
    """Execute a build request via Claude Agent SDK.

    Args:
        transcript: The voice memo transcription describing what to build
        metadata: Optional metadata including confidence score

    Returns:
        Dict with success status, output, and deliverables
    """
    metadata = metadata or {}
    confidence = metadata.get("confidence", 0.0)

    # Generate unique build ID
    build_id = str(uuid.uuid4())

    # Select model based on transcript analysis
    model_name, env_overrides = select_model(transcript, confidence)
    model_reason = get_model_reason(transcript, confidence)

    # Create build session in database
    await database.save_claude_session(
        session_id=build_id,
        transcript=transcript,
        model_used=model_name,
        status="running",
    )

    # Notify via Telegram that build is starting
    try:
        await telegram_qa.notify_build_complete(
            build_id=build_id,
            success=True,
            summary=f"🚀 Starting build...\n\nModel: {model_name}\nReason: {model_reason}\n\nTranscript: {transcript[:200]}...",
        )
    except Exception:
        pass  # Don't fail if notification fails

    try:
        # Try to use Claude Agent SDK
        result = await _run_with_agent_sdk(
            build_id=build_id,
            transcript=transcript,
            model_name=model_name,
            env_overrides=env_overrides,
        )
    except ImportError:
        # Claude Agent SDK not installed - use CLI fallback
        result = await _run_with_cli(
            build_id=build_id,
            transcript=transcript,
            model_name=model_name,
            env_overrides=env_overrides,
        )
    except Exception as e:
        # Build failed
        result = {
            "success": False,
            "output": f"Build failed: {str(e)}",
            "deliverables": [],
            "error": str(e),
        }

    # Update session with result
    await database.update_claude_session(
        session_id=build_id,
        status="completed" if result.get("success") else "failed",
        result=result.get("output", ""),
        deliverables=result.get("deliverables", []),
    )

    # Deploy the build if successful
    deployed_url = None
    if result.get("success"):
        deployed_url = await _deploy_build_output(build_id, result)
        if deployed_url:
            # Add deployed URL to deliverables
            deliverables = result.get("deliverables", [])
            if deployed_url not in deliverables:
                deliverables.insert(0, deployed_url)
                result["deliverables"] = deliverables
                result["deployed_url"] = deployed_url

    # Notify completion
    try:
        await telegram_qa.notify_build_complete(
            build_id=build_id,
            success=result.get("success", False),
            summary=result.get("output", "Build completed"),
            deliverables=result.get("deliverables"),
            deployed_url=deployed_url,
        )
    except Exception:
        pass

    return result


async def _deploy_build_output(build_id: str, result: dict) -> Optional[str]:
    """Deploy the build output and return the accessible URL.

    Args:
        build_id: The build session ID
        result: The build result containing output and deliverables

    Returns:
        The deployed URL, or None if deployment failed
    """
    builds_dir = Path(BUILDS_WORK_DIR)
    if not builds_dir.exists():
        logger.warning(f"Builds directory does not exist: {builds_dir}")
        return None

    # Find project directories (exclude hidden and common non-project dirs)
    project_dirs = [
        d for d in builds_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    ]

    if not project_dirs:
        logger.warning("No project directories found in builds folder")
        return None

    # Use the most recently modified directory
    project_dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    project_path = project_dirs[0]

    logger.info(f"Deploying project: {project_path.name}")

    try:
        deployed_url = await deploy.deploy_build(project_path)
        if deployed_url:
            logger.info(f"Deployed to: {deployed_url}")
        return deployed_url
    except Exception as e:
        logger.error(f"Deployment failed: {e}")
        return None


async def _run_with_agent_sdk(
    build_id: str,
    transcript: str,
    model_name: str,
    env_overrides: dict,
) -> dict[str, Any]:
    """Run build using Claude Agent SDK.

    Args:
        build_id: Unique build session ID
        transcript: The build request
        model_name: Selected model name
        env_overrides: Environment variables to set

    Returns:
        Dict with success, output, and deliverables
    """
    # Import here to allow graceful fallback
    from claude_agent_sdk import ClaudeAgentOptions, query

    # Set environment overrides
    original_env = {}
    for key, value in env_overrides.items():
        original_env[key] = os.environ.get(key)
        if value:
            os.environ[key] = value
        elif key in os.environ:
            del os.environ[key]

    try:
        # Load preferences and build prompt
        preferences = load_preferences()
        prompt = build_prompt(transcript, preferences)

        # Configure agent options
        options = ClaudeAgentOptions(
            allowed_tools=ALLOWED_TOOLS,
            permission_mode="bypassPermissions",
            cwd=BUILDS_WORK_DIR,
        )

        # Collect output
        output_parts = []
        deliverables = []
        questions_asked = 0

        # Run the agent
        async for message in query(prompt=prompt, options=options):
            # Check message type by class name (SDK uses typed message classes)
            message_type = type(message).__name__

            if message_type == "AssistantMessage":
                if hasattr(message, "content"):
                    # content is a list of TextBlock objects
                    for block in message.content:
                        if hasattr(block, "text"):
                            output_parts.append(block.text)

            elif message_type == "ResultMessage":
                if hasattr(message, "result") and message.result:
                    output_parts.append(str(message.result))

            # Detect if agent needs input (this is a simplified check)
            if hasattr(message, "content"):
                content_text = ""
                if hasattr(message.content, "__iter__"):
                    for block in message.content:
                        if hasattr(block, "text"):
                            content_text += block.text
                if "?" in content_text and _looks_like_question(content_text):
                    if questions_asked < 1:
                        questions_asked += 1
                        # Ask Omar via Telegram
                        answer = await telegram_qa.ask_omar(
                            question=content_text,
                            build_id=build_id,
                            context=f"Building: {transcript[:100]}",
                        )
                        output_parts.append(f"\nOmar answered: {answer}\n")

        # Extract deliverables from output
        full_output = "\n".join(output_parts)
        deliverables = _extract_deliverables(full_output)

        return {
            "success": True,
            "output": full_output,
            "deliverables": deliverables,
            "model": model_name,
        }

    finally:
        # Restore original environment
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


async def _run_with_cli(
    build_id: str,
    transcript: str,
    model_name: str,
    env_overrides: dict,
) -> dict[str, Any]:
    """Fallback: Run build using Claude CLI subprocess.

    Args:
        build_id: Unique build session ID
        transcript: The build request
        model_name: Selected model name
        env_overrides: Environment variables to set

    Returns:
        Dict with success, output, and deliverables
    """
    import asyncio
    import json

    # Build the prompt
    preferences = load_preferences()
    prompt = build_prompt(transcript, preferences)

    # Prepare environment
    env = os.environ.copy()
    for key, value in env_overrides.items():
        if value:
            env[key] = value
        elif key in env:
            del env[key]

    # Run claude CLI
    cmd = [
        "claude",
        "-p", prompt,
        "--output-format", "json",
        "--dangerously-skip-permissions",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=BUILDS_WORK_DIR,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=600,  # 10 minute timeout
        )

        if proc.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            return {
                "success": False,
                "output": f"CLI failed: {error_msg}",
                "deliverables": [],
                "error": error_msg,
            }

        # Parse JSON output
        output = stdout.decode()
        try:
            result_data = json.loads(output)
            result_text = result_data.get("result", output)
        except json.JSONDecodeError:
            result_text = output

        deliverables = _extract_deliverables(result_text)

        return {
            "success": True,
            "output": result_text,
            "deliverables": deliverables,
            "model": model_name,
        }

    except asyncio.TimeoutError:
        return {
            "success": False,
            "output": "Build timed out after 10 minutes",
            "deliverables": [],
            "error": "timeout",
        }
    except Exception as e:
        return {
            "success": False,
            "output": f"CLI error: {str(e)}",
            "deliverables": [],
            "error": str(e),
        }


def _looks_like_question(content: str) -> bool:
    """Check if content looks like a question needing user input.

    Args:
        content: The message content to check

    Returns:
        True if it looks like a question for the user
    """
    question_patterns = [
        "would you like",
        "should i",
        "do you want",
        "which",
        "what should",
        "please choose",
        "please select",
        "could you clarify",
        "can you specify",
    ]
    content_lower = content.lower()
    return any(pattern in content_lower for pattern in question_patterns)


def _extract_deliverables(output: str) -> list[str]:
    """Extract deliverables (URLs, file paths) from build output.

    Args:
        output: The build output text

    Returns:
        List of deliverable strings
    """
    import re

    deliverables = []

    # Extract URLs
    url_pattern = r'https?://[^\s<>"\')\]]+(?<![.,;:!?])'
    urls = re.findall(url_pattern, output)
    for url in urls:
        # Filter out common non-deliverable URLs
        if not any(skip in url for skip in ["github.com/anthropics", "docs.", "api."]):
            if url not in deliverables:
                deliverables.append(url)

    # Extract file paths (simple heuristic)
    path_patterns = [
        r'Created:\s+([^\s]+\.[a-z]+)',
        r'Deployed to:\s+([^\s]+)',
        r'Available at:\s+([^\s]+)',
    ]
    for pattern in path_patterns:
        matches = re.findall(pattern, output, re.IGNORECASE)
        for match in matches:
            if match not in deliverables:
                deliverables.append(match)

    return deliverables[:10]  # Limit to 10 deliverables
