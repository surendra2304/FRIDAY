"""Phase 5.10 — Voice Tool Execution Security Hardening Tests.

Verifies:
A. Tool arguments are NOT emitted verbatim into logs.
B. Fake secret passed as tool argument is redacted or omitted.
C. Safe tool execution still works correctly.
D. Sensitive authorization still works.
E. Dangerous tool blocking still works.
F. Multiple function calls remain correctly correlated.
G. Voice tool failures return safe structured errors.
H. Existing text tool execution behavior is unchanged.
"""

import asyncio
import logging
from unittest import mock
import pytest

from friday.core.logging import redact_tool_args
from friday.core.types import (
    SafetyLevel,
    ToolCall,
    ToolResult,
)
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry
from friday.voice.gemini_live_session import GeminiLiveVoiceSession


# ---------------------------------------------------------------------------
# Helper stubs
# ---------------------------------------------------------------------------

class SafeEchoTool(BaseTool):
    name = "safe_echo"
    description = "Echo the input back safely"
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
    }
    def execute(self, message: str = "", **kwargs) -> ToolResult:
        return ToolResult(name=self.name, content=f"Echo: {message}", is_error=False)


class SensitiveTool(BaseTool):
    name = "sensitive_action"
    description = "Requires authorization"
    safety_level = SafetyLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {"target": {"type": "string"}},
        "required": ["target"],
    }
    def execute(self, target: str = "", **kwargs) -> ToolResult:
        return ToolResult(name=self.name, content=f"Sensitive: {target}", is_error=False)


class DangerousTool(BaseTool):
    name = "dangerous_delete"
    description = "Dangerous delete"
    safety_level = SafetyLevel.DANGEROUS
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    def execute(self, path: str = "", **kwargs) -> ToolResult:
        return ToolResult(name=self.name, content=f"Deleted: {path}", is_error=False)


class BurstFailTool(BaseTool):
    name = "burst_fail_tool"
    description = "Always raises"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {}}
    def execute(self, **kwargs) -> ToolResult:
        raise RuntimeError("Simulated burst failure")


class FakeFC:
    def __init__(self, name: str, call_id: str, args: dict):
        self.name = name
        self.id = call_id
        self.args = args


def _make_session(agent=None) -> GeminiLiveVoiceSession:
    with mock.patch.dict("os.environ", {"FRIDAY_GEMINI_API_KEY": "TEST_KEY_UNIT_TEST"}):
        return GeminiLiveVoiceSession(api_key="TEST_KEY_UNIT_TEST", agent=agent)


def _make_agent(registry: ToolRegistry, authorizer=None):
    from friday.core.auth import AutoApproveAuthorizer, DefaultSecureAuthorizer
    from unittest.mock import MagicMock
    from friday.agent.agent import FridayAgent
    agent = MagicMock()
    agent.tools = registry
    agent.authorizer = authorizer or DefaultSecureAuthorizer()
    agent.memory = None
    agent.conversation_id = None
    agent._processed_tool_ids = set()
    agent._execute_single_tool_call = lambda tc: FridayAgent._execute_single_tool_call_internal(agent, tc)
    return agent


# ---------------------------------------------------------------------------
# A. Tool arguments NOT logged verbatim
# ---------------------------------------------------------------------------

def test_A_raw_args_not_logged():
    """Secret values must not appear verbatim after redact_tool_args."""
    redacted = redact_tool_args({"expression": "12345 * 6789", "secret": "s3cr3t-value"})
    assert "s3cr3t-value" not in str(redacted)
    assert redacted.get("secret") == "[REDACTED]"


# ---------------------------------------------------------------------------
# B. Fake secret in tool arg is redacted
# ---------------------------------------------------------------------------

def test_B_fake_secret_argument_redacted():
    args = {
        "password": "SuperSecret@123",
        "api_key": "AIza" + "Sy" + "FakeKeyHere",
        "token": "eyJhbGciOiJSUzI1NiJ9.fake",
        "expression": "1+1",
        "limit": 10,
    }
    redacted = redact_tool_args(args)
    assert redacted["password"] == "[REDACTED]"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["token"] == "[REDACTED]"
    assert redacted["limit"] == 10
    assert redacted["expression"] == "1+1"


# ---------------------------------------------------------------------------
# C. Safe tool execution still works
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_C_safe_tool_execution_works():
    from friday.core.auth import AutoApproveAuthorizer
    registry = ToolRegistry()
    registry.register(SafeEchoTool())
    agent = _make_agent(registry, AutoApproveAuthorizer())
    session = _make_session(agent=agent)
    fc = FakeFC("safe_echo", "call_echo_1", {"message": "hello world"})
    resp = await session._execute_tool_call(fc)
    assert resp.name == "safe_echo"
    assert resp.id == "call_echo_1"
    assert "Echo: hello world" in resp.response.get("output", "")


# ---------------------------------------------------------------------------
# D. Sensitive authorization gating
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_D_sensitive_authorization_blocks_without_approval():
    from friday.core.auth import DefaultSecureAuthorizer
    registry = ToolRegistry()
    registry.register(SensitiveTool())
    agent = _make_agent(registry, DefaultSecureAuthorizer())
    session = _make_session(agent=agent)
    fc = FakeFC("sensitive_action", "call_sens_1", {"target": "user_data"})
    resp = await session._execute_tool_call(fc)
    output = resp.response.get("output", "") + resp.response.get("error", "")
    assert (
        "Execution error" in output
        or "rejected" in output.lower()
        or "block" in output.lower()
        or "Authorization" in output
    )


# ---------------------------------------------------------------------------
# E. Dangerous tool blocking
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_E_dangerous_tool_blocked():
    from friday.core.auth import DefaultSecureAuthorizer
    registry = ToolRegistry()
    registry.register(DangerousTool())
    agent = _make_agent(registry, DefaultSecureAuthorizer())
    session = _make_session(agent=agent)
    fc = FakeFC("dangerous_delete", "call_danger_1", {"path": "/etc/hosts"})
    resp = await session._execute_tool_call(fc)
    output = resp.response.get("output", "") + resp.response.get("error", "")
    assert "Deleted" not in output
    assert (
        "Execution error" in output
        or "block" in output.lower()
        or "rejected" in output.lower()
        or "Authorization" in output
    )


# ---------------------------------------------------------------------------
# F. Multiple function calls correctly correlated
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_F_multiple_function_calls_correlated():
    from friday.core.auth import AutoApproveAuthorizer
    registry = ToolRegistry()
    registry.register(SafeEchoTool())
    agent = _make_agent(registry, AutoApproveAuthorizer())
    session = _make_session(agent=agent)
    fcs = [FakeFC("safe_echo", f"call_multi_{i}", {"message": f"msg-{i}"}) for i in range(5)]
    responses = await asyncio.gather(*[session._execute_tool_call(fc) for fc in fcs])
    for i, resp in enumerate(responses):
        assert resp.id == f"call_multi_{i}"
        assert resp.name == "safe_echo"
        assert f"msg-{i}" in resp.response.get("output", "")


# ---------------------------------------------------------------------------
# G. Voice tool failures return safe structured errors
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_G_tool_failure_returns_safe_structured_error():
    from friday.core.auth import AutoApproveAuthorizer
    registry = ToolRegistry()
    registry.register(BurstFailTool())
    agent = _make_agent(registry, AutoApproveAuthorizer())
    session = _make_session(agent=agent)
    fc = FakeFC("burst_fail_tool", "call_fail_1", {})
    resp = await session._execute_tool_call(fc)
    output = resp.response.get("output", "")
    assert "Execution error" in output or "error" in resp.response
    assert "Traceback" not in output


# ---------------------------------------------------------------------------
# H. Existing text tool execution path unchanged
# ---------------------------------------------------------------------------

def test_H_registry_text_path_unchanged():
    registry = ToolRegistry()
    registry.register(SafeEchoTool())
    result = registry.execute("safe_echo", {"message": "canonical text path"}, allow_sensitive=False)
    assert not result.is_error
    assert "canonical text path" in result.content


def test_H_registry_logs_no_raw_arg_values(caplog):
    registry = ToolRegistry()
    registry.register(SafeEchoTool())
    with caplog.at_level(logging.INFO, logger="friday"):
        registry.execute("safe_echo", {"message": "do-not-log-this-value"}, allow_sensitive=False)
    full_log = caplog.text
    assert "do-not-log-this-value" not in full_log
    assert "safe_echo" in full_log


# ---------------------------------------------------------------------------
# redact_tool_args edge cases
# ---------------------------------------------------------------------------

def test_redact_tool_args_non_dict_input():
    out = redact_tool_args("not a dict")  # type: ignore[arg-type]
    assert out.get("_redacted") is True


def test_redact_tool_args_truncates_excess_keys():
    large = {f"key_{i}": i for i in range(12)}
    out = redact_tool_args(large, max_keys=5)
    assert "_truncated" in out
    assert len(out) <= 6


def test_redact_tool_args_safe_scalars_pass_through():
    args = {"limit": 10, "threshold": 0.75, "enabled": True}
    out = redact_tool_args(args)
    assert out["limit"] == 10
    assert out["threshold"] == 0.75
    assert out["enabled"] is True
