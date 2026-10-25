"""
FRIDAY/apps/core/src/friday_core/agent_runtime.py — FRIDAY Agent Runtime.

This is the wiring layer that makes the new deep engines usable by the running
agent instead of sitting in a corner of the repository:

* ``FridayAgentRuntime`` drives FRIDAY's task execution with the harness engine
  (planning, permission-gated tool use, verification, checkpointing, tracing)
  and the browser automation engine (indexed page understanding + goal runs).
* ``router`` exposes the same capabilities as HTTP endpoints so the API server,
  the mesh gateway and FRIDAY's own dashboards can call them.
* ``MEMORY_HOOK`` gives the runtime a durable memory: every completed task is
  committed to Memora's ``viking://`` context database when a database is
  attached, and prior relevant context is recalled before planning.

Nothing here is decorative: the orchestrator's workflows call
``FridayAgentRuntime.execute`` / ``.browse`` / ``.verify`` directly, and
``friday_core.real_deep_api_server`` mounts ``router``.
"""
from __future__ import annotations

import importlib.util
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .real_browser_agent import (
    BrowserAutomationEngine,
    SensitiveDataGuard,
    SitePage,
)
from .real_harness_engineering import (
    AgentLoop,
    Check,
    ContextBudget,
    ContextCompactor,
    HarnessBlueprint,
    HARNESS_PRIMITIVES,
    LoopAction,
    LoopStep,
    Message,
    PermissionGate,
    PermissionRule,
    StateStore,
    Tracer,
    VerificationLoop,
    default_registry,
    estimate_tokens,
)

try:  # pragma: no cover - exercised only when FastAPI is installed
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel, Field

    _ROUTER_AVAILABLE = True
except Exception:  # pragma: no cover - keeps the runtime importable without FastAPI
    APIRouter = None  # type: ignore[assignment]
    HTTPException = None  # type: ignore[assignment]
    BaseModel = object  # type: ignore[assignment]

    def Field(*_args: Any, **_kwargs: Any) -> Any:  # type: ignore[misc]
        return None

    _ROUTER_AVAILABLE = False


ROOT = Path(__file__).resolve().parents[5]
VK_PATH = ROOT / "Memora" / "core" / "memory" / "real_viking_context.py"


# ── Memory bridge ─────────────────────────────────────────────────────────

def load_viking_module() -> Any | None:
    """Load Memora's viking context database without importing the whole app."""
    if "friday_viking_context" in sys.modules:
        return sys.modules["friday_viking_context"]
    if not VK_PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location("friday_viking_context", VK_PATH)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules["friday_viking_context"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # pragma: no cover - defensive: memory must never break tasks
        sys.modules.pop("friday_viking_context", None)
        return None
    return module


@dataclass
class RuntimeMemory:
    """Durable task memory backed by Memora's ``viking://user/friday`` subtree."""

    database: Any
    user: str = "friday"
    session: Any = None

    @property
    def root(self) -> str:
        return f"viking://user/{self.user}"

    def begin_session(self) -> Any:
        self.session = self.database.open_session(self.user)
        return self.session

    def remember_turn(self, role: str, content: str) -> None:
        if self.session is None:
            self.begin_session()
        self.session.add(role, content)

    def commit(self) -> dict[str, Any]:
        if self.session is None:
            return {"committed": False, "reason": "no open session"}
        result = self.database.commit_session(self.session)
        self.session = None
        return {"committed": True, **result.as_dict()}

    def recall(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        hits = self.database.search(query, root=self.root, level="L1", limit=limit)
        return [hit.as_dict() for hit in hits]


# ── Runtime ───────────────────────────────────────────────────────────────

@dataclass
class ExecutionStep:
    """A single tool call FRIDAY should perform."""

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def as_action(self) -> LoopAction:
        return LoopAction(kind="tool", tool=self.tool, arguments=dict(self.arguments))


@dataclass
class ExecutionResult:
    task: str
    ok: bool
    stop_reason: str
    observations: list[str]
    tokens_used: int
    denied: int
    approvals: list[str] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "ok": self.ok,
            "stop_reason": self.stop_reason,
            "observations": list(self.observations),
            "tokens_used": self.tokens_used,
            "denied": self.denied,
            "approvals": list(self.approvals),
            "verification": self.verification,
            "trace": self.trace,
            "plan": self.plan,
        }


class FridayAgentRuntime:
    """The task runtime FRIDAY's orchestrator and API delegate to."""

    def __init__(
        self,
        workspace: dict[str, str] | None = None,
        budget: ContextBudget | None = None,
        memory: RuntimeMemory | None = None,
        rules: Iterable[PermissionRule] | None = None,
    ) -> None:
        self.registry = default_registry(workspace or {})
        self.gate = PermissionGate(rules, registry=self.registry)
        self.approvals = _ApprovalLog()
        self.budget = budget or ContextBudget()
        self.state = StateStore()
        self.tracer = Tracer()
        self.browser = BrowserAutomationEngine()
        self.guard = SensitiveDataGuard()
        self.memory = memory
        self._blueprint = HarnessBlueprint()

    # -- planning ---------------------------------------------------------
    def plan(self, goal: str, steps: Iterable[str | dict[str, Any]]) -> dict[str, Any]:
        plan = self._decomposer().decompose(goal, steps)
        return plan.as_dict()

    @staticmethod
    def _decomposer():
        from .real_harness_engineering import TaskDecomposer

        return TaskDecomposer()

    def recall_context(self, goal: str, limit: int = 3) -> list[dict[str, Any]]:
        if self.memory is None:
            return []
        return self.memory.recall(goal, limit=limit)

    # -- execution --------------------------------------------------------
    def execute(
        self,
        task: str,
        steps: Iterable[ExecutionStep | dict[str, Any]],
        checks: Iterable[Check] | None = None,
        max_steps: int = 12,
        remember: bool = True,
    ) -> ExecutionResult:
        """Run a scripted tool sequence through the guarded agent loop."""
        sequence = [self._coerce(step) for step in steps]
        plan = self.plan(task, [f"{step.tool}" for step in sequence] or ["no-op"])
        recalled = self.recall_context(task)
        cursor = {"index": 0}

        def policy(_task: str, history: list[LoopStep]) -> LoopAction:
            if cursor["index"] >= len(sequence):
                return LoopAction(kind="respond", text=_summarise(history))
            step = sequence[cursor["index"]]
            cursor["index"] += 1
            return step.as_action()

        with self.tracer.span("friday.execute", task=task[:80],
                              planned_steps=len(sequence)) as span:
            loop = AgentLoop(registry=self.registry, gate=self.gate,
                             approvals=self.approvals.queue, max_steps=max_steps,
                             budget=self.budget.available())
            result = loop.run(task, policy)
            span.attributes["stop_reason"] = result.stop_reason
            span.attributes["tokens"] = result.tokens_used

        verification: dict[str, Any] = {}
        if checks:
            artifact = "\n".join(result.observations())
            verification = VerificationLoop(list(checks)).run(artifact).as_dict()

        checkpoint = self.state.save(len(self.state) + 1, {
            "task": task,
            "stop_reason": result.stop_reason,
            "observations": result.observations(),
            "ok": result.succeeded,
        })

        if self.memory is not None and remember:
            self.memory.remember_turn("user", task)
            if result.observations():
                self.memory.remember_turn("assistant", result.observations()[-1])

        outcome = ExecutionResult(
            task=task,
            ok=result.succeeded and verification.get("passed", True),
            stop_reason=result.stop_reason,
            observations=result.observations(),
            tokens_used=result.tokens_used,
            denied=result.denials,
            approvals=[request.request_id for request in result.approvals],
            verification=verification,
            trace=self.tracer.trace.summary(),
            plan=plan,
        )
        outcome.plan["recalled_context"] = [hit["uri"] for hit in recalled]
        if not outcome.ok and checkpoint is not None:
            outcome.plan["checkpoint"] = checkpoint.checkpoint_id
        return outcome

    def verify(self, artifact: str, checks: Iterable[Check],
               revise: Callable[[str, list[str]], str] | None = None) -> dict[str, Any]:
        return VerificationLoop(list(checks)).run(artifact, revise).as_dict()

    def compact(self, messages: Iterable[dict[str, Any]] | Iterable[Message],
                strategy: str = "summarise", query: str = "") -> dict[str, Any]:
        converted = [
            message if isinstance(message, Message)
            else Message(message.get("role", "user"), message.get("content", ""),
                         bool(message.get("pinned", False)))
            for message in messages
        ]
        result = ContextCompactor(self.budget, strategy=strategy).compact_until_fits(
            converted, query)
        payload = result.as_dict()
        payload["messages"] = [message.as_dict() for message in result.messages]
        return payload

    # -- browsing ---------------------------------------------------------
    def browse(self, pages: Iterable[SitePage | dict[str, Any]], goal: str,
               start_url: str = "", max_steps: int = 10) -> dict[str, Any]:
        site_pages = [self._page(page) for page in pages]
        with self.tracer.span("friday.browse", goal=goal[:80],
                              pages=len(site_pages)) as span:
            result = self.browser.run_goal(site_pages, goal, start_url=start_url,
                                           max_steps=max_steps)
            span.attributes["success"] = bool(result.get("success"))
        if self.memory is not None:
            self.memory.remember_turn("tool", f"browse: {goal} -> {result.get('final_url', '')}")
        return result

    @staticmethod
    def _page(page: SitePage | dict[str, Any]) -> SitePage:
        if isinstance(page, SitePage):
            return page
        return SitePage(
            url=page["url"],
            title=page.get("title", page["url"]),
            spec=page.get("spec", {"tag": "body", "children": []}),
            doc_height=float(page.get("doc_height", 1800.0)),
            requires_auth=bool(page.get("requires_auth", False)),
        )

    @staticmethod
    def _coerce(step: ExecutionStep | dict[str, Any]) -> ExecutionStep:
        if isinstance(step, ExecutionStep):
            return step
        return ExecutionStep(tool=step.get("tool", ""),
                             arguments=dict(step.get("arguments") or {}))

    # -- memory -----------------------------------------------------------
    def commit_memory(self) -> dict[str, Any]:
        if self.memory is None:
            return {"committed": False, "reason": "memory not attached"}
        return self.memory.commit()

    def memory_root(self) -> str:
        return self.memory.root if self.memory else ""

    # -- introspection ----------------------------------------------------
    def capabilities(self) -> dict[str, Any]:
        return {
            "agent": "FRIDAY",
            "capabilities": [
                "task_planning", "agent_harness", "harness_execution",
                "tool_permissions", "output_verification", "context_compaction",
                "browser_automation", "run_tracing", "checkpointing",
            ],
            "primitives": [key for key, _, _ in HARNESS_PRIMITIVES],
            "tools": self.registry.names(),
            "context_window": self.budget.window,
            "memory_root": self.memory_root(),
            "self_assessment": self._blueprint.audit([
                "agent-loop", "planning", "context-assembly", "compaction",
                "tool-design", "permissions", "memory", "orchestration",
                "verification", "observability", "debugging",
                "human-in-the-loop", "evaluation",
            ]).as_dict(),
        }

    def token_estimate(self, text: str) -> int:
        return estimate_tokens(text)


class _ApprovalLog:
    """Minimal approval queue facade so the runtime can report escalations."""

    def __init__(self) -> None:
        from .real_harness_engineering import HumanApprovalQueue

        self.queue = HumanApprovalQueue()

    def pending(self) -> list[dict[str, Any]]:
        return [request.as_dict() for request in self.queue.pending()]

    def resolve(self, request_id: str, approved: bool, approver: str = "operator"
                ) -> dict[str, Any]:
        return self.queue.resolve(request_id, approved, approver).as_dict()


def _summarise(history: Iterable[LoopStep]) -> str:
    last = list(history)[-1:] if history else []
    if not last:
        return "no actions executed"
    return f"completed {len(list(history))} step(s); last observation: {last[0].observation}"


# ── HTTP surface ──────────────────────────────────────────────────────────

if _ROUTER_AVAILABLE:

    class PlanRequest(BaseModel):  # type: ignore[misc]
        goal: str = Field(min_length=1)
        steps: list[str] = Field(default_factory=list)

    class StepModel(BaseModel):  # type: ignore[misc]
        tool: str = Field(min_length=1)
        arguments: dict[str, Any] = Field(default_factory=dict)

    class ExecuteRequest(BaseModel):  # type: ignore[misc]
        task: str = Field(min_length=1)
        steps: list[StepModel] = Field(default_factory=list)
        files: dict[str, str] = Field(default_factory=dict)
        max_steps: int = Field(default=12, ge=1, le=50)

    class CompactRequest(BaseModel):  # type: ignore[misc]
        messages: list[dict[str, Any]] = Field(default_factory=list)
        strategy: str = "summarise"
        query: str = ""

    class BrowsePage(BaseModel):  # type: ignore[misc]
        url: str
        title: str = ""
        spec: dict[str, Any] = Field(default_factory=dict)
        doc_height: float = 1800.0
        requires_auth: bool = False

    class BrowseRequest(BaseModel):  # type: ignore[misc]
        goal: str = Field(min_length=1)
        pages: list[BrowsePage] = Field(default_factory=list)
        start_url: str = ""
        max_steps: int = Field(default=10, ge=1, le=40)

    router = APIRouter(prefix="/v1/agent", tags=["FRIDAY Agent Runtime"])
    _RUNTIME = FridayAgentRuntime()

    @router.get("/capabilities")
    def capabilities() -> dict[str, Any]:
        return _RUNTIME.capabilities()

    @router.post("/plan")
    def plan(request: PlanRequest) -> dict[str, Any]:
        try:
            return _RUNTIME.plan(request.goal, request.steps or ["execute"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/execute")
    def execute(request: ExecuteRequest) -> dict[str, Any]:
        runtime = FridayAgentRuntime(workspace=request.files) if request.files else _RUNTIME
        result = runtime.execute(
            request.task,
            [{"tool": step.tool, "arguments": step.arguments} for step in request.steps],
            max_steps=request.max_steps,
        )
        return result.as_dict()

    @router.post("/context/compact")
    def compact(request: CompactRequest) -> dict[str, Any]:
        try:
            return _RUNTIME.compact(request.messages, request.strategy, request.query)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/browser/run")
    def browser_run(request: BrowseRequest) -> dict[str, Any]:
        pages = [page.model_dump() for page in request.pages]
        if not pages:
            raise HTTPException(status_code=422, detail="at least one page is required")
        return _RUNTIME.browse(pages, request.goal, start_url=request.start_url,
                               max_steps=request.max_steps)

    @router.get("/trace")
    def trace() -> dict[str, Any]:
        return _RUNTIME.tracer.trace.summary()

else:  # pragma: no cover
    router = None


def build_memory_runtime(user: str = "friday") -> RuntimeMemory | None:
    """Attach a viking context database if Memora is available on disk."""
    module = load_viking_module()
    if module is None:
        return None
    return RuntimeMemory(database=module.ContextDatabase(user=user), user=user)


def default_runtime() -> FridayAgentRuntime:
    return FridayAgentRuntime(memory=build_memory_runtime())


__all__ = [
    "ExecutionResult",
    "ExecutionStep",
    "FridayAgentRuntime",
    "RuntimeMemory",
    "build_memory_runtime",
    "default_runtime",
    "estimate_tokens",
    "load_viking_module",
    "router",
]
