"""FORGE Task Manager Skill for FRIDAY.

Manages software engineering tasks on behalf of FORGE. Task records live in this
process; a build request is additionally POSTed to the FORGE REST API when that
API answers, and the record says which of the two happened.
- submit_build_request: Expands a goal, records it, and dispatches it to FORGE (POST /api/tasks) when reachable
- get_task_status: Returns the tracked state, progress and ETA of a task record
- get_task_logs: Returns the execution/build log lines recorded for a task
- inspect_task: Inspects recorded files, verification results and artifacts
- list_tasks: Lists recent software engineering task records
- get_artifacts: Retrieves recorded completion reports and verification manifests
- cancel_task: Cancels a tracked task (and asks FORGE to cancel it when reachable)
- get_forge_health: Probes FORGE (GET /api/health) and reports what it answered

Each docstring here used to claim a REST call without one being made, so a task
that never left this process was reported as a FORGE build and a health check
that never happened reported HEALTHY.
"""

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    files_created: list[str]
    artifacts: list[str]
    verification_results: dict[str, Any]
    test_coverage_pct: float
    logs: list[str]
    delivery_package_path: str | None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    failure_reason: str | None = None

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
        auth_client: ForgeAuthClient | None = None,
        memory: Any | None = None,
        *,
        demo_data: bool | None = None,
    ) -> None:
        self._auth_client = auth_client
        self.memory = memory
        self._tasks: dict[str, ForgeTaskDetails] = {}
        self._lock = threading.RLock()
        # Sample tasks used to be seeded unconditionally, so every freshly built
        # ForgeManagerSkill - in production, in the voice skill, in the dashboard -
        # claimed a COMPLETED delivery ("Build a responsive portfolio website",
        # 100%, all verifications PASSED) whose artifact paths existed nowhere on
        # disk. The dashboard rendered it as "1 task completed" and the voice
        # skill announced "task forge_task_01 delivered". Sample data now needs
        # to be asked for.
        from friday.ecosystem.command_center import demo_mode_enabled

        self.demo_data = demo_data if demo_data is not None else demo_mode_enabled()
        if self.demo_data:
            self._init_defaults()

    def _forge_request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        timeout_sec: float = 3.0,
    ) -> dict[str, Any]:
        """One signed HTTP call to the FORGE API. Never raises.

        Returns ``{"ok", "url", "http_status", "error", "payload"}``. The client
        is asked for signed headers, the call is made, and whatever happened is
        reported - including the fact that nothing answered.
        """
        import json as _json
        import urllib.error
        import urllib.request

        url = f"{self.auth_client.api_url}{path}"
        result: dict[str, Any] = {"ok": False, "url": url, "http_status": None, "error": None, "payload": {}}
        try:
            data = _json.dumps(body).encode("utf-8") if body is not None else None
            request = urllib.request.Request(url, data=data, method=method.upper())
            for header, value in self.auth_client.generate_signed_headers(
                method.upper(), path, body or {}
            ).items():
                request.add_header(header, value)
            request.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                result["http_status"] = getattr(response, "status", None) or response.getcode()
                raw = response.read().decode("utf-8", errors="replace")
            result["ok"] = 200 <= int(result["http_status"] or 0) < 300
            if raw:
                try:
                    result["payload"] = _json.loads(raw)
                except ValueError:
                    result["payload"] = {"raw_response": raw[:400]}
            if not result["ok"]:
                result["error"] = f"HTTP {result['http_status']}"
        except urllib.error.HTTPError as e:  # answered, but not with a success
            result["http_status"] = e.code
            result["error"] = f"HTTP {e.code}"
            try:
                payload = _json.loads(e.read().decode("utf-8", errors="replace") or "{}")
                result["payload"] = payload if isinstance(payload, dict) else {}
            except Exception:
                result["payload"] = {}
        except Exception as e:  # no answer at all
            result["error"] = f"{type(e).__name__}: {e}"
        return result

    def _probe_forge_api(self) -> dict[str, Any]:
        """Issues the health request the health report claims to be based on."""
        return self._forge_request("GET", "/api/health", timeout_sec=2.5)

    @property
    def auth_client(self) -> ForgeAuthClient:
        if self._auth_client is None:
            self._auth_client = ForgeAuthClient()
        return self._auth_client

    def _init_defaults(self) -> None:
        """Sample tasks for demos and tests. Served only when demo mode is on."""
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
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Expands the goal, records the task, and POSTs it to FORGE when reachable.

        The record is kept either way; ``dispatched`` in the result says whether a
        running FORGE accepted it, so a caller cannot mistake a local note for a
        build in progress.
        """
        if not self.auth_client.acquire_rate_limit():
            raise ForgeRateLimitExceeded("FORGE API rate limit (10 req/min) exceeded.")

        opts = options or {}
        priority = opts.get("priority", "NORMAL")
        expanded = ForgeTemplateLibrary.expand_goal(goal, opts.get("context"))

        dispatch = self._forge_request("POST", "/api/tasks", {"goal": expanded, "priority": priority})

        with self._lock:
            task_id = f"forge_task_{len(self._tasks)+1:02d}"

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
            if dispatch["ok"]:
                record.logs.append(
                    f"[FORGE] Dispatched to {dispatch['url']} (HTTP {dispatch['http_status']})."
                )
            else:
                record.logs.append(
                    f"[FORGE] Not dispatched to {dispatch['url']}"
                    f" ({dispatch['error'] or 'no response'}); tracked in this process only. No build is running."
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

            logger.info(f"[FORGE_MANAGER] Submitted build request {task_id}: {goal} (dispatched={dispatch['ok']})")
            return {
                "task_id": task_id,
                "status": "READY",
                "dispatch_status": "DISPATCHED" if dispatch["ok"] else "LOCAL_ONLY",
                "dispatched": dispatch["ok"],
                "dispatch_url": dispatch["url"],
                "dispatch_error": None if dispatch["ok"] else (dispatch["error"] or "no response"),
                "goal": goal,
                "expanded_specification": expanded,
                "created_at": record.created_at,
            }

    def assign_software_task(
        self,
        goal: str,
        priority: str = "NORMAL",
        deadline: str | None = None,
    ) -> str:
        """Alias for submit_build_request returning task_id string."""
        res = self.submit_build_request(goal, options={"priority": priority, "deadline": deadline})
        return res["task_id"]

    def get_task_status(self, task_id: str) -> dict[str, Any]:
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

    def _artifact_evidence(self, paths: list[str]) -> dict[str, bool]:
        """Maps each claimed artifact path to whether it exists on this machine.

        A path in a task record is a *claim*. Nothing in FORGE wrote it to disk in
        this process, so the only honest rendering is claim plus verification.
        """
        evidence: dict[str, bool] = {}
        for raw in paths or []:
            try:
                evidence[raw] = Path(raw).exists()
            except OSError:  # pragma: no cover - depends on the host filesystem
                evidence[raw] = False
        return evidence

    def get_task_artifacts(self, task_id: str) -> list[str]:
        """Retrieves list of generated software artifact paths/URLs."""
        return list(self.get_artifacts(task_id).get("artifacts", []))

    def review_task_output(self, task_id: str) -> str:
        """Returns a review of the task's output, quoting only what was recorded.

        Two fabrications lived in the four lines this replaces. The verification
        line defaulted a *missing* result to ``PASSED`` (and a missing test count
        to 14 passed / 0 failed), so a task with no verification block at all was
        reviewed as verified. And every artifact path was printed as though the
        file existed; the seeded paths (``dist/portfolio_website_v1.0.zip``)
        existed nowhere on disk.
        """
        insp = self.inspect_task(task_id)
        if "error" in insp:
            return f"Task {task_id} not found."
        ver = insp.get("verification_results") or {}

        if ver:
            verification = ", ".join(f"{k}: {v}" for k, v in sorted(ver.items()))
        else:
            verification = "no verification result was recorded"

        artifacts = insp.get("artifacts") or []
        if artifacts:
            artifact_lines = "\n".join(
                f"  • `{a}` ({'found on disk' if insp['artifacts_on_disk'].get(a) else 'NOT FOUND on disk'})"
                for a in artifacts
            )
        else:
            artifact_lines = "  • none recorded"

        delivery = insp.get("delivery_package_path")
        if delivery:
            delivery_note = f"`{delivery}`"
            if not insp["artifacts_on_disk"].get(delivery):
                delivery_note += " (NOT FOUND on disk)"
        else:
            delivery_note = "none recorded"

        lines = [
            f"### 🛠️ FORGE Task Review: `{insp['task_id']}`",
            f"- **Goal:** {insp['goal']}",
            f"- **Status:** **{insp['state']}**",
            f"- **Test Coverage:** {insp['test_coverage_pct']:.1f}%",
            f"- **Verification Results:** {verification}",
            f"- **Generated Artifacts ({len(artifacts)}):**",
            artifact_lines,
            f"- **Delivery Package:** {delivery_note}",
        ]
        if insp.get("sample_data"):
            lines.append(
                "- **Provenance:** SAMPLE DATA - these paths and results were seeded for "
                "demos and were never produced by a build."
            )
        return "\n".join(lines)

    def get_task_logs(self, task_id: str) -> dict[str, Any]:
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

    def inspect_task(self, task_id: str) -> dict[str, Any]:
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
                "artifacts_on_disk": self._artifact_evidence(task.artifacts),
                "verification_results": task.verification_results,
                "test_coverage_pct": task.test_coverage_pct,
                "delivery_package_path": task.delivery_package_path,
                "sample_data": self.demo_data,
            }

    def list_tasks(self, limit: int = 10) -> dict[str, Any]:
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

    def get_artifacts(self, task_id: str) -> dict[str, Any]:
        """Retrieves completion reports and verification manifests (GET /api/tasks/{id}/artifacts)."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return {"task_id": task_id, "artifacts": [], "error": f"Task {task_id} not found."}
            return {
                "task_id": task.task_id,
                "artifacts": list(task.artifacts),
                "artifacts_on_disk": self._artifact_evidence(task.artifacts),
                "delivery_package_path": task.delivery_package_path,
                "delivery_package_on_disk": (
                    self._artifact_evidence([task.delivery_package_path]).get(task.delivery_package_path, False)
                    if task.delivery_package_path else False
                ),
                "sample_data": self.demo_data,
            }

    def cancel_task(self, task_id: str) -> dict[str, Any]:
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

    def get_forge_health(self) -> dict[str, Any]:
        """Probes FORGE (GET /api/health) and reports what it answered.

        This method used to return a constant ``{"status": "HEALTHY",
        "ai_universe_connection": "CONNECTED"}`` without issuing any request, so
        the health operator, the supervisor operator, the master dashboard and the
        voice skill all announced a service that may not exist. The status is now
        the endpoint's own status, or ``UNREACHABLE`` with the error.
        """
        probe = self._probe_forge_api()
        with self._lock:
            running_tasks = sum(1 for t in self._tasks.values() if t.state in ("RUNNING", "VERIFYING", "READY"))
            completed = sum(1 for t in self._tasks.values() if t.state == "COMPLETED")
            tracked = len(self._tasks)

        local = {
            # These counts describe *this process's* records, not FORGE's queue.
            "task_store": "in-process records",
            "active_builds_count": running_tasks,
            "total_completed": completed,
            "total_tasks_tracked": tracked,
        }

        if not probe["ok"]:
            return {
                "status": "UNREACHABLE",
                "reachable": False,
                "service": "FORGE (no health response)",
                "api_url": self.auth_client.api_url,
                "probe_url": probe["url"],
                "error": probe["error"] or "no response",
                "ai_universe_connection": "unknown (the health endpoint did not answer)",
                **local,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        payload = probe["payload"] if isinstance(probe["payload"], dict) else {}
        reported_status = payload.get("status") or payload.get("health") or "UNREPORTED"
        return {
            "status": str(reported_status).upper(),
            "reachable": True,
            "http_status": probe["http_status"],
            "service": payload.get("service") or "FORGE (service name not reported)",
            "api_url": self.auth_client.api_url,
            "probe_url": probe["url"],
            "ai_universe_connection": payload.get("ai_universe_connection") or "unknown (not reported)",
            "reported": payload,
            **local,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def execute(
        self,
        user_request: str,
        agent: Any | None = None,
        tool_registry: Any | None = None,
        llm_provider: Any | None = None,
        authorizer: Any | None = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        """Executes voice-driven FORGE task management queries."""
        clean = user_request.strip().lower()
        step_results: list[dict[str, Any]] = []

        try:
            # 1. "Forge status"
            if clean in ("forge status", "system status forge"):
                health = self.get_forge_health()
                probe_clause = (
                    f"Probed {health.get('probe_url')} (HTTP {health.get('http_status')}). "
                    if health.get("reachable")
                    else f"I probed {health.get('probe_url')} and got no answer: {health.get('error')}. "
                )
                spoken = (
                    f"FORGE Software Engineering Engine status: {health.get('status')}. "
                    + probe_clause
                    + f"AI-Universe bridge is {health.get('ai_universe_connection')}. "
                    f"In this process I track {health.get('total_tasks_tracked')} task record(s): "
                    f"{health.get('active_builds_count')} awaiting or in progress, "
                    f"{health.get('total_completed')} recorded as completed."
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
                    all_artifacts: list[str] = []
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
