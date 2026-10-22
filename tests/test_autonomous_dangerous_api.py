"""A scripted user request must not turn autonomous mode into dangerous approval."""

from __future__ import annotations

from fastapi.testclient import TestClient

from friday.agent.agent import FridayAgent
from friday.api import server
from friday.core import config
from friday.core.auth import DefaultSecureAuthorizer
from friday.core.config import Settings
from friday.core.types import Message, Role, SafetyLevel, ToolCall, ToolResult
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry


class DangerousProbeTool(BaseTool):
    name = "dangerous_probe"
    description = "A local probe that must not execute without dangerous confirmation."
    safety_level = SafetyLevel.DANGEROUS
    parameters = {
        "type": "object",
        "properties": {"label": {"type": "string"}},
        "required": ["label"],
    }

    def __init__(self) -> None:
        self.execution_count = 0

    def execute(self, label: str = "", **_kwargs) -> ToolResult:
        self.execution_count += 1
        return ToolResult(name=self.name, content=f"Executed dangerous probe: {label}", is_error=False)


class ScriptedDangerousProvider:
    """Issue one local tool call, then report only the resulting evidence."""

    def __init__(self) -> None:
        self.issued = False

    def __call__(self, messages, tools):
        if not self.issued:
            available = {item.get("function", {}).get("name") for item in (tools or [])}
            assert "dangerous_probe" in available
            self.issued = True
            return Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(
                        id="api-dangerous-probe-1",
                        name="dangerous_probe",
                        arguments={"label": "must-not-run"},
                    )
                ],
            )
        return Message(role=Role.ASSISTANT, content="The dangerous operation was not completed.")


def test_api_request_cannot_execute_dangerous_tool_in_privileged_modes(monkeypatch) -> None:
    settings = Settings(_env_file=None, env="testing", autonomous_mode=True, full_access_mode=True)
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    monkeypatch.setitem(server.app.dependency_overrides, server._require_control_access, lambda: None)

    tool = DangerousProbeTool()
    tools = ToolRegistry()
    tools.register(tool)
    agent = FridayAgent(
        settings=settings,
        llm_provider=MockLLMProvider(custom_responder=ScriptedDangerousProvider()),
        memory=InMemoryConversationMemory(),
        tool_registry=tools,
        authorizer=DefaultSecureAuthorizer(),
        max_tool_iterations=2,
    )
    monkeypatch.setattr(server, "agent", agent)

    response = TestClient(server.app).post(
        "/api/command",
        json={"command": "please run the protected administrative probe"},
    )

    assert response.status_code == 403, response.text
    assert tool.execution_count == 0
    assert response.json()["metadata"]["authorization_denied"] is True
