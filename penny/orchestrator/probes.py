"""Cheap probe implementations for background tasks.

Probes are lightweight information-gathering operations that run
while the human is away. They accumulate findings without spending
expensive reasoning tokens.

Key principle: "Failures are informative."
A grep that finds nothing tells us where the answer ISN'T.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default timeout for probes (seconds)
PROBE_TIMEOUT = int(os.environ.get("PENNY_PROBE_TIMEOUT", "30"))


async def run_probes(input_data: dict) -> list[dict]:
    """Run all applicable cheap probes based on input data.

    Args:
        input_data: Task input containing query, search terms, paths, etc.

    Returns:
        List of finding dicts with probe results and confidence scores.
    """
    results = []
    probe_types = determine_probes(input_data)

    for probe_type in probe_types:
        try:
            if probe_type == "grep":
                result = await probe_grep(input_data)
            elif probe_type == "file_read":
                result = await probe_file_read(input_data)
            elif probe_type == "api_check":
                result = await probe_api_check(input_data)
            elif probe_type == "atlas":
                result = await probe_atlas(input_data)
            elif probe_type == "command":
                result = await probe_command(input_data)
            else:
                continue

            if result:
                results.append(result)

        except Exception as e:
            logger.warning(f"Probe {probe_type} failed: {e}")
            results.append({
                "probe": probe_type,
                "error": str(e),
                "confidence": 0.0,
            })

    return results


def determine_probes(input_data: dict) -> list[str]:
    """Determine which probes to run based on input data."""
    probes = []

    # Always try Atlas if there's a query
    if input_data.get("query") or input_data.get("text"):
        probes.append("atlas")

    # Grep if there's a search pattern
    if input_data.get("search_pattern") or input_data.get("code_search"):
        probes.append("grep")

    # File read if specific paths are mentioned
    if input_data.get("file_paths") or input_data.get("read_files"):
        probes.append("file_read")

    # API check if there are URLs to verify
    if input_data.get("check_urls") or input_data.get("api_endpoints"):
        probes.append("api_check")

    # Command probe if there's a diagnostic command
    if input_data.get("command") or input_data.get("diagnostic"):
        probes.append("command")

    return probes


async def probe_grep(input_data: dict) -> Optional[dict]:
    """Search codebase for patterns using ripgrep.

    This is a cheap probe - just runs rg and counts matches.
    """
    pattern = input_data.get("search_pattern") or input_data.get("code_search")
    search_path = input_data.get("search_path", ".")

    if not pattern:
        return None

    try:
        # Use ripgrep for fast searching
        cmd = ["rg", "-c", "--no-heading", pattern, search_path]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=PROBE_TIMEOUT,
        )

        if proc.returncode not in (0, 1):  # 1 means no matches, which is ok
            return {
                "probe": "grep",
                "pattern": pattern,
                "error": stderr.decode().strip(),
                "confidence": 0.0,
            }

        # Parse output to count matches per file
        matches = []
        total_matches = 0
        for line in stdout.decode().strip().split("\n"):
            if ":" in line and line:
                file_path, count = line.rsplit(":", 1)
                count = int(count)
                matches.append({"file": file_path, "count": count})
                total_matches += count

        # Confidence based on number of matches
        # Few matches = focused, high confidence
        # Many matches = broad, lower confidence
        if total_matches == 0:
            confidence = 0.1  # No matches is still informative
        elif total_matches <= 5:
            confidence = 0.9  # Very focused
        elif total_matches <= 20:
            confidence = 0.7  # Reasonable scope
        else:
            confidence = 0.5  # Broad, needs refinement

        return {
            "probe": "grep",
            "pattern": pattern,
            "total_matches": total_matches,
            "files": matches[:10],  # Top 10 files
            "confidence": confidence,
        }

    except asyncio.TimeoutError:
        return {
            "probe": "grep",
            "pattern": pattern,
            "error": f"Timeout after {PROBE_TIMEOUT}s",
            "confidence": 0.0,
        }
    except FileNotFoundError:
        # rg not installed, try grep
        return await _fallback_grep(pattern, search_path)


async def _fallback_grep(pattern: str, search_path: str) -> Optional[dict]:
    """Fallback to standard grep if ripgrep not available."""
    try:
        cmd = ["grep", "-r", "-c", pattern, search_path]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, _ = await asyncio.wait_for(
            proc.communicate(),
            timeout=PROBE_TIMEOUT,
        )

        matches = []
        total_matches = 0
        for line in stdout.decode().strip().split("\n"):
            if ":" in line and line:
                parts = line.rsplit(":", 1)
                if len(parts) == 2:
                    file_path, count = parts
                    try:
                        count = int(count)
                        matches.append({"file": file_path, "count": count})
                        total_matches += count
                    except ValueError:
                        pass

        confidence = 0.5 if total_matches > 0 else 0.1

        return {
            "probe": "grep",
            "pattern": pattern,
            "total_matches": total_matches,
            "files": matches[:10],
            "confidence": confidence,
            "fallback": True,
        }

    except Exception as e:
        return {
            "probe": "grep",
            "pattern": pattern,
            "error": str(e),
            "confidence": 0.0,
        }


async def probe_file_read(input_data: dict) -> Optional[dict]:
    """Read specific files to gather context.

    Lightweight read - just checks if files exist and gets sizes/summaries.
    """
    file_paths = input_data.get("file_paths") or input_data.get("read_files", [])

    if not file_paths:
        return None

    if isinstance(file_paths, str):
        file_paths = [file_paths]

    results = []
    found_count = 0

    for path_str in file_paths[:10]:  # Limit to 10 files
        path = Path(path_str)
        try:
            if path.exists():
                stat = path.stat()
                # Read first 500 chars as preview
                preview = ""
                if path.is_file() and stat.st_size < 100000:  # Only small files
                    try:
                        preview = path.read_text()[:500]
                    except Exception:
                        preview = "[binary or unreadable]"

                results.append({
                    "path": str(path),
                    "exists": True,
                    "size": stat.st_size,
                    "preview": preview,
                })
                found_count += 1
            else:
                results.append({
                    "path": str(path),
                    "exists": False,
                })
        except Exception as e:
            results.append({
                "path": str(path),
                "error": str(e),
            })

    confidence = found_count / len(file_paths) if file_paths else 0.0

    return {
        "probe": "file_read",
        "files_checked": len(file_paths),
        "files_found": found_count,
        "results": results,
        "confidence": confidence,
    }


async def probe_api_check(input_data: dict) -> Optional[dict]:
    """Check API endpoints for availability.

    Simple health checks - no expensive operations.
    """
    urls = input_data.get("check_urls") or input_data.get("api_endpoints", [])

    if not urls:
        return None

    if isinstance(urls, str):
        urls = [urls]

    try:
        import httpx
    except ImportError:
        return {
            "probe": "api_check",
            "error": "httpx not installed",
            "confidence": 0.0,
        }

    results = []
    healthy_count = 0

    async with httpx.AsyncClient(timeout=10.0) as client:
        for url in urls[:5]:  # Limit to 5 URLs
            try:
                response = await client.get(url)
                is_healthy = response.status_code < 400
                results.append({
                    "url": url,
                    "status_code": response.status_code,
                    "healthy": is_healthy,
                })
                if is_healthy:
                    healthy_count += 1
            except Exception as e:
                results.append({
                    "url": url,
                    "error": str(e),
                    "healthy": False,
                })

    confidence = healthy_count / len(urls) if urls else 0.0

    return {
        "probe": "api_check",
        "urls_checked": len(urls),
        "healthy_count": healthy_count,
        "results": results,
        "confidence": confidence,
    }


async def probe_atlas(input_data: dict) -> Optional[dict]:
    """Query Atlas knowledge base for relevant context.

    "What do I already know about this?"
    """
    query = input_data.get("query") or input_data.get("text")

    if not query:
        return None

    try:
        # Try to import Atlas integration
        from ..integrations import atlas

        result = await atlas.search_atlas(query, limit=5)

        if result.get("success"):
            results = result.get("results", [])
            total = result.get("total", len(results))

            # Confidence based on relevance of results
            confidence = min(total / 5, 1.0) if total > 0 else 0.1

            return {
                "probe": "atlas",
                "query": query[:100],
                "results_count": total,
                "results": results[:5],
                "confidence": confidence,
            }
        else:
            return {
                "probe": "atlas",
                "query": query[:100],
                "error": result.get("error", "Unknown error"),
                "confidence": 0.0,
            }

    except ImportError:
        return {
            "probe": "atlas",
            "query": query[:100],
            "error": "Atlas integration not available",
            "confidence": 0.0,
        }
    except Exception as e:
        return {
            "probe": "atlas",
            "query": query[:100],
            "error": str(e),
            "confidence": 0.0,
        }


async def probe_command(input_data: dict) -> Optional[dict]:
    """Run a diagnostic command.

    Only allows safe, read-only commands.
    """
    command = input_data.get("command") or input_data.get("diagnostic")

    if not command:
        return None

    # Whitelist of safe commands
    safe_prefixes = [
        "ls", "cat", "head", "tail", "wc", "find", "which", "type",
        "git status", "git log", "git diff", "git branch",
        "docker ps", "docker images",
        "pip list", "pip show",
        "python --version", "node --version",
        "curl -I",  # HEAD request only
    ]

    is_safe = any(command.strip().startswith(prefix) for prefix in safe_prefixes)

    if not is_safe:
        return {
            "probe": "command",
            "command": command,
            "error": "Command not in safe whitelist",
            "confidence": 0.0,
        }

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=PROBE_TIMEOUT,
        )

        output = stdout.decode().strip()
        error = stderr.decode().strip()

        success = proc.returncode == 0
        confidence = 0.8 if success else 0.3

        return {
            "probe": "command",
            "command": command,
            "exit_code": proc.returncode,
            "output": output[:1000],  # Limit output
            "error": error[:500] if error else None,
            "success": success,
            "confidence": confidence,
        }

    except asyncio.TimeoutError:
        return {
            "probe": "command",
            "command": command,
            "error": f"Timeout after {PROBE_TIMEOUT}s",
            "confidence": 0.0,
        }
    except Exception as e:
        return {
            "probe": "command",
            "command": command,
            "error": str(e),
            "confidence": 0.0,
        }


def calculate_confidence(findings: list[dict]) -> float:
    """Calculate aggregate confidence from multiple findings.

    Uses weighted average with higher weight for successful probes.
    """
    if not findings:
        return 0.0

    total_weight = 0.0
    weighted_sum = 0.0

    for finding in findings:
        confidence = finding.get("confidence", 0.0)
        has_error = "error" in finding

        # Weight successful probes higher
        weight = 0.5 if has_error else 1.0

        weighted_sum += confidence * weight
        total_weight += weight

    return weighted_sum / total_weight if total_weight > 0 else 0.0
