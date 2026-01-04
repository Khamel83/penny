"""Background task orchestrator loop.

The core loop that runs cheap probes while the human is away,
accumulates findings, and escalates to expensive reasoning when needed.
"""

import asyncio
import logging
import os
from typing import Optional

from .. import database
from .probes import run_probes, calculate_confidence

logger = logging.getLogger(__name__)

# Configuration
POLL_INTERVAL = int(os.environ.get("PENNY_POLL_INTERVAL", "30"))
HIGH_CONFIDENCE_THRESHOLD = float(os.environ.get("PENNY_HIGH_CONFIDENCE", "0.8"))


class BackgroundOrchestrator:
    """Runs cheap probes while human is away, escalates when ready."""

    def __init__(self, poll_interval: int = POLL_INTERVAL):
        self.poll_interval = poll_interval
        self.running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the background orchestrator loop."""
        if self.running:
            logger.warning("Orchestrator already running")
            return

        self.running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Background orchestrator started (poll interval: {self.poll_interval}s)")

    async def stop(self):
        """Stop the background orchestrator gracefully."""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Background orchestrator stopped")

    async def _run_loop(self):
        """Main loop: poll for pending tasks, run probes, escalate when ready."""
        while self.running:
            try:
                # Get pending tasks
                tasks = await database.get_pending_background_tasks(limit=5)

                for task in tasks:
                    await self._process_task(task)

                # Check for tasks ready to escalate
                ready_tasks = await database.get_tasks_ready_for_escalation(
                    confidence_threshold=HIGH_CONFIDENCE_THRESHOLD
                )
                for task in ready_tasks:
                    await self._escalate_task(task)

            except Exception as e:
                logger.error(f"Orchestrator loop error: {e}", exc_info=True)

            await asyncio.sleep(self.poll_interval)

    async def _process_task(self, task: dict):
        """Run appropriate probes for a task."""
        task_id = task["id"]
        logger.info(f"Processing task {task_id}: {task['task_type']}")

        # Mark as running
        await database.update_task_status(task_id, "running")

        try:
            input_data = task.get("input_data", {})

            # Run cheap probes
            probe_results = await run_probes(input_data)

            # Append findings
            for result in probe_results:
                await database.append_finding(task_id, result)

            # Get updated task with all findings
            updated_task = await database.get_background_task(task_id)
            if not updated_task:
                return

            # Calculate aggregate confidence
            all_findings = updated_task.get("findings", [])
            confidence = calculate_confidence(all_findings)

            # Check if all probes failed (all have errors, no useful findings)
            all_failed = all(
                result.get("error") is not None or result.get("confidence", 0) == 0
                for result in probe_results
            ) if probe_results else True

            # Determine next status
            if confidence >= HIGH_CONFIDENCE_THRESHOLD:
                # Ready for escalation - will be picked up in next loop
                await database.update_task_status(
                    task_id,
                    "pending",
                    confidence=confidence,
                )
                logger.info(f"Task {task_id} ready for escalation (confidence: {confidence:.2f})")
            elif all_failed:
                # All probes failed - increment retry count
                updated = await database.increment_task_retry(task_id)
                retry_count = updated.get("retry_count", 0) if updated else 0
                max_retries = updated.get("max_retries", 3) if updated else 3

                if retry_count >= max_retries:
                    # Max retries reached - escalate anyway with low confidence
                    # (Let the human decide what to do)
                    await database.update_task_status(
                        task_id,
                        "pending",
                        confidence=confidence,
                    )
                    logger.warning(f"Task {task_id} max retries reached, escalating with low confidence")
                else:
                    # Keep as pending for retry
                    await database.update_task_status(
                        task_id,
                        "pending",
                        confidence=confidence,
                    )
                    logger.info(f"Task {task_id} probes failed, retry {retry_count}/{max_retries}")
            else:
                # Some probes succeeded, keep accumulating
                await database.update_task_status(
                    task_id,
                    "pending",
                    confidence=confidence,
                )
                logger.info(f"Task {task_id} accumulating (confidence: {confidence:.2f})")

        except Exception as e:
            logger.error(f"Error processing task {task_id}: {e}", exc_info=True)

            # Increment retry count
            updated = await database.increment_task_retry(task_id)
            if updated and updated.get("retry_count", 0) >= updated.get("max_retries", 3):
                await database.update_task_status(
                    task_id,
                    "failed",
                    error_message=str(e),
                )
                logger.error(f"Task {task_id} failed after max retries")
            else:
                # Schedule retry in 60 seconds
                from datetime import datetime, timedelta
                next_run = (datetime.utcnow() + timedelta(seconds=60)).isoformat()
                await database.increment_task_retry(task_id, next_run_at=next_run)

    async def _escalate_task(self, task: dict):
        """Escalate task to expensive reasoning with accumulated findings."""
        task_id = task["id"]
        logger.info(f"Escalating task {task_id}")

        try:
            # Import here to avoid circular imports
            from .escalation import evaluate_and_escalate

            result = await evaluate_and_escalate(task)
            logger.info(f"Escalation result for {task_id}: {result.get('action')}")

        except ImportError:
            # Escalation module not yet implemented
            logger.warning("Escalation module not available, marking task complete")
            await database.update_task_status(task_id, "completed")

        except Exception as e:
            logger.error(f"Error escalating task {task_id}: {e}", exc_info=True)
            await database.update_task_status(
                task_id,
                "failed",
                error_message=f"Escalation error: {e}",
            )


# Singleton instance for easy access
_orchestrator: Optional[BackgroundOrchestrator] = None


def get_orchestrator() -> BackgroundOrchestrator:
    """Get or create the singleton orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = BackgroundOrchestrator()
    return _orchestrator
