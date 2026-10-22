"""Drive detection-only repair through FridayAgent with an offline scripted provider."""

from __future__ import annotations

from typing import Any

import pytest

from friday.agent.agent import FridayAgent
from friday.core.config import Settings
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationResponse,
    Message,
    Role,
    ToolCall,
)
from friday.llm.mock_provider import MockLLMProvider
from friday.tools.registry import tool_authorizer


class DryRunPlanner:
    def __init__(self) -> None:
        self.calls = 0
        self.visible_tools: set[str] = set()
        self.tool_results: list[str] = []

    def __call__(self, messages: list[Message], tools: list[dict[str, Any]] | None) -> Message:
        self.calls += 1
        self.visible_tools = {
            item.get("function", {}).get("name", "") for item in (tools or [])
        }
        self.tool_results.extend(
            message.content or "" for message in messages if message.role == Role.TOOL
        )
        if self.calls == 1:
            return Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(
                        id="self-repair-dry-run-1",
                        name="self_repair",
                        arguments={"scope": "tests", "dry_run": True},
                    )
                ],
            )
        return Message(
            role=Role.ASSISTANT,
            content="Detection-only result: " + (self.tool_results[-1] if self.tool_results else "no tool result"),
        )


class LocalApprover:
    """Issue a real test capability bound to this one locally approved tool call."""

    def __init__(self) -> None:
        self.approved: list[str] = []

    def authorize(self, request: Any) -> AuthorizationResponse:
        self.approved.append(request.tool_name)
        capability = tool_authorizer.issue_capability(
            tool_name=request.tool_name,
            arguments=request.arguments,
            safety_level=request.safety_level,
            tool_call_id=request.tool_call_id or "",
            purpose=request.purpose or "offline regression",
        )
        return AuthorizationResponse(
            decision=AuthorizationDecision.APPROVED,
            reason="approved only for this offline regression",
            capability=capability,
        )


def test_user_requested_dry_run_never_enters_reflex_repair_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from friday.cognition import reflex
    from friday.cognition.reflex import Incident, IncidentKind, IncidentSeverity

    incident = Incident(
        kind=IncidentKind.TEST_FAILURE,
        severity=IncidentSeverity.HIGH,
        source="tests/test_example.py::test_case",
        summary="a scripted test failure",
    )

    class Detector:
        includes: list[Any] = []

        async def scan(self, *, include: Any = None) -> list[Incident]:
            self.includes.append(include)
            return [incident]

    class GuardedBrain:
        def __init__(self) -> None:
            self.detector = Detector()
            self.repair_calls = 0

        async def run_once(self, *, include: Any = None) -> dict[str, Any]:
            self.repair_calls += 1
            raise AssertionError("the scripted dry-run must not invoke repair handlers")

    brain = GuardedBrain()
    monkeypatch.setattr(reflex, "get_reflex_brain", lambda *args, **kwargs: brain)
    planner = DryRunPlanner()
    approver = LocalApprover()
    agent = FridayAgent(
        settings=Settings(env="testing", llm_provider="mock", embedding_provider="none"),
        llm_provider=MockLLMProvider(custom_responder=planner),
        authorizer=approver,
        max_tool_iterations=2,
    )

    response = agent.process_message("Check for test failures with a dry-run self-repair.")

    assert "self_repair" in planner.visible_tools
    assert approver.approved == ["self_repair"]
    assert brain.detector.includes == [{IncidentKind.TEST_FAILURE}]
    assert brain.repair_calls == 0
    assert "[DRY_RUN]" in response.content
    assert "no repair handler was invoked" in response.content.lower()
