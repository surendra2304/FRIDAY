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
from friday.autonomous.controller import _mesh_action_for

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
    plan_id: str = ""
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
        plan.plan_id = plan_id

        # Simple goal decomposition based on keywords
        # In production, this would use LLM-based decomposition
        lower_goal = goal.lower()

        # Real multi-agent plan template: chains specialists so that a single
        # high-level goal results in actual work being performed by each agent
        # instead of repeated status probes. Stratex is deliberately not in the
        # research chain: its task protocol only accepts supervision verbs, so a
        # research "trading implications" step would be padded work.
        _research_kw = ("research", "investigate", "analyze", "study", "learn", "explore")
        _followup_kw = ("store", "save", "memory", "report", "trading", "market", "portfolio", "positions",
                        "crypto", "findings", "results")
        if any(kw in lower_goal for kw in _research_kw) and any(kw in lower_goal for kw in _followup_kw):
            plan.add_subtask(SubTask(
                id="st_1",
                description=f"Research the topic and gather evidence from multiple sources: {goal}",
                agent="INTELX",
                dependencies=[],
            ))

            # Add Stratex status check for trading/market/crypto/portfolio/positions goals
            _trading_kw = ("trading", "market", "crypto", "portfolio", "positions")
            if any(kw in lower_goal for kw in _trading_kw):
                plan.add_subtask(SubTask(
                    id="st_2",
                    description="Check current trading positions, balance, and portfolio exposure",
                    agent="STRATEX",
                    dependencies=["st_1"],
                ))
                memora_id = "st_3"
                cortex_id = "st_4"
            else:
                memora_id = "st_2"
                cortex_id = "st_3"

            plan.add_subtask(SubTask(
                id=memora_id,
                description=f"Store the research findings and analysis in persistent memory: {goal}",
                agent="MEMORA",
                dependencies=["st_1"],
            ))
            plan.add_subtask(SubTask(
                id=cortex_id,
                description="Report website health and operational status for the public site",
                agent="CORTEX",
                dependencies=[memora_id],
            ))

        # Check for trading-related goals
        elif any(kw in lower_goal for kw in ["trade", "trading", "crypto", "market", "position"]):
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

        # Check for threat intelligence goals (IntelX)
        elif any(kw in lower_goal for kw in ["threat intelligence", "threat intel", "osint", "intelligence x", "dark web", "breach monitor", "actor profile", "ttp", "threat"]):
            plan.add_subtask(SubTask(
                id="st_1",
                description="Gather threat intelligence from OSINT sources",
                agent="INTELX",
                dependencies=[],
            ))
            plan.add_subtask(SubTask(
                id="st_2",
                description="Analyze threat actor profiles and TPPs",
                agent="INTELX",
                dependencies=["st_1"],
            ))
            plan.add_subtask(SubTask(
                id="st_3",
                description="Generate threat intelligence summary",
                agent="INTELX",
                dependencies=["st_2"],
            ))

        # Check for security operations goals (Sentinel)
        elif any(kw in lower_goal for kw in ["security audit", "vulnerability scan", "compliance audit", "zero trust", "firewall", "incident response", "siem", "soc"]):
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

    _FAILED_PAYLOAD_STATES = {
        "REFUSED", "FORBIDDEN", "BLOCKED", "DENIED", "FAILED", "ERROR",
        "UNVERIFIED", "PENDING", "TIMEOUT", "UNREACHABLE",
    }

    @classmethod
    def _payload_failure(cls, result: Any) -> str:
        """Return the peer's failure status, or "" when the work really ran.

        A mesh dispatch can return a normal dict whose status is REFUSED or
        FORBIDDEN (403). Treating any non-empty dict as success marked those
        subtasks COMPLETED and made the dashboard claim work that never happened.
        """
        if not isinstance(result, dict):
            return ""
        status = str(result.get("status") or "").strip().upper()
        if status in cls._FAILED_PAYLOAD_STATES:
            return status
        if result.get("success") is False:
            return "FAILED"
        error = str(result.get("error") or "").strip()
        if error and error.upper() not in ("NONE", "NULL"):
            return "FAILED"
        return ""

    async def execute_subtask(self, subtask: SubTask, plan: "ExecutionPlan | None" = None) -> bool:
        """Execute a single sub-task."""
        subtask.status = "RUNNING"
        subtask.started_at = time.time()
        subtask.attempts += 1

        directive = subtask.description
        context = self._dependency_context(subtask, plan)
        if context:
            directive = f"{directive}{context}"

        logger.info(f"Executing subtask {subtask.id}: {subtask.description} (agent: {subtask.agent})")
        logger.info("Agent %s is now performing work: %s", subtask.agent, subtask.description)

        try:
            # Route to appropriate agent, passing the subtask description plus any
            # completed upstream findings as the actual objective/directive.
            result = await self._dispatch_to_agent(subtask.agent, directive)

            if result:
                failure = self._payload_failure(result)
                if failure:
                    raise RuntimeError(f"Agent returned {failure}")
                subtask.status = "COMPLETED"
                subtask.result = result
                subtask.completed_at = time.time()
                self._record_action(subtask, result, True)
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
                self._record_action(subtask, str(e), False)
            else:
                subtask.status = "PENDING"
                # Exponential backoff retry
                await asyncio.sleep(2 ** subtask.attempts)

            return False

    def _dependency_context(self, subtask: SubTask, plan: "ExecutionPlan | None") -> str:
        """Carry completed upstream findings into the next agent's directive.

        Plan steps are ordered by dependency, but a peer only receives its own
        description. Adding the upstream summaries makes the handoff real: the
        memory write stores what IntelX actually found, and later steps reason
        over it instead of starting from nothing.
        """
        if plan is None or not subtask.dependencies:
            return ""
        parts: list[str] = []
        for dep_id in subtask.dependencies:
            dep = next((st for st in plan.subtasks if st.id == dep_id), None)
            if dep is None or dep.status != "COMPLETED":
                continue
            summary = self._summarise_result(dep.result, 500).strip()
            if summary:
                parts.append(f"{dep.agent} reported: {summary}")
        if not parts:
            return ""
        joined = "\n".join(parts)
        return (
            "\n\nUpstream findings from the previous step, use this as context "
            f"for your work:\n{joined}"
        )

    @staticmethod
    def _summarise_result(result: Any, limit: int = 300) -> str:
        """Turn an agent envelope into one honest line for the activity log."""
        if isinstance(result, dict):
            for key in ("summary", "spoken_summary", "stage", "status", "error"):
                value = result.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:limit]
            payload = result.get("result")
            if isinstance(payload, dict):
                for key in ("spoken_summary", "text_response", "summary", "stage"):
                    value = payload.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()[:limit]
            return json.dumps(result, default=str)[:limit]
        return str(result)[:limit]

    def _record_action(self, subtask: "SubTask", result: Any, success: bool) -> None:
        """Mirror daemon work into the shared activity history and live stream.

        The daemon dispatches through the mesh, bypassing the controller's own
        action log. Without this the dashboard shows idle rooms while agents are
        actually working, which reads as fake progress.
        """
        try:
            from friday.autonomous.controller import autonomous_controller

            summary = self._summarise_result(result)
            autonomous_controller.record_agent_action(
                agent=subtask.agent,
                directive=subtask.description,
                result=summary,
                success=bool(success) and self._result_is_success(summary, result),
            )
        except Exception as exc:  # never let logging break execution
            logger.debug("Could not record agent action for %s: %s", subtask.agent, exc)

    @staticmethod
    def _result_is_success(summary: str, result: Any) -> bool:
        """A dispatch that returned a refusal is not a successful task.

        Agents such as Stratex answer out-of-domain asks with a REFUSED status.
        Recording that as success would make the activity feed lie.
        """
        head = (summary or "").strip().upper()
        if head.startswith(("REFUSED", "DENIED", "FAILED", "ERROR", "UNVERIFIED")):
            return False
        if isinstance(result, dict):
            if result.get("success") is False:
                return False
            if str(result.get("error") or "").strip():
                return False
        return True

    def _get_peer_mesh(self) -> Any:
        """Lazily build (or reuse a monkeypatched) verified task mesh."""
        mesh = getattr(self, "_peer_mesh", None)
        if mesh is None:
            from friday.cognition.mesh import Mesh, build_contracts
            from friday.ecosystem.fleet_client import fleet_client

            mesh = Mesh(contracts=build_contracts(fleet_client))
            self._peer_mesh = mesh
        return mesh

    async def _dispatch_to_agent(self, agent: str, directive: str) -> Any:
        """Dispatch a directive to a specific agent using the verified mesh with Inference/Memora routing.

        The subtask description is forwarded as the actual objective/directive.
        The mesh action is derived from the description (via the shared helper)
        rather than being hardcoded to a status probe.
        """
        agent_id = agent.lower().strip()
        logger.info("Dispatching real work to %s via Mesh routing: %s", agent.upper(), directive)
        try:
            from friday.cognition.mesh import OutcomeState
            from friday.autonomous import controller as controller_module

            mesh = self._get_peer_mesh()
            mesh_action = controller_module._mesh_action_for(agent_id, directive)
            # A status/health probe action is only appropriate for an explicit
            # status request. For any real work directive, upgrade to "execute"
            # so the peer performs the task instead of returning a status probe.
            status_intent = getattr(controller_module, "_STATUS_INTENT", None)
            is_status_request = bool(status_intent and status_intent.search(directive or ""))
            if mesh_action in ("status", "health_summary") and not is_status_request:
                mesh_action = "execute"
            # Memora only accepts store/query; keep store for write directives.
            if agent_id == "memora" and mesh_action == "execute":
                mesh_action = "store"
            # Stratex: "execute" requires live trading auth (6 gates). For any
            # mesh request from FRIDAY, keep "status" which provides read-only
            # access to positions, supervision, and portfolio state without
            # triggering the live trading authorization gates.
            if agent_id == "stratex" and mesh_action == "execute":
                mesh_action = "status"

            envelope = mesh.build_envelope(
                agent_id,
                action=mesh_action,
                objective=directive,
                inputs={"directive": directive, "content": directive, "text": directive, "query": directive},
                capability=f"{agent_id}.execute",
                actor="friday",
                trust_level="operator_confirmed",
            )
            outcome = await mesh.dispatch(
                agent_id,
                action=mesh_action,
                envelope=envelope,
                attempts=1,
            )
            if outcome.state is OutcomeState.COMPLETED:
                return outcome.result if outcome.result is not None else {
                    "status": "COMPLETED",
                    "detail": outcome.detail,
                }
            elif outcome.state is OutcomeState.PENDING:
                return {"status": "PENDING", "task_id": outcome.task_id, "detail": outcome.detail}
            else:
                logger.warning("Mesh dispatch for %s returned %s: %s", agent, outcome.state, outcome.detail)
                return outcome.result if outcome.result is not None else {
                    "status": outcome.state.value,
                    "detail": outcome.detail,
                }
        except Exception as e:
            logger.error(f"Failed to dispatch to {agent}: {e}")
            return None

    async def execute_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Execute a complete plan with dependency resolution."""
        logger.info(f"Executing plan: {plan.goal[:80]} (subtasks: {len(plan.subtasks)})")
        if not plan.subtasks:
            # An empty plan means no agent did anything. Reporting COMPLETED here
            # is the fake-success path: the goal returns in under a second with
            # zero work. Fail loudly instead.
            logger.error("Plan %s produced no subtasks; refusing to report success", plan.goal[:80])
            plan.status = "FAILED"
            plan.completed_at = time.time()
            self.execution_history.append({
                "plan_id": getattr(plan, "plan_id", "") or f"plan_{int(plan.created_at * 1000)}",
                "goal": plan.goal,
                "status": plan.status,
                "completed": 0,
                "failed": 0,
                "error": "No subtasks were generated for this goal",
            })
            return plan

        for st in plan.subtasks:
            logger.info(f"  Subtask: {st.id} deps={st.dependencies} status={st.status}")
        plan.status = "RUNNING"

        # Execute sub-tasks in dependency order
        iteration = 0
        while plan.get_pending_subtasks():
            iteration += 1
            if iteration > 100:
                logger.error("Plan execution exceeded max iterations")
                break
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
                # No subtask can run right now. Pending subtasks whose
                # dependencies have failed (or been blocked) can never become
                # ready — mark them FAILED so the plan finishes with an honest
                # PARTIAL/FAILED status instead of waiting forever.
                skipped = []
                for st in list(plan.get_pending_subtasks()):
                    for dep_id in st.dependencies:
                        dep = next((s for s in plan.subtasks if s.id == dep_id), None)
                        if dep is not None and dep.status in ("FAILED", "BLOCKED"):
                            st.status = "FAILED"
                            st.error = "Skipped: dependency did not complete"
                            st.completed_at = time.time()
                            self._record_action(st, st.error, False)
                            skipped.append(st)
                            break
                if skipped:
                    plan.completed_subtasks = len(plan.get_completed_subtasks())
                    plan.failed_subtasks = len(plan.get_failed_subtasks())
                    logger.warning(
                        "Plan %s: skipped %d subtasks with failed dependencies",
                        plan.plan_id,
                        len(skipped),
                    )
                    continue
                # All remaining pending subtasks wait on dependencies that are
                # still running or retryable; poll and re-check.
                logger.warning("No ready subtasks, waiting for dependencies... (iteration %d, pending=%d)", iteration, len(plan.get_pending_subtasks()))
                for st in plan.get_pending_subtasks():
                    logger.warning("  Pending: %s deps=%s", st.id, st.dependencies)
                await asyncio.sleep(1)
                continue

            # Execute ready sub-tasks (can be parallelized). Keep explicit task
            # handles so cancellation waits for every in-flight step to finish
            # its cleanup before the parent goal can report a stopped state.
            subtask_tasks = [
                asyncio.create_task(self.execute_subtask(st, plan))
                for st in ready_subtasks
            ]
            try:
                results = await asyncio.gather(*subtask_tasks)
            except asyncio.CancelledError:
                for task in subtask_tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*subtask_tasks, return_exceptions=True)
                raise

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
        plan_id = getattr(plan, "plan_id", "") or f"plan_{int(plan.created_at * 1000)}"
        self.execution_history.append({
            "plan_id": plan_id,
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
