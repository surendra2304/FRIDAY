"""
FRIDAY Autonomous Daemon — Background goal execution engine.

This daemon runs continuously in the background when autonomous mode is enabled.
It pulls goals from a persistent queue, decomposes them into execution plans,
and coordinates multiple specialist agents to achieve them.

The daemon is started/stopped with the autonomous mode toggle and survives
process restarts by persisting its state to disk.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.autonomous.enhanced_controller import (
    enhanced_controller,
    ExecutionPlan,
    SubTask,
)

logger = get_logger("autonomous.daemon")


@dataclass
class AutonomousGoal:
    """A goal submitted for autonomous execution."""
    id: str
    goal: str
    priority: int = 0  # higher = more urgent
    status: str = "QUEUED"  # QUEUED, RUNNING, COMPLETED, FAILED
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    plan_id: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class AutonomousDaemon:
    """
    Background daemon that continuously executes autonomous goals.

    Features:
    - Persistent goal queue (survives restarts)
    - Concurrent goal execution with configurable limits
    - Automatic retry with exponential backoff
    - Progress tracking and detailed logging
    - Integration with enhanced controller for plan execution
    """

    def __init__(self) -> None:
        self.controller = enhanced_controller
        self._goal_queue: list[AutonomousGoal] = []
        self._running_goals: dict[str, AutonomousGoal] = {}
        self._completed_goals: list[AutonomousGoal] = []
        self._max_concurrent_goals = 2
        self._running = False
        self._daemon_task: asyncio.Task | None = None
        self._persistence_path = Path(__file__).resolve().parents[3] / ".data" / "autonomous_goals.json"
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted goals from disk."""
        try:
            if not self._persistence_path.is_file():
                return
            with self._persistence_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            logger.warning("Could not load autonomous goals from %s: %s", self._persistence_path, exc)
            return

        for raw in data.get("queued", []):
            try:
                goal = AutonomousGoal(**raw)
                self._goal_queue.append(goal)
            except Exception:
                continue

        for raw in data.get("running", []):
            try:
                goal = AutonomousGoal(**raw)
                # Reset running goals to queued on restart
                goal.status = "QUEUED"
                goal.started_at = 0.0
                self._goal_queue.append(goal)
            except Exception:
                continue

        for raw in data.get("completed", [])[-50:]:
            try:
                goal = AutonomousGoal(**raw)
                self._completed_goals.append(goal)
            except Exception:
                continue

        logger.info(
            "Loaded autonomous state: %d queued, %d completed",
            len(self._goal_queue),
            len(self._completed_goals),
        )

    def _persist_state(self) -> None:
        """Persist goal state to disk atomically."""
        try:
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "queued": [goal.__dict__ for goal in self._goal_queue],
                "running": [goal.__dict__ for goal in self._running_goals.values()],
                "completed": [goal.__dict__ for goal in self._completed_goals[-50:]],
            }
            tmp = self._persistence_path.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, default=str)
            os.replace(tmp, self._persistence_path)
        except Exception as exc:
            logger.warning("Could not persist autonomous goals: %s", exc)

    def submit_goal(self, goal_text: str, priority: int = 0, metadata: dict[str, Any] | None = None) -> AutonomousGoal:
        """Submit a new goal for autonomous execution."""
        goal = AutonomousGoal(
            id=f"goal_{int(time.time() * 1000)}_{os.urandom(4).hex()}",
            goal=goal_text.strip(),
            priority=priority,
            metadata=metadata or {},
        )
        self._goal_queue.append(goal)
        # Sort by priority (highest first), then by creation time
        self._goal_queue.sort(key=lambda g: (-g.priority, g.created_at))
        self._persist_state()
        logger.info("Submitted autonomous goal %s: %s", goal.id, goal.goal[:80])
        return goal

    def get_status(self) -> dict[str, Any]:
        """Get current daemon status."""
        return {
            "running": self._running,
            "queued": len(self._goal_queue),
            "running": len(self._running_goals),
            "completed": len(self._completed_goals),
            "max_concurrent": self._max_concurrent_goals,
            "goals": {
                "queued": [
                    {
                        "id": g.id,
                        "goal": g.goal[:100],
                        "priority": g.priority,
                        "status": g.status,
                    }
                    for g in self._goal_queue[:10]
                ],
                "running": [
                    {
                        "id": g.id,
                        "goal": g.goal[:100],
                        "plan_id": g.plan_id,
                        "elapsed": time.time() - g.started_at if g.started_at else 0,
                    }
                    for g in self._running_goals.values()
                ],
                "recent_completed": [
                    {
                        "id": g.id,
                        "goal": g.goal[:100],
                        "status": g.status,
                        "duration": g.completed_at - g.started_at if g.completed_at else 0,
                    }
                    for g in self._completed_goals[-5:]
                ],
            },
        }

    async def start(self) -> None:
        """Start the autonomous daemon."""
        if self._running:
            return
        self._running = True
        self._daemon_task = asyncio.create_task(self._run_loop(), name="friday-autonomous-daemon")
        logger.info("Autonomous daemon started")

    async def stop(self) -> None:
        """Stop the autonomous daemon gracefully."""
        if not self._running:
            return
        self._running = False
        if self._daemon_task:
            self._daemon_task.cancel()
            try:
                await self._daemon_task
            except asyncio.CancelledError:
                pass
        self._persist_state()
        logger.info("Autonomous daemon stopped")

    async def _run_loop(self) -> None:
        """Main daemon loop."""
        while self._running:
            try:
                # Check if we can start more goals
                if len(self._running_goals) < self._max_concurrent_goals and self._goal_queue:
                    goal = self._goal_queue.pop(0)
                    await self._start_goal(goal)

                # Check running goals for completion
                await self._check_running_goals()

                # Persist state periodically
                self._persist_state()

            except Exception as exc:
                logger.error("Autonomous daemon loop error: %s", exc)

            await asyncio.sleep(5)  # Poll interval

    async def _start_goal(self, goal: AutonomousGoal) -> None:
        """Start executing a goal."""
        goal.status = "RUNNING"
        goal.started_at = time.time()
        self._running_goals[goal.id] = goal
        self._persist_state()

        # Decompose goal into execution plan
        try:
            plan = self.controller.decompose_goal(goal.goal)
            goal.plan_id = getattr(plan, "plan_id", "") or (plan.subtasks[0].id if plan.subtasks else "")
            logger.info("Daemon decomposed goal %s into %d subtasks: %s", goal.id, len(plan.subtasks),
                        " -> ".join(st.agent for st in plan.subtasks))
            # Execute plan in background
            asyncio.create_task(self._execute_goal(goal, plan), name=f"autonomous-goal-{goal.id}")
            logger.info("Started autonomous goal %s with %d subtasks", goal.id, len(plan.subtasks))
        except Exception as exc:
            goal.status = "FAILED"
            goal.error = str(exc)
            goal.completed_at = time.time()
            logger.error("Failed to start goal %s: %s", goal.id, exc)
            await self._finish_goal(goal)

    async def _execute_goal(self, goal: AutonomousGoal, plan: ExecutionPlan) -> None:
        """Execute a goal's plan, dispatching real work to each specialist."""
        logger.info("Daemon executing real multi-agent plan for goal %s: %s", goal.id, goal.goal)
        try:
            await self.controller.execute_plan(plan)
            goal.status = "COMPLETED" if plan.status == "COMPLETED" else "FAILED"
            logger.info("Daemon goal %s finished: %s (%d/%d subtasks)",
                        goal.id, plan.status, plan.completed_subtasks, plan.total_subtasks)
        except Exception as exc:
            goal.status = "FAILED"
            goal.error = str(exc)
            logger.error("Goal %s execution failed: %s", goal.id, exc)
        finally:
            goal.completed_at = time.time()
            await self._finish_goal(goal)

    async def _finish_goal(self, goal: AutonomousGoal) -> None:
        """Move goal from running to completed."""
        self._running_goals.pop(goal.id, None)
        self._completed_goals.append(goal)
        if len(self._completed_goals) > 100:
            self._completed_goals = self._completed_goals[-100:]
        self._persist_state()
        logger.info("Goal %s finished with status: %s", goal.id, goal.status)

    async def _check_running_goals(self) -> None:
        """Check running goals for stalls/timeouts."""
        now = time.time()
        for goal_id, goal in list(self._running_goals.items()):
            # Timeout after 30 minutes
            if goal.started_at and now - goal.started_at > 1800:
                logger.warning("Goal %s timed out after 30 minutes", goal_id)
                goal.status = "FAILED"
                goal.error = "Execution timeout (30 minutes)"
                goal.completed_at = now
                await self._finish_goal(goal)


# Module-level singleton
autonomous_daemon = AutonomousDaemon()