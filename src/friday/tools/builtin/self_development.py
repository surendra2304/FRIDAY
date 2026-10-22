"""Real, registered tools for self-improvement and self-repair.

BUG-003 in the truth audit: the system prompt told the model, in the imperative,
that it MUST call ``SelfImprovementWorkflow`` and "call the workflow tool" — and
no such tool existed. ``SelfImprovementWorkflow`` was imported nowhere but its own
package ``__init__``, and ``SelfHealingWorkflow`` had zero references in the
entire codebase, tests included. Asking FRIDAY to gain a capability therefore
produced a phantom tool call, which is exactly the failure the owner reported:
ask for new work and it says it cannot.

These tools close that gap. They are ordinary :class:`BaseTool` implementations,
which means they appear in the model's schema list, they pass through the normal
authorisation path, and they are visible in ``/api/tools`` — no special casing.

Their behaviour is deliberately *honest about the pipeline* rather than a shortcut
around it. A self-development request ultimately produces code, and code reaches
this repository only through the same gate every other change uses: test evidence,
a signed review, and either the owner's approval or a standing mandate. So the
tool's job is to do the part that can be done without authority — understand the
request, locate the capability gap, synthesise a candidate, verify it — and then
report precisely which gate step it reached.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from typing import Any, ClassVar

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.self_development")


class SelfDevelopTool(BaseTool):
    """Extend FRIDAY's own capabilities: plan a change, synthesise code, verify it.

    Named ``self_develop`` rather than ``self_improve`` so the name reads as a
    verb a model can reason about, and aliased below for the workflow it wraps.
    """

    name = "self_develop"
    description = (
        "Add a new capability, tool, feature or module to FRIDAY's own codebase. "
        "Use this whenever the owner asks FRIDAY to gain an ability it does not "
        "have, to modify its own code, or to upgrade itself. It plans the change, "
        "writes the code, runs the tests, and reports exactly how far it got."
    )
    safety_level = SafetyLevel.SENSITIVE
    risk_level = "SENSITIVE"
    auth_requirement = "USER"
    def __init__(self, resolver: Any | None = None) -> None:
        # Injection keeps the real user-facing tool testable with an offline
        # provider and a scratch repository; production still builds the normal
        # resolver on first use.
        self._resolver = resolver

    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "request": {
                "type": "string",
                "description": "What FRIDAY should become able to do, in the owner's own words.",
            },
            "target_path": {
                "type": "string",
                "description": (
                    "Optional repository-relative file to change. Omit to let the planner choose "
                    "the right location."
                ),
            },
        },
        "required": ["request"],
    }

    def execute(self, request: str = "", target_path: str = "", **_: Any) -> ToolResult:
        if not request.strip():
            return ToolResult(
                name=self.name,
                content="A self-development request needs a description of the capability to add.",
                is_error=True,
                safety_level=self.safety_level,
            )

        try:
            resolver = self._resolver
            if resolver is None:
                from friday.cognition.capability import CapabilityResolver

                resolver = CapabilityResolver()
            resolution = resolver.resolve(request, target_path=target_path)
        except Exception as exc:  # a planner failure must not look like a refusal
            logger.exception("self_develop failed to plan")
            return ToolResult(
                name=self.name,
                content=(
                    f"I could not plan that change: {type(exc).__name__}: {exc}. "
                    "Nothing was written; the failure is in planning, not in the request."
                ),
                is_error=True,
                safety_level=self.safety_level,
            )

        return ToolResult(
            name=self.name,
            content=resolution.spoken_summary(),
            is_error=not resolution.plan_feasible,
            safety_level=self.safety_level,
            metadata=resolution.as_dict(),
        )


class SelfRepairTool(BaseTool):
    """Detect faults and optionally let the reflex brain handle them.

    This is the tool form of whatever the owner actually means by "fix yourself".
    Normal mode runs a real reflex pass and reports its outcomes. With ``dry_run``
    enabled, it invokes only the detector and never enters the repair handlers.
    """

    name = "self_repair"
    description = (
        "Detect faults in FRIDAY's own code, its runtime, or the agent fleet, and repair "
        "what can be proven fixed. Use this when the owner says 'fix yourself', 'self repair', "
        "'self heal', 'auto fix', or reports that something of yours is broken."
    )
    safety_level = SafetyLevel.SENSITIVE
    risk_level = "SENSITIVE"
    auth_requirement = "USER"
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "description": (
                    "Optional comma-separated subset of: imports, tests, fleet, resources, logs. "
                    "Omit to scan everything."
                ),
            },
            "dry_run": {
                "type": "boolean",
                "description": (
                    "Detect and report without applying anything. Useful to see the diagnosis "
                    "before granting autonomy."
                ),
            },
        },
        "required": [],
    }

    def execute(self, scope: str = "", dry_run: bool = False, **_: Any) -> ToolResult:
        try:
            from friday.cognition.reflex import get_reflex_brain, parse_incident_scope
        except Exception as exc:
            logger.exception("self_repair dependencies could not load")
            return ToolResult(
                name=self.name,
                content=(
                    f"The reflex system could not load: {type(exc).__name__}: {exc}. "
                    "No repair outcome is claimed."
                ),
                is_error=True,
                safety_level=self.safety_level,
            )

        scope = str(scope or "")
        try:
            selected = parse_incident_scope(scope)
        except ValueError as exc:
            return ToolResult(
                name=self.name,
                content=f"Invalid self-repair scope: {exc}. Nothing was scanned or changed.",
                is_error=True,
                refused=True,
                safety_level=self.safety_level,
                metadata={"scope": scope},
            )

        try:
            brain = get_reflex_brain()
            if dry_run:
                detector = getattr(brain, "detector", None)
                scan = getattr(detector, "scan", None)
                if not callable(scan):
                    raise RuntimeError("the reflex detector does not support a read-only scan")
                incidents = _run_coroutine(scan(include=selected))
                result = {
                    "status": "COMPLETED",
                    "incidents": len(incidents),
                    "acted_on": 0,
                    "skipped_recently_handled": 0,
                    "counts": {"DRY_RUN": len(incidents)} if incidents else {},
                    "outcomes": [
                        {
                            "incident": incident.as_dict(),
                            "status": "DRY_RUN",
                            "action": "none",
                            "detail": "Detected only; no repair handler was invoked.",
                            "evidence": incident.evidence,
                            "evidence_class": "dry_run_detection",
                        }
                        for incident in incidents
                    ],
                    "dry_run": True,
                    "detail": "Dry run: detection only; no repair handler was invoked.",
                }
            else:
                result = _run_coroutine(brain.run_once(include=selected))
        except Exception as exc:
            logger.exception("self_repair could not run")
            return ToolResult(
                name=self.name,
                content=(
                    f"The repair pass failed before producing a complete report: "
                    f"{type(exc).__name__}: {exc}. Checks or actions may have completed "
                    "before the failure; inspect the system before retrying. No completed "
                    "outcome is claimed."
                ),
                is_error=True,
                safety_level=self.safety_level,
            )

        return ToolResult(
            name=self.name,
            content=_render_pass(result),
            is_error=result.get("status") == "ERROR",
            safety_level=self.safety_level,
            metadata=result,
        )


def _run_coroutine(coro: Any) -> Any:
    """Run a coroutine from whichever thread and event-loop context we are in."""
    import asyncio as _asyncio

    try:
        _asyncio.get_running_loop()
    except RuntimeError:
        return _asyncio.run(coro)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_asyncio.run, coro).result()

def _render_pass(result: dict[str, Any]) -> str:
    """Render a reflex pass the way a person would say it out loud."""
    status = result.get("status")
    if status == "ERROR":
        return f"The repair pass failed before it could examine anything: {result.get('error')}"

    incidents = result.get("incidents", 0)
    if not incidents:
        if result.get("dry_run"):
            return "Dry run complete: no incidents were found, and no repair handler was invoked."
        return (
            "Everything I checked is healthy: no failing tests, no unimportable modules, "
            "no host pressure."
        )

    counts: dict[str, int] = result.get("counts") or {}
    if result.get("dry_run"):
        lines = [f"Dry run detected {incidents} fault(s); no repair handler was invoked."]
    else:
        lines = [f"I examined {incidents} fault(s) and acted on {result.get('acted_on', 0)}."]
    for outcome in result.get("outcomes", []):
        incident = outcome.get("incident", {})
        lines.append(f"- [{outcome.get('status')}] {incident.get('summary', '')}")
        lines.append(f"  {outcome.get('detail', '')}")
    if counts.get("AWAITING_MANDATE"):
        lines.append(
            "Some repairs were proven and are waiting on your authority. Grant standing autonomy "
            "with `friday --grant-autonomy`, or approve them individually."
        )
    return "\n".join(lines)


def register(registry: Any) -> list[str]:
    """Register both tools. Available for callers that build their own registry."""
    registered: list[str] = []
    for tool in (SelfDevelopTool(), SelfRepairTool()):
        registry.register(tool)
        registered.append(tool.name)
    return registered


#: Tool classes exposed at import time, so the package's ``__init__`` can collect
#: them the same way it collects every other builtin.
TOOLS = (SelfDevelopTool, SelfRepairTool)
