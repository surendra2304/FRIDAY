"""
friday/autonomous/enhanced_controller.py — Enhanced FRIDAY Autonomous Controller.

Extends the base AutonomousController with:
1. Task Decomposition: Breaks complex goals into executable sub-tasks
2. Progress Tracking: Real-time tracking of task completion
3. Adaptive Planning: Adjusts plans based on execution results
4. Cross-Agent Coordination: Orchestrates multiple specialists
5. Self-Evaluation: Evaluates outcomes and learns from results
6. Autonomous Decision Making: Makes decisions without human input for safe operations
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger
from friday.ecosystem.fleet_client import fleet_client

logger = get_logger("autonomous.enhanced_controller")


@dataclass
class SubTask:
    """A sub-task in the autonomous execution plan."""
    id: str
    description: str
    agent: str  # Target agent name (INFERENCE, STRATEX, etc.)
    status: str = "PENDING"  # PENDING, RUNNING, COMPLETED, FAILED
    result: Any = None
    error: str = ""
    attempts: int = 0
    max_attempts: int = 3
    started_at: float = 0.0
    completed_at: float = 0.0
    dependencies: list[str] = field(default_factory=list)


@dataclass
class ExecutionPlan:
    """A complete execution plan for a complex goal."""
    goal: str
    subtasks: list[SubTask] = field(default_factory=list)
    status: str = "PENDING"  # PENDING, RUNNING, COMPLETED, FAILED, PARTIAL
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    total_subtasks: int = 0
    completed_subtasks: int = 0
    failed_subtasks: int = 0

    def add_subtask(self, subtask: SubTask) -> None:
        self.subtasks.append(subtask)
        self.total_subtasks += 1

    def get_pending_subtasks(self) -> list[SubTask]:
        return [s for s in self.subtasks if s.status == "PENDING"]

    def get_running_subtasks(self) -> list[SubTask]:
        return [s for s in self.subtasks if s.status == "RUNNING"]

    def get_completed_subtasks(self) -> list[SubTask]:
        return [s for s in self.subtasks if s.status == "COMPLETED"]

    def get_failed_subtasks(self) -> list[SubTask]:
        return [s for s in self.subtasks if s.status == "FAILED"]

    def get_progress(self) -> float:
        if self.total_subtasks == 0:
            return 0.0
        return self.completed_subtasks / self.total_subtasks


class EnhancedAutonomousController:
    """
    Enhanced autonomous controller with task decomposition, progress tracking,
    and adaptive planning.
    """

    def __init__(self):
        self.plans: dict[str, ExecutionPlan] = {}
        self.active_plan_id: str | None = None
        self.execution_history: list[dict[str, Any]] = []
        self.agent_health: dict[str, dict[str, Any]] = {}

    def decompose_goal(self, goal: str) -> ExecutionPlan:
        """
        Decompose a complex goal into executable sub-tasks.

        Args:
            goal: Natural language goal description

        Returns:
            ExecutionPlan with decomposed sub-tasks
        """
        logger.info(f"Decomposing goal: {goal[:100]}")

        plan = ExecutionPlan(goal=goal)
        plan_id = f"plan_{int(time.time() * 1000)}"

        # Simple goal decomposition based on keywords
        # In production, this would use LLM-based decomposition
        lower_goal = goal.lower()

        # Check for trading-related goals
        if any(kw in lower_goal for kw in ["trade", "trading", "crypto", "market", "position"]):
            plan.add_subtask(SubTask(
                id="st_1",
                description="Analyze market conditions and current positions",
                agent="STRATEX",
                dependencies=[],
            ))
            plan.add_subtask(SubTask(
                id="st_2",
                description="Evaluate trading opportunities based on market analysis",
                agent="STRATEX",
                dependencies=["st_1"],
            ))
            plan.add_subtask(SubTask(
                id="st_3",
                description="Execute trade if conditions met",
                agent="STRATEX",
                dependencies=["st_2"],
            ))

        # Check for research goals
        elif any(kw in lower_goal for kw in ["research", "investigate", "analyze", "study", "learn"]):
            plan.add_subtask(SubTask(
                id="st_1",
                description="Identify research topic and key questions",
                agent="INTELX",
                dependencies=[],
            ))
            plan.add_subtask(SubTask(
                id="st_2",
                description="Gather information from multiple sources",
                agent="INTELX",
                dependencies=["st_1"],
            ))
            plan.add_subtask(SubTask(
                id="st_3",
                description="Verify facts and detect contradictions",
                agent="INTELX",
                dependencies=["st_2"],
            ))
            plan.add_subtask(SubTask(
                id="st_4",
                description="Synthesize findings into report",
                agent="INTELX",
                dependencies=["st_3"],
            ))

        # Check for software/code goals
        elif any(kw in lower_goal for kw in ["code", "build", "develop", "create", "implement", "fix", "bug"]):
            plan.add_subtask(SubTask(
                id="st_1",
                description="Analyze requirements and plan implementation",
                agent="FORGE",
                dependencies=[],
            ))
            plan.add_subtask(SubTask(
                id="st_2",
                description="Write and test code",
                agent="FORGE",
                dependencies=["st_1"],
            ))
            plan.add_subtask(SubTask(
                id="st_3",
                description="Run security audit on generated code",
                agent="SENTINEL",
                dependencies=["st_2"],
            ))
            plan.add_subtask(SubTask(
                id="st_4",
                description="Deploy if audit passes",
                agent="FORGE",
                dependencies=["st_3"],
            ))

        # Check for video/content goals
        elif any(kw in lower_goal for kw in ["video", "youtube", "content", "video", "production"]):
            plan.add_subtask(SubTask(
                id="st_1",
                description="Discover trending topics and content ideas",
                agent="VYRALX",
                dependencies=[],
            ))
            plan.add_subtask(SubTask(
                id="st_2",
                description="Generate script and content pack",
                agent="VYRALX",
                dependencies=["st_1"],
            ))
            plan.add_subtask(SubTask(
                id="st_3",
                description="Render and produce video",
                agent="VYRALX",
                dependencies=["st_2"],
            ))
            plan.add_subtask(SubTask(
                id="st_4",
                description="Publish to YouTube",
                agent="VYRALX",
                dependencies=["st_3"],
            ))

        # Check for forecasting goals
        elif any(kw in lower_goal for kw in ["forecast", "predict", "probability", "estimate"]):
            plan.add_subtask(SubTask(
                id="st_1",
                description="Collect historical data and current conditions",
                agent="FUTURIS",
                dependencies=[],
            ))
            plan.add_subtask(SubTask(
                id="st_2",
                description="Run predictive models and calibrate",
                agent="FUTURIS",
                dependencies=["st_1"],
            ))
            plan.add_subtask(SubTask(
                id="st_3",
                description="Generate forecast with confidence intervals",
                agent="FUTURIS",
                dependencies=["st_2"],
            ))

        # Check for memory/recall goals
        elif any(kw in lower_goal for kw in ["memory", "remember", "recall", "store", "save"]):
            plan.add_subtask(SubTask(
                id="st_1",
                description="Store information in appropriate memory scope",
                agent="MEMORA",
                dependencies=[],
            ))
            plan.add_subtask(SubTask(
                id="st_2",
                description="Verify storage and create retrieval index",
                agent="MEMORA",
                dependencies=["st_1"],
            ))

        # Check for web/browser goals
        elif any(kw in lower_goal for kw in ["browse", "web", "scrape", "crawl", "website", "url"]):
            plan.add_subtask(SubTask(
                id="st_1",
                description="Navigate to target URL",
                agent="CORTEX",
                dependencies=[],
            ))
            plan.add_subtask(SubTask(
                id="st_2",
                description="Extract content and data",
                agent="CORTEX",
                dependencies=["st_1"],
            ))

        # Check for security goals
        elif any(kw in lower_goal for kw in ["security", "audit", "vulnerability", "threat", "protect", "scan"]):
            plan.add_subtask(SubTask(
                id="st_1",
                description="Scan target for vulnerabilities",
                agent="SENTINEL",
                dependencies=[],
            ))
            plan.add_subtask(SubTask(
                id="st_2",
                description="Analyze findings and assess risk",
                agent="SENTINEL",
                dependencies=["st_1"],
            ))
            plan.add_subtask(SubTask(
                id="st_3",
                description="Generate remediation recommendations",
                agent="SENTINEL",
                dependencies=["st_2"],
            ))

        # Default plan for general goals
        else:
            plan.add_subtask(SubTask(
                id="st_1",
                description="Analyze goal and gather context",
                agent="INFERENCE",
                dependencies=[],
            ))
            plan.add_subtask(SubTask(
                id="st_2",
                description="Plan execution approach",
                agent="INFERENCE",
                dependencies=["st_1"],
            ))
            plan.add_subtask(SubTask(
                id="st_3",
                description="Execute planned actions",
                agent="INFERENCE",
                dependencies=["st_2"],
            ))

        plan.status = "PENDING"
        self.plans[plan_id] = plan
        self.active_plan_id = plan_id

        logger.info(f"Created plan {plan_id} with {len(plan.subtasks)} subtasks")
        return plan

    async def execute_subtask(self, subtask: SubTask) -> bool:
        """Execute a single sub-task."""
        subtask.status = "RUNNING"
        subtask.started_at = time.time()
        subtask.attempts += 1

        logger.info(f"Executing subtask {subtask.id}: {subtask.description} (agent: {subtask.agent})")

        try:
            # Route to appropriate agent
            result = await self._dispatch_to_agent(subtask.agent, subtask.description)

            if result:
                subtask.status = "COMPLETED"
                subtask.result = result
                subtask.completed_at = time.time()
                logger.info(f"Subtask {subtask.id} completed successfully")
                return True
            else:
                raise RuntimeError("Agent returned no result")

        except Exception as e:
            subtask.error = str(e)
            logger.error(f"Subtask {subtask.id} failed: {e}")

            if subtask.attempts >= subtask.max_attempts:
                subtask.status = "FAILED"
                subtask.completed_at = time.time()
            else:
                subtask.status = "PENDING"
                # Exponential backoff retry
                await asyncio.sleep(2 ** subtask.attempts)

            return False

    async def _dispatch_to_agent(self, agent: str, directive: str) -> Any:
        """Dispatch a directive to a specific agent."""
        try:
            # Use fleet_client to dispatch to agent
            result = await fleet_client.dispatch(
                agent=agent,
                directive=directive,
                timeout=30.0,
            )
            return result
        except Exception as e:
            logger.error(f"Failed to dispatch to {agent}: {e}")
            return None

    async def execute_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Execute a complete plan with dependency resolution."""
        logger.info(f"Executing plan: {plan.goal[:80]}")
        plan.status = "RUNNING"

        # Execute sub-tasks in dependency order
        while plan.get_pending_subtasks():
            # Find sub-tasks with all dependencies satisfied
            ready_subtasks = []
            for subtask in plan.get_pending_subtasks():
                deps_met = all(
                    dep_subtask.status == "COMPLETED"
                    for dep_subtask in plan.subtasks
                    if dep_subtask.id in subtask.dependencies
                )
                if deps_met:
                    ready_subtasks.append(subtask)

            if not ready_subtasks:
                logger.warning("No ready subtasks, waiting for dependencies...")
                await asyncio.sleep(1)
                continue

            # Execute ready sub-tasks (can be parallelized)
            results = await asyncio.gather(
                *[self.execute_subtask(st) for st in ready_subtasks]
            )

            # Update plan progress
            plan.completed_subtasks = len(plan.get_completed_subtasks())
            plan.failed_subtasks = len(plan.get_failed_subtasks())

        # Final plan status
        if plan.failed_subtasks == 0:
            plan.status = "COMPLETED"
        elif plan.completed_subtasks > 0:
            plan.status = "PARTIAL"
        else:
            plan.status = "FAILED"

        plan.completed_at = time.time()

        # Record execution history
        self.execution_history.append({
            "plan_id": plan_id if 'plan_id' in locals() else "",
            "goal": plan.goal,
            "status": plan.status,
            "completed": plan.completed_subtasks,
            "failed": plan.failed_subtasks,
            "duration": plan.completed_at - plan.created_at,
        })

        logger.info(
            f"Plan execution completed: {plan.status} "
            f"({plan.completed_subtasks}/{plan.total_subtasks} subtasks)"
        )

        return plan

    def evaluate_outcome(self, plan: ExecutionPlan) -> dict[str, Any]:
        """Evaluate the outcome of a completed plan."""
        evaluation = {
            "plan_goal": plan.goal,
            "status": plan.status,
            "success_rate": plan.get_progress(),
            "total_subtasks": plan.total_subtasks,
            "completed": plan.completed_subtasks,
            "failed": plan.failed_subtasks,
            "duration": plan.completed_at - plan.created_at if plan.completed_at else 0,
            "failed_subtasks": [
                {"id": st.id, "description": st.description, "error": st.error}
                for st in plan.get_failed_subtasks()
            ],
        }

        # Generate insights
        insights = []
        if plan.failed_subtasks > 0:
            insights.append(f"{plan.failed_subtasks} subtasks failed")

        if plan.duration > 3600:  # > 1 hour
            insights.append("Execution took over 1 hour")

        if plan.completed_subtasks == plan.total_subtasks:
            insights.append("All subtasks completed successfully")

        evaluation["insights"] = insights
        return evaluation

    def get_active_plan(self) -> ExecutionPlan | None:
        """Get the currently active plan."""
        if self.active_plan_id and self.active_plan_id in self.plans:
            return self.plans[self.active_plan_id]
        return None

    def get_execution_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent execution history."""
        return self.execution_history[-limit:]

    def get_agent_health(self) -> dict[str, dict[str, Any]]:
        """Get health status of all agents."""
        return self.agent_health

    async def check_agent_health(self) -> dict[str, dict[str, Any]]:
        """Check health of all agents in the fleet."""
        agents = ["INFERENCE", "STRATEX", "INTELX", "FUTURIS", "CORTEX", "FORGE", "SENTINEL", "MEMORA", "VYRALX"]

        for agent in agents:
            try:
                health = await fleet_client.health_check(agent)
                self.agent_health[agent] = health
            except Exception as e:
                self.agent_health[agent] = {"status": "UNHEALTHY", "error": str(e)}

        return self.agent_health


# Module-level singleton
enhanced_controller = EnhancedAutonomousController()
