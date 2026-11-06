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
import re
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
from friday.api.response_synthesizer import synthesize_answer

logger = get_logger("autonomous.daemon")

_AGENT_NAMES = {
    "inference": "Inference",
    "stratex": "Stratex",
    "intelx": "IntelX",
    "futuris": "Futuris",
    "cortex": "Cortex",
    "forge": "Forge",
    "sentinel": "Sentinel",
    "memora": "Memora",
    "vyralx": "VyralX",
}

# One honest verb per specialist so a finished goal reads like a report from a
# colleague instead of a table of status tokens.
_STEP_VERBS = {
    "intelx": "took the research step",
    "memora": "wrote the findings into persistent memory",
    "cortex": "checked the public site",
    "stratex": "reviewed the trading book",
    "forge": "worked the code change",
    "sentinel": "ran the security review",
    "vyralx": "handled the video work",
    "futuris": "ran the forecast",
    "inference": "worked through the reasoning",
}

_MACHINE_TAG_RE = re.compile(r"\[[A-Z][A-Z0-9 _-]{2,}:[^\]]*\]")
_REFERENCE_RE = re.compile(r"\b(?:goal|plan|task|st|trace|run)_[0-9a-zA-Z_-]{4,}\b")
_RESULT_KEYS = ("spoken_summary", "summary", "message", "text_response", "reply", "detail", "stage", "output")


def _clean_text(value: Any, limit: int = 240) -> str:
    """Strip machine tags, goal references and raw JSON from owner-facing text."""
    text = str(value or "")
    if not text:
        return ""
    text = _MACHINE_TAG_RE.sub(" ", text)
    text = _REFERENCE_RE.sub(" ", text)
    text = re.sub(r"\s+([.,;:])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip(" -–—:;\t\r\n")
    if not text or text[0] in "{[<":
        return ""
    text = re.sub(r"^(status|state)\s*[:=]\s*\w+\s*", "", text, flags=re.IGNORECASE)
    if len(text) > limit:
        cut = text[:limit]
        stop = max(cut.rfind(". "), cut.rfind("; "))
        text = (cut[: stop + 1] if stop > limit * 0.45 else cut.rstrip(" ,;") + "…")
    return text.strip()


def _human_result(result: Any, limit: int = 200) -> str:
    """Reduce an agent envelope to one sentence the owner can read."""
    if result is None:
        return ""
    if isinstance(result, str):
        return _clean_text(result, limit)
    if isinstance(result, dict):
        for key in _RESULT_KEYS:
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return _clean_text(value, limit)
        nested = result.get("result")
        if nested is not None and nested is not result:
            text = _human_result(nested, limit)
            if text:
                return text
        status = str(result.get("status") or "").strip().lower()
        if status in {"completed", "complete", "ok", "success", "stored", "saved", "done"}:
            return "It confirmed the work was done."
        return ""
    return _clean_text(result, limit)


def _with_period(text: str) -> str:
    """End a fragment with punctuation so joined prose reads cleanly."""
    cleaned = str(text or "").strip()
    if cleaned and cleaned[-1] not in ".!?…":
        cleaned += "."
    return cleaned


def _short_action(description: str, limit: int = 88) -> str:
    """Turn a planner instruction into a short human action label."""
    text = str(description or "").split(":")[0]
    text = re.sub(r"\s+", " ", text).strip().rstrip(".")
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


@dataclass
class AutonomousGoal:
    """A goal submitted for autonomous execution."""
    id: str
    goal: str
    priority: int = 0  # higher = more urgent
    status: str = "QUEUED"  # QUEUED, RUNNING, COMPLETED, FAILED, PARTIAL
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    plan_id: str = ""
    error: str = ""
    summary: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
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
        self._live_plans: dict[str, ExecutionPlan] = {}
        self._max_concurrent_goals = 2
        self._running = False
        self._daemon_task: asyncio.Task | None = None
        self._wake = asyncio.Event()
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

    @property
    def is_running(self) -> bool:
        """True while the background worker loop is alive."""
        return self._running

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
        self._wake.set()
        logger.info("Submitted autonomous goal %s: %s", goal.id, goal.goal[:80])
        return goal

    def _step_payload(self, subtask: SubTask) -> dict[str, Any]:
        """One planned action, with the agent, its state and its real result."""
        duration = 0.0
        if subtask.completed_at and subtask.started_at:
            duration = round(subtask.completed_at - subtask.started_at, 2)
        agent = (subtask.agent or "").strip().lower()
        return {
            "id": subtask.id,
            "agent": agent,
            "agent_name": _AGENT_NAMES.get(agent, agent.upper() or "FRIDAY"),
            "action": _short_action(subtask.description),
            "status": (subtask.status or "PENDING").lower(),
            "depends_on": list(subtask.dependencies),
            "duration": duration,
            "result": _human_result(subtask.result) if subtask.status == "COMPLETED" else "",
            "error": _clean_text(subtask.error, 140) if subtask.status == "FAILED" else "",
        }

    def _build_summary(self, goal: AutonomousGoal, plan: ExecutionPlan, duration: float) -> str:
        """Turn a finished plan into a short, honest, human-readable report."""
        subtasks = list(plan.subtasks)
        total = len(subtasks)
        completed = sum(1 for st in subtasks if st.status == "COMPLETED")
        failed = sum(1 for st in subtasks if st.status == "FAILED")

        if total == 0:
            return (
                "I could not turn that into a plan, so no agent was asked to do anything. "
                "Try rephrasing it as a concrete task, for example: research a topic, store the findings, and report back."
            )

        seconds = max(0.0, duration)
        if completed == total:
            opener = f"Done. All {total} steps finished in {seconds:.1f} seconds."
        elif completed:
            opener = (
                f"Partly done. {completed} of {total} steps finished in {seconds:.1f} seconds"
                + (f"; {failed} failed." if failed else ".")
            )
        else:
            opener = f"That did not go through. None of the {total} steps completed."

        sentences = [opener]
        for st in subtasks:
            agent = (st.agent or "").strip().lower()
            name = _AGENT_NAMES.get(agent, agent.upper() or "FRIDAY")
            verb = _STEP_VERBS.get(agent, "handled its step")
            if st.status == "COMPLETED":
                line = f"{name} {verb}."
                result = _human_result(st.result, 180)
                if result and not result.lower().startswith(("it confirmed", "completed", "ok", "success")):
                    line += f" {_with_period(result)}"
                sentences.append(line)
            elif st.status == "FAILED":
                reason = _clean_text(st.error, 120)
                sentences.append(
                    f"{name} could not finish that step" + (f": {reason}." if reason else ".")
                )

        if completed == total and total > 1 and any(st.dependencies for st in subtasks):
            sentences.append("Each step handed what it found to the next agent as the work moved forward.")

        return " ".join(sentences)

    def _goal_payload(self, goal: AutonomousGoal, step_limit: int = 12) -> dict[str, Any]:
        """Serialise a goal with its live pipeline so the dashboard can show the work."""
        plan = self._live_plans.get(goal.id)
        if plan is not None:
            steps = [self._step_payload(st) for st in plan.subtasks]
        else:
            steps = list(goal.steps)

        summary = goal.summary
        if not summary and plan is not None and goal.status in ("QUEUED", "RUNNING"):
            done = sum(1 for st in plan.subtasks if st.status == "COMPLETED")
            total = len(plan.subtasks)
            summary = f"Working on it — {done} of {total} steps finished so far."
        if not summary and goal.status == "QUEUED":
            summary = "Queued. I will start as soon as a worker slot is free."
        if not summary and goal.status in ("COMPLETED", "PARTIAL", "FAILED"):
            summary = (
                "That finished, but I don't have a readable report for it. "
                "The flow view shows which agents ran."
            )

        duration = 0.0
        if goal.completed_at and goal.started_at:
            duration = round(goal.completed_at - goal.started_at, 2)
        elif goal.started_at:
            duration = round(time.time() - goal.started_at, 2)

        return {
            "id": goal.id,
            "goal": goal.goal[:160],
            "status": goal.status,
            "summary": summary,
            "steps": steps[:step_limit],
            "duration": duration,
            "created_at": goal.created_at,
            "started_at": goal.started_at,
            "completed_at": goal.completed_at,
            "error": goal.error,
            "plan_id": goal.plan_id,
        }

    def get_goal(self, goal_id: str) -> dict[str, Any] | None:
        """Look up one goal by reference across the whole lifecycle."""
        candidates = list(self._goal_queue) + list(self._running_goals.values())
        for goal in candidates:
            if goal.id == goal_id:
                return self._goal_payload(goal)
        for goal in reversed(self._completed_goals):
            if goal.id == goal_id:
                return self._goal_payload(goal)
        return None

    def get_status(self) -> dict[str, Any]:
        """Get current daemon status."""
        return {
            "daemon_running": self._running,
            "queued": len(self._goal_queue),
            "running": len(self._running_goals),
            "completed": len(self._completed_goals),
            "max_concurrent": self._max_concurrent_goals,
            "goals": {
                "queued": [self._goal_payload(g) for g in self._goal_queue[:10]],
                "running": [self._goal_payload(g) for g in self._running_goals.values()],
                "recent_completed": [self._goal_payload(g) for g in self._completed_goals[-5:]],
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

            # Wake immediately when a goal is submitted; otherwise poll every
            # five seconds. This removes the dead pause between "send" and the
            # first agent step appearing on the dashboard.
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
            finally:
                self._wake.clear()

    async def _start_goal(self, goal: AutonomousGoal) -> None:
        """Start executing a goal."""
        goal.status = "RUNNING"
        goal.started_at = time.time()
        self._running_goals[goal.id] = goal
        self._persist_state()

        # Decompose goal into execution plan
        try:
            planner = getattr(self.controller, "plan_goal", None)
            if callable(planner):
                plan = await planner(goal.goal)
            else:
                # Compatibility for small test doubles and older controller
                # implementations that only expose the deterministic planner.
                plan = self.controller.decompose_goal(goal.goal)
            goal.plan_id = getattr(plan, "plan_id", "") or (plan.subtasks[0].id if plan.subtasks else "")
            goal.steps = [self._step_payload(st) for st in plan.subtasks]
            self._live_plans[goal.id] = plan
            logger.info("Daemon decomposed goal %s into %d subtasks: %s", goal.id, len(plan.subtasks),
                        " -> ".join(st.agent for st in plan.subtasks))
            # Execute plan in background
            asyncio.create_task(self._execute_goal(goal, plan), name=f"autonomous-goal-{goal.id}")
            logger.info("Started autonomous goal %s with %d subtasks", goal.id, len(plan.subtasks))
        except Exception as exc:
            goal.status = "FAILED"
            goal.error = str(exc)
            goal.completed_at = time.time()
            goal.summary = (
                "I could not put a plan together for that, so no agent ran. "
                "Try describing the task in one clear sentence."
            )
            logger.error("Failed to start goal %s: %s", goal.id, exc)
            await self._finish_goal(goal)

    async def _execute_goal(self, goal: AutonomousGoal, plan: ExecutionPlan) -> None:
        """Execute a goal's plan, dispatching real work to each specialist."""
        logger.info("Daemon executing real multi-agent plan for goal %s: %s", goal.id, goal.goal)
        # Status is only published after the answer exists: flipping to COMPLETED
        # before synthesis made dashboards read a finished goal with an empty
        # summary and display a progress line as the final answer.
        final_status = "FAILED"
        final_error = ""
        try:
            if not plan.subtasks:
                final_error = "Planner produced no agent tasks for this goal"
                logger.error("Goal %s has an empty plan; marking FAILED", goal.id)
                return
            await self.controller.execute_plan(plan)
            # Carry the plan's real outcome through. A PARTIAL plan is not a
            # completed goal, and calling it FAILED hides the work that did run.
            final_status = plan.status if plan.status in ("COMPLETED", "PARTIAL") else "FAILED"
            if final_status != "COMPLETED":
                final_error = (
                    f"Plan ended {plan.status} "
                    f"({plan.completed_subtasks}/{plan.total_subtasks} subtasks completed)"
                )
            logger.info("Daemon goal %s finished: %s (%d/%d subtasks)",
                        goal.id, plan.status, plan.completed_subtasks, plan.total_subtasks)
        except Exception as exc:
            final_status = "FAILED"
            final_error = str(exc)
            logger.error("Goal %s execution failed: %s", goal.id, exc)
        finally:
            goal.completed_at = time.time()
            # The owner reads this, so it has to be prose about real work —
            # never a status token or a goal reference.
            goal.steps = [self._step_payload(st) for st in plan.subtasks]

            duration = goal.completed_at - (goal.started_at or goal.completed_at)

            # Synthesize a conversational answer via the Inference gateway (primary path).
            # _build_summary is only a true fallback when synthesis fails or returns nothing,
            # so the owner never sees a raw status log unless the gateway is unreachable.
            synthesized = ""
            try:
                synthesized = await synthesize_answer(goal.goal, goal.steps)
                if synthesized:
                    goal.summary = synthesized
                    logger.info("Goal %s: synthesized conversational answer via Inference", goal.id)
                else:
                    logger.warning(
                        "Goal %s: synthesis returned an empty answer; using summary fallback", goal.id
                    )
                    goal.summary = self._build_summary(goal, plan, duration)
            except Exception as exc:
                logger.warning(
                    "Goal %s: answer synthesis failed (%s); using summary fallback", goal.id, exc
                )
                goal.summary = self._build_summary(goal, plan, duration)

            goal.status = final_status
            goal.error = final_error
            self._live_plans.pop(goal.id, None)
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
                goal.summary = (
                    "I stopped this one because it ran past the thirty minute limit. "
                    "Nothing further will run; send it again if you still want it."
                )
                goal.completed_at = now
                await self._finish_goal(goal)


# Module-level singleton
autonomous_daemon = AutonomousDaemon()