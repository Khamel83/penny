"""Service router - dispatches to authenticated AI services.

Key principle: Penny never holds API keys for Claude/Anthropic directly.
It dispatches to authenticated CLIs or aggregator APIs.

Available services:
- claude: Claude CLI (Max plan, pre-authenticated)
- gemini: Gemini CLI (Google auth)
- openrouter: OpenRouter API (aggregator, pay-per-use)
- glm: Z.AI GLM-4.7 API (cheap, fast)
"""

import asyncio
import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# CLI paths
CLAUDE_CLI = os.environ.get("PENNY_CLAUDE_CLI", "claude")
GEMINI_CLI = os.environ.get("PENNY_GEMINI_CLI", "gemini")

# API endpoints
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GLM_API_URL = os.environ.get("GLM_API_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions")


class ServiceRouter:
    """Routes requests to appropriate AI services."""

    async def dispatch(
        self,
        service: str,
        prompt: str,
        model: Optional[str] = None,
        timeout: int = 600,
        working_dir: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> dict[str, Any]:
        """Dispatch to a service.

        Args:
            service: 'claude', 'gemini', 'openrouter', 'glm'
            prompt: The prompt to send
            model: Optional model override
            timeout: Timeout in seconds
            working_dir: Working directory for CLI (claude only)
            system_prompt: Optional system prompt

        Returns:
            dict with success, output, service, and metadata
        """
        logger.info(f"Dispatching to {service}" + (f" (model: {model})" if model else ""))

        if service == "claude":
            return await self._dispatch_claude(prompt, model, timeout, working_dir)
        elif service == "gemini":
            return await self._dispatch_gemini(prompt, model, timeout)
        elif service == "openrouter":
            return await self._dispatch_openrouter(prompt, model, timeout, system_prompt)
        elif service == "glm":
            return await self._dispatch_glm(prompt, model, timeout, system_prompt)
        else:
            return {"success": False, "error": f"Unknown service: {service}", "service": service}

    async def _dispatch_claude(
        self,
        prompt: str,
        model: Optional[str],
        timeout: int,
        working_dir: Optional[str],
    ) -> dict[str, Any]:
        """Dispatch to Claude CLI.

        Uses the authenticated claude CLI from Max plan.
        """
        cmd = [CLAUDE_CLI, "-p", prompt, "--output-format", "json"]

        if model:
            cmd.extend(["--model", model])

        # Add --dangerously-skip-permissions for automation
        cmd.append("--dangerously-skip-permissions")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )

            if proc.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(f"Claude CLI error: {error_msg}")
                return {
                    "success": False,
                    "error": error_msg,
                    "service": "claude",
                    "exit_code": proc.returncode,
                }

            output = stdout.decode()

            # Try to parse JSON output
            try:
                data = json.loads(output)
                result_text = data.get("result", output)
            except json.JSONDecodeError:
                result_text = output

            return {
                "success": True,
                "output": result_text,
                "service": "claude",
                "model": model,
            }

        except asyncio.TimeoutError:
            logger.error(f"Claude CLI timeout after {timeout}s")
            return {
                "success": False,
                "error": f"Timeout after {timeout}s",
                "service": "claude",
            }
        except FileNotFoundError:
            logger.error(f"Claude CLI not found at: {CLAUDE_CLI}")
            return {
                "success": False,
                "error": f"Claude CLI not found: {CLAUDE_CLI}",
                "service": "claude",
            }
        except Exception as e:
            logger.error(f"Claude CLI exception: {e}")
            return {
                "success": False,
                "error": str(e),
                "service": "claude",
            }

    async def _dispatch_gemini(
        self,
        prompt: str,
        model: Optional[str],
        timeout: int,
    ) -> dict[str, Any]:
        """Dispatch to Gemini CLI.

        Uses Google-authenticated gemini CLI.
        """
        cmd = [GEMINI_CLI]

        if model:
            cmd.extend(["--model", model])

        try:
            # Gemini CLI reads prompt from stdin
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode()),
                timeout=timeout,
            )

            if proc.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(f"Gemini CLI error: {error_msg}")
                return {
                    "success": False,
                    "error": error_msg,
                    "service": "gemini",
                    "exit_code": proc.returncode,
                }

            return {
                "success": True,
                "output": stdout.decode(),
                "service": "gemini",
                "model": model,
            }

        except asyncio.TimeoutError:
            logger.error(f"Gemini CLI timeout after {timeout}s")
            return {
                "success": False,
                "error": f"Timeout after {timeout}s",
                "service": "gemini",
            }
        except FileNotFoundError:
            logger.error(f"Gemini CLI not found at: {GEMINI_CLI}")
            return {
                "success": False,
                "error": f"Gemini CLI not found: {GEMINI_CLI}",
                "service": "gemini",
            }
        except Exception as e:
            logger.error(f"Gemini CLI exception: {e}")
            return {
                "success": False,
                "error": str(e),
                "service": "gemini",
            }

    async def _dispatch_openrouter(
        self,
        prompt: str,
        model: Optional[str],
        timeout: int,
        system_prompt: Optional[str],
    ) -> dict[str, Any]:
        """Dispatch to OpenRouter API.

        Aggregator API with access to many models.
        """
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            return {
                "success": False,
                "error": "OPENROUTER_API_KEY not set",
                "service": "openrouter",
            }

        # Default model for OpenRouter
        model = model or "google/gemini-2.5-flash-lite"

        try:
            import httpx
        except ImportError:
            return {
                "success": False,
                "error": "httpx not installed",
                "service": "openrouter",
            }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://penny.khamel.com",
                        "X-Title": "Penny Voice Assistant",
                    },
                    json={
                        "model": model,
                        "messages": messages,
                    },
                    timeout=timeout,
                )
                response.raise_for_status()

                data = response.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})

                return {
                    "success": True,
                    "output": content,
                    "service": "openrouter",
                    "model": model,
                    "usage": usage,
                }

        except httpx.TimeoutException:
            return {
                "success": False,
                "error": f"Timeout after {timeout}s",
                "service": "openrouter",
            }
        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {e.response.text}",
                "service": "openrouter",
            }
        except Exception as e:
            logger.error(f"OpenRouter exception: {e}")
            return {
                "success": False,
                "error": str(e),
                "service": "openrouter",
            }

    async def _dispatch_glm(
        self,
        prompt: str,
        model: Optional[str],
        timeout: int,
        system_prompt: Optional[str],
    ) -> dict[str, Any]:
        """Dispatch to Z.AI GLM API.

        Cheap, fast model for simple tasks.
        """
        api_key = os.environ.get("GLM_API_KEY") or os.environ.get("ZHIPU_API_KEY")
        if not api_key:
            return {
                "success": False,
                "error": "GLM_API_KEY not set",
                "service": "glm",
            }

        model = model or "glm-4-flash"

        try:
            import httpx
        except ImportError:
            return {
                "success": False,
                "error": "httpx not installed",
                "service": "glm",
            }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    GLM_API_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": messages,
                    },
                    timeout=timeout,
                )
                response.raise_for_status()

                data = response.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})

                return {
                    "success": True,
                    "output": content,
                    "service": "glm",
                    "model": model,
                    "usage": usage,
                }

        except httpx.TimeoutException:
            return {
                "success": False,
                "error": f"Timeout after {timeout}s",
                "service": "glm",
            }
        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {e.response.text}",
                "service": "glm",
            }
        except Exception as e:
            logger.error(f"GLM exception: {e}")
            return {
                "success": False,
                "error": str(e),
                "service": "glm",
            }


# Singleton instance
service_router = ServiceRouter()


async def dispatch(
    service: str,
    prompt: str,
    **kwargs,
) -> dict[str, Any]:
    """Convenience function to dispatch using singleton router."""
    return await service_router.dispatch(service, prompt, **kwargs)
