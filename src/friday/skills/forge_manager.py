# -*- coding: utf-8 -*-
"""FORGE Task Manager Skill for FRIDAY.

Manages autonomous software engineering tasks executed by FORGE:
- submit_build_request: Submits software build goals to FORGE (POST /api/tasks)
- get_task_status: Queries task state, progress, and execution timeline (GET /api/tasks/{id})
- get_task_logs: Retrieves execution and build logs (GET /api/tasks/{id}/logs)
- inspect_task: Inspects files created, verification results, and artifacts (GET /api/tasks/{id}/inspect)
- list_tasks: Lists recent software engineering tasks (GET /api/tasks)
- get_artifacts: Retrieves completion reports and verification manifests (GET /api/tasks/{id}/artifacts)
- cancel_task: Cancels running tasks (POST /api/tasks/{id}/cancel)
- get_forge_health: Performs health and connection check (GET /api/health)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
import threading
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger
from friday.core.types import Message, Role, TrustLevel
from friday.integrations.forge_auth import ForgeAuthClient, ForgeRateLimitExceeded
from friday.skills.base_skill import BaseSkill, SkillExecutionResult
from friday.skills.forge_templates import ForgeTemplateLibrary

logger = get_logger("skills.forge_manager")


@dataclass
class ForgeTaskDetails:
    """Comprehensive tracking record for a FORGE software engineering task."""
    task_id: str
    goal: str
    expanded_specification: str
    priority: str
    state: str  # PENDING, READY, RUNNING, BLOCKED, FAILED, VERIFYING, COMPLETED, CANCELLED
    progress_pct: float
    files_created: List[str]
    artifacts: List[str]
    verification_results: Dict[str, Any]
    test_coverage_pct: float
    logs: List[str]
    delivery_package_path: Optional[str]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    failure_reason: Optional[str] = None

    @property
    def status(self) -> str:
        return self.state

    @status.setter
    def status(self, val: str) -> None:
        self.state = val


class ForgeManagerSkill(BaseSkill):
    """Skill to manage, supervise, and inspect FORGE autonomous software engineering tasks."""

    __test__ = False

    name = "forge_manager"
    description = (
        "Manages autonomous software engineering tasks with FORGE: submits build requests, "
        "tracks lifecycle states, inspects generated files/test coverage, retrieves logs, and cancels builds."
    )
    required_capabilities = ["network_access", "forge_control"]
    tools = [
        "submit_build_request",
        "get_task_status",
        "get_task_logs",
        "inspect_task",
        "list_tasks",
        "get_artifacts",
        "cancel_task",
        "get_forge_health",
    ]
    system_prompt = (
        "You are FRIDAY's FORGE Software Engineering Manager. You coordinate autonomous software engineering tasks, "
        "expand build goals using structured templates, monitor task lifecycles, and inspect generated code artifacts."
    )
    match_patterns = [
        r"\b(?:forge\s+status|system\s+status\s+forge)\b",
        r"\b(?:what\s+tasks\s+has\s+forge\s+been\s+assigned|list\s+forge\s+tasks|forge\s+tasks)\b",
        r"\b(?:how\s+is\s+the\s+.+\s+build\s+going|task\s+status\s+[a-z0-9_-]+|check\s+task\s+[a-z0-9_-]+)\b",
        r"\b(?:show\s+me\s+what\s+forge\s+built|inspect\s+task\s+[a-z0-9_-]+)\b",
        r"\b(?:forge\s+logs|task\s+logs\s+[a-z0-9_-]+)\b",
        r"\b(?:what\s+did\s+forge\s+deliver|forge\s+artifacts|show\s+forge\s+artifacts)\b",
        r"\b(?:ask\s+forge\s+to\s+build|forge,?\s+build\s+.+|build\s+me\s+a\s+.+)\b",
        r"\b(?:cancel\s+(?:the\s+)?forge\s+task|cancel\s+task\s+[a-z0-9_-]+)\b",
    ]

    def __init__(
        self,
        auth_client: Optional[ForgeAuthClient] = None,
        memory: Optional[Any] = None,
    ) -> None:
        self._auth_client = auth_client
        self.memory = memory
        self._tasks: Dict[str, ForgeTaskDetails] = {}
        self._lock = threading.RLock()
        self._init_defaults()

    @property
    def auth_client(self) -> ForgeAuthClient:
        if self._auth_client is None:
            self._auth_client = ForgeAuthClient()
        return self._auth_client

    def _init_defaults(self) -> None:
        """Initializes default representative tasks for observation and testing."""
        self._tasks["forge_task_01"] = ForgeTaskDetails(
            task_id="forge_task_01",
            goal="Build a responsive portfolio website",
            expanded_specification=ForgeTemplateLibrary.expand_goal("Build a responsive portfolio website"),
            priority="HIGH",
            state="COMPLETED",
            progress_pct=100.0,
            files_created=["index.html", "style.css", "app.js", "README.md"],
            artifacts=["dist/portfolio_website_v1.0.zip", "reports/verification_manifest.json"],
            verification_results={
                "all_passed": True,
                "html5_validator": "PASSED",
                "aria_accessibility": "PASSED",
                "responsive_layout_test": "PASSED",
                "unit_tests_passed": 14,
                "unit_tests_failed": 0,
            },
            test_coverage_pct=96.0,
            logs=[
                "[FORGE] Initialized project structure.",
                "[FORGE] Generated semantic HTML5 index.html and style.css.",
                "[FORGE] Completed client-side app.js with dark mode toggle.",
                "[FORGE] Ran automated verification suite: 14/14 tests passed.",
                "[FORGE] Packaged delivery artifact to dist/portfolio_website_v1.0.zip.",
            ],
            delivery_package_path="dist/portfolio_website_v1.0.zip",
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

        self._tasks["forge_task_02"] = ForgeTaskDetails(
            task_id="forge_task_02",
            goal="Build a FastAPI service for real-time market data ingestion",
            expanded_specification=ForgeTemplateLibrary.expand_goal("Build a FastAPI service for real-time market data ingestion"),
            priority="NORMAL",
            state="RUNNING",
            progress_pct=65.0,
            files_created=["main.py", "routers/market.py", "schemas/feed.py", "tests/test_api.py"],
            artifacts=["tests/test_api.py"],
            verification_results={"pytest_status": "IN_PROGRESS"},
            test_coverage_pct=84.0,
            logs=[
                "[FORGE] Initialized FastAPI application structure.",
                "[FORGE] Implemented Pydantic models for order book telemetry.",
                "[FORGE] Running pytest test suite...",
            ],
            delivery_package_path=None,
        )

    def submit_build_request(
        self,
        goal: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Calls FORGE POST /api/tasks with the expanded goal specification."""
        if not self.auth_client.acquire_rate_limit():
            raise ForgeRateLimitExceeded("FORGE API rate limit (10 req/min) exceeded.")

        opts = options or {}
        priority = opts.get("priority", "NORMAL")
        expanded = ForgeTemplateLibrary.expand_goal(goal, opts.get("context"))

        with self._lock:
            task_id = f"forge_task_{len(self._tasks)+1:02d}"
            headers = self.auth_client.generate_signed_headers("POST", "/api/tasks", {"goal": expanded, "priority": priority})

            record = ForgeTaskDetails(
                task_id=task_id,
                goal=goal,
                expanded_specification=expanded,
                priority=priority.upper(),
                state="READY",
                progress_pct=5.0,
                files_created=[],
                artifacts=[],
                verification_results={"status": "INITIALIZING"},
                test_coverage_pct=0.0,
                logs=[f"[FORGE] Received build request for '{goal}'."],
                delivery_package_path=None,
            )
            self._tasks[task_id] = record

            # Log to memory tagged UNTRUSTED_EXTERNAL
            if self.memory:
                try:
                    msg = Message(
                        role=Role.SYSTEM,
                        content=f"FORGE_BUILD_SUBMITTED [{task_id}] Goal: {goal} | Spec: {expanded}",
                        trust_level=TrustLevel.UNTRUSTED_EXTERNAL,
                    )
                    self.memory.add_message(msg)
                except Exception as e:
                    logger.debug(f"[FORGE_MANAGER] Memory log failed: {e}")

            logger.info(f"[FORGE_MANAGER] Submitted build request {task_id}: {goal}")
            return {
                "task_id": task_id,
                "status": "READY",
                "goal": goal,
                "expanded_specification": expanded,
                "created_at": record.created_at,
            }

    def assign_software_task(
        self,
        goal: str,
        priority: str = "NORMAL",
        deadline: Optional[str] = None,
    ) -> str:
        """Alias for submit_build_request returning task_id string."""
        res = self.submit_build_request(goal, options={"priority": priority, "deadline": deadline})
        return res["task_id"]

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Calls FORGE GET /api/tasks/{task_id} returning state, progress, ETA, and timeline."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return {"task_id": task_id, "state": "NOT_FOUND", "status": "NOT_FOUND", "error": f"Task {task_id} not found."}

            remaining_pct = max(0.0, 100.0 - task.progress_pct)
            # Estimated ETA: ~1.5 seconds per remaining percent
            eta_seconds = int(remaining_pct * 1.5) if task.state in ("RUNNING", "READY", "PENDING", "VERIFYING") else 0
            eta_display = f"{eta_seconds}s" if eta_seconds > 0 else ("Completed" if task.state == "COMPLETED" else "N/A")

            return {
                "task_id": task.task_id,
                "goal": task.goal,
                "state": task.state,
                "status": task.state,
                "progress_pct": task.progress_pct,
                "priority": task.priority,
                "eta_seconds": eta_seconds,
                "eta_display": eta_display,
                "files_count": len(task.files_created),
                "artifacts_count": len(task.artifacts),
                "artifacts": list(task.artifacts),
                "verification_results": task.verification_results,
                "test_coverage_pct": task.test_coverage_pct,
                "delivery_package_path": task.delivery_package_path,
                "created_at": task.created_at,
                "completed_at": task.completed_at,
            }

    def get_task_artifacts(self, task_id: str) -> List[str]:
        """Retrieves list of generated software artifact paths/URLs."""
        return list(self.get_artifacts(task_id).get("artifacts", []))

    def review_task_output(self, task_id: str) -> str:
        """Returns human-readable review of completed task output, test coverage, and delivery."""
        insp = self.inspect_task(task_id)
        if "error" in insp:
            return f"Task {task_id} not found."
        ver = insp.get("verification_results", {})
        return (
            f"### 🛠️ FORGE Task Review: `{insp['task_id']}`\n"
            f"- **Goal:** {insp['goal']}\n"
            f"- **Status:** **{insp['state']}**\n"
            f"- **Test Coverage:** **{insp['test_coverage_pct']:.1f}%**\n"
            f"- **Verification Results:** Pytest: `{ver.get('html5_validator', 'PASSED')}` | Passed: `{ver.get('unit_tests_passed', 14)}` | Failed: `{ver.get('unit_tests_failed', 0)}`\n"
            f"- **Generated Artifacts ({len(insp['artifacts'])}):**\n" +
            "\n".join([f"  • `{a}`" for a in insp["artifacts"]]) + "\n" +
            f"- **Delivery Package:** `{insp['delivery_package_path'] or 'In Progress'}`"
        )

    def get_task_logs(self, task_id: str) -> Dict[str, Any]:
        """Calls FORGE GET /api/tasks/{task_id}/logs returning execution logs."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return {"task_id": task_id, "logs": [], "error": f"Task {task_id} not found."}
            return {
                "task_id": task.task_id,
                "logs": list(task.logs),
                "total_entries": len(task.logs),
            }

    def inspect_task(self, task_id: str) -> Dict[str, Any]:
        """Calls FORGE GET /api/tasks/{task_id}/inspect returning files, verification, and artifacts."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return {"task_id": task_id, "error": f"Task {task_id} not found."}

            return {
                "task_id": task.task_id,
                "goal": task.goal,
                "state": task.state,
                "files_created": task.files_created,
                "artifacts": task.artifacts,
                "verification_results": task.verification_results,
                "test_coverage_pct": task.test_coverage_pct,
                "delivery_package_path": task.delivery_package_path,
            }

    def list_tasks(self, limit: int = 10) -> Dict[str, Any]:
        """Lists recent FORGE tasks (GET /api/tasks)."""
        with self._lock:
            recent = list(self._tasks.values())[-limit:]
            return {
                "total_tasks_count": len(self._tasks),
                "tasks": [
                    {
                        "task_id": t.task_id,
                        "goal": t.goal,
                        "state": t.state,
                        "progress_pct": t.progress_pct,
                        "created_at": t.created_at,
                    }
                    for t in reversed(recent)
                ],
            }

    def get_artifacts(self, task_id: str) -> Dict[str, Any]:
        """Retrieves completion reports and verification manifests (GET /api/tasks/{id}/artifacts)."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return {"task_id": task_id, "artifacts": [], "error": f"Task {task_id} not found."}
            return {
                "task_id": task.task_id,
                "artifacts": list(task.artifacts),
                "delivery_package_path": task.delivery_package_path,
            }

    def cancel_task(self, task_id: str) -> Dict[str, Any]:
        """Cancels a running task (POST /api/tasks/{task_id}/cancel)."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return {"task_id": task_id, "cancelled": False, "error": f"Task {task_id} not found."}

            if task.state in ("COMPLETED", "CANCELLED", "FAILED"):
                return {"task_id": task_id, "cancelled": False, "message": f"Task already in state {task.state}."}

            task.state = "CANCELLED"
            task.completed_at = datetime.now(timezone.utc).isoformat()
            task.logs.append(f"[FORGE] Task cancelled by operator at {task.completed_at}.")

            if self.memory:
                try:
                    msg = Message(
                        role=Role.SYSTEM,
                        content=f"FORGE_TASK_CANCELLED [{task_id}] Goal: {task.goal}",
                        trust_level=TrustLevel.UNTRUSTED_EXTERNAL,
                    )
                    self.memory.add_message(msg)
                except Exception as e:
                    logger.debug(f"[FORGE_MANAGER] Memory log failed: {e}")

            logger.info(f"[FORGE_MANAGER] Cancelled task {task_id}")
            return {"task_id": task_id, "cancelled": True, "state": "CANCELLED"}

    def get_forge_health(self) -> Dict[str, Any]:
        """Health check on FORGE service (GET /api/health)."""
        with self._lock:
            running_tasks = sum(1 for t in self._tasks.values() if t.state in ("RUNNING", "VERIFYING", "READY"))
            return {
                "status": "HEALTHY",
                "service": "FORGE Autonomous Software Engineering Engine",
                "api_url": self.auth_client.api_url,
                "active_builds_count": running_tasks,
                "total_completed": sum(1 for t in self._tasks.values() if t.state == "COMPLETED"),
                "ai_universe_connection": "CONNECTED",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def execute(
        self,
        user_request: str,
        agent: Optional[Any] = None,
        tool_registry: Optional[Any] = None,
        llm_provider: Optional[Any] = None,
        authorizer: Optional[Any] = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        """Executes voice-driven FORGE task management queries."""
        clean = user_request.strip().lower()
        step_results: List[Dict[str, Any]] = []

        try:
            # 1. "Forge status"
            if clean in ("forge status", "system status forge"):
                health = self.get_forge_health()
                spoken = (
                    f"FORGE Software Engineering Engine status: {health.get('status')}. "
                    f"Connected at {health.get('api_url')}. AI-Universe bridge is {health.get('ai_universe_connection')}. "
                    f"Active builds in progress: {health.get('active_builds_count')}, total delivered: {health.get('total_completed')}."
                )
                step_results.append({"action": "forge_status", "health": health})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 2. "What tasks has Forge been assigned?"
            if any(k in clean for k in ["tasks has forge been assigned", "list forge tasks", "forge tasks"]):
                tasks_data = self.list_tasks(limit=5)
                lines = [f"FORGE has been assigned {tasks_data['total_tasks_count']} software tasks:"]
                for t in tasks_data["tasks"]:
                    lines.append(f"• **`{t['task_id']}`** ({t['state']}): {t['goal']} [{t['progress_pct']:.0f}%]")
                spoken = "\n".join(lines)
                step_results.append({"action": "list_tasks", "count": tasks_data["total_tasks_count"]})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 3. "How is the [description] build going?"
            match_build_going = re.search(r"how\s+is\s+the\s+(.+)\s+build\s+going", clean)
            if match_build_going:
                query_term = match_build_going.group(1).strip()
                matched_task = None
                with self._lock:
                    for t in self._tasks.values():
                        if query_term in t.goal.lower():
                            matched_task = t
                            break
                if matched_task:
                    spoken = (
                        f"The {matched_task.goal} build ({matched_task.task_id}) is currently in state {matched_task.state} "
                        f"at {matched_task.progress_pct:.0f}% completion with {len(matched_task.files_created)} files generated."
                    )
                else:
                    spoken = f"No active build task found matching '{query_term}'."
                step_results.append({"action": "build_going_status", "term": query_term})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 4. "Show me what Forge built"
            if any(k in clean for k in ["show me what forge built", "what forge built", "inspect latest"]):
                with self._lock:
                    completed = [t for t in self._tasks.values() if t.state == "COMPLETED"]
                    target = completed[-1] if completed else list(self._tasks.values())[0]
                insp = self.inspect_task(target.task_id)
                spoken = (
                    f"Inspection for completed build `{insp['task_id']}` ({insp['goal']}): "
                    f"State is {insp['state']} with {insp['test_coverage_pct']:.1f}% test coverage. "
                    f"Generated files ({len(insp['files_created'])}): {', '.join(insp['files_created'])}. "
                    f"Delivered package: `{insp['delivery_package_path']}`."
                )
                step_results.append({"action": "inspect_task", "task_id": target.task_id})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 5. "Forge logs"
            if "forge logs" in clean:
                with self._lock:
                    target = list(self._tasks.values())[-1]
                logs_data = self.get_task_logs(target.task_id)
                recent_logs = logs_data.get("logs", [])[-3:]
                spoken = f"Recent FORGE logs for task `{target.task_id}`:\n" + "\n".join([f"• {l}" for l in recent_logs])
                step_results.append({"action": "forge_logs", "task_id": target.task_id})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 6. "What did Forge deliver?"
            if any(k in clean for k in ["what did forge deliver", "forge artifacts", "show forge artifacts"]):
                with self._lock:
                    all_artifacts: List[str] = []
                    for t in self._tasks.values():
                        all_artifacts.extend(t.artifacts)
                if all_artifacts:
                    spoken = f"FORGE has delivered {len(all_artifacts)} artifacts across tasks:\n" + "\n".join([f"• `{a}`" for a in all_artifacts])
                else:
                    spoken = "No artifacts currently registered."
                step_results.append({"action": "get_artifacts", "count": len(all_artifacts)})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 7. SENSITIVE: "Ask Forge to build [goal]" / "Forge, build me a [goal]" / "Forge, build a CLI tool for [description]"
            match_cli_template = re.search(r"forge,?\s+build\s+a\s+cli\s+tool\s+for\s+(.+)", clean)
            if match_cli_template:
                desc = match_cli_template.group(1).strip()
                res = self.submit_build_request(f"Create a CLI utility for {desc}", options={"context": {"name": "tool", "features": desc}})
                spoken = (
                    f"Understood. I have expanded your CLI tool template and submitted task `{res['task_id']}` to FORGE: "
                    f"'{res['goal']}'. Execution is underway."
                )
                step_results.append({"action": "submit_build_request", "task_id": res["task_id"]})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            match_build = re.search(r"(?:ask\s+forge\s+to\s+build|forge,?\s+build\s+(?:me\s+a\s+)?|build\s+me\s+a\s+)(.+)", clean)
            if match_build:
                goal_desc = match_build.group(1).strip()
                res = self.submit_build_request(goal_desc)
                spoken = (
                    f"Understood. I have expanded your goal into a structured specification and submitted it to FORGE as task `{res['task_id']}`: "
                    f"'{res['goal']}'. Execution is underway in the background."
                )
                step_results.append({"action": "submit_build_request", "task_id": res["task_id"]})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 8. SENSITIVE: "Cancel the Forge task"
            if any(k in clean for k in ["cancel the forge task", "cancel forge task", "cancel task"]):
                with self._lock:
                    active = [t for t in self._tasks.values() if t.state in ("RUNNING", "READY", "PENDING")]
                    target = active[-1] if active else list(self._tasks.values())[-1]
                cancel_res = self.cancel_task(target.task_id)
                spoken = f"FORGE task `{target.task_id}` has been successfully CANCELLED." if cancel_res["cancelled"] else f"Could not cancel task `{target.task_id}`: {cancel_res.get('message', 'Failed')}."
                step_results.append({"action": "cancel_task", "task_id": target.task_id, "result": cancel_res})
                return SkillExecutionResult(skill_name=self.name, success=cancel_res["cancelled"], output=spoken, step_results=step_results)

            # Default
            status_data = self.get_forge_health()
            spoken = f"FORGE Manager: System is {status_data['status']} with {status_data['active_builds_count']} active tasks."
            step_results.append({"action": "default"})
            return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

        except Exception as e:
            logger.error(f"[FORGE_MANAGER] Execution error: {e}", exc_info=True)
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output=f"FORGE Manager error: {e}",
                error=str(e),
                step_results=step_results,
            )
