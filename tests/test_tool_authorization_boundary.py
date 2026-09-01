"""Comprehensive regression test suite for ToolRegistry cryptographic authorization boundary.

Proves:
1. Direct ToolRegistry calls to SENSITIVE or DANGEROUS tools without capability are blocked.
2. Passing forged booleans (e.g. `allow_sensitive=True`) does not grant authorization.
3. Modifying arguments after authorization was granted fails execution (argument hash mismatch).
4. Mismatching tool name or tool call ID fails execution.
5. Replayed authorization capabilities are rejected (single-use guarantee).
6. Expired authorization capabilities are rejected (time-bounded).
7. Forged cryptographic signatures are rejected.
8. Legitimate authorization capabilities execute cleanly.
9. FridayAgent and TaskExecutionEngine execute tools securely via capabilities.
"""

import time

import pytest

from friday.agent.agent import FridayAgent
from friday.agent.executor import TaskExecutionEngine
from friday.agent.planner import PlanStep, StepStatus, TaskPlan
from friday.core.auth import (
    AutoApproveAuthorizer,
    AutoDenyAuthorizer,
)
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    SafetyLevel,
    ToolCall,
    ToolResult,
)
from friday.llm.mock_provider import MockLLMProvider
from friday.security.authorization import (
    ToolAuthorizer,
)
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry


class DummyProtectedTool(BaseTool):
    name = "delete_database"
    description = "Deletes database tables"
    safety_level = SafetyLevel.DANGEROUS
    parameters = {
        "type": "object",
        "properties": {
            "target": {"type": "string"},
            "force": {"type": "boolean"},
        },
        "required": ["target"],
    }

    def execute(self, target: str, force: bool = False) -> ToolResult:
        return ToolResult(
            name=self.name,
            content=f"Database '{target}' deleted successfully (force={force}).",
            is_error=False,
            safety_level=self.safety_level,
        )


class DummySafeTool(BaseTool):
    name = "get_system_time"
    description = "Returns the current system timestamp"
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {},
    }

    def execute(self) -> ToolResult:
        return ToolResult(
            name=self.name,
            content="2026-08-21T01:00:00Z",
            is_error=False,
            safety_level=self.safety_level,
        )


@pytest.fixture
def test_registry():
    reg = ToolRegistry()
    reg.register(DummyProtectedTool())
    reg.register(DummySafeTool())
    return reg


@pytest.fixture
def fresh_authorizer():
    return ToolAuthorizer(default_ttl_seconds=10.0)


def test_safe_tool_executes_without_capability(test_registry):
    """SAFE tools execute freely without requiring an explicit capability."""
    res = test_registry.execute("get_system_time", {})
    assert not res.is_error
    assert "2026-08-21" in res.content


def test_protected_tool_blocked_without_capability(test_registry):
    """Direct ToolRegistry execution of DANGEROUS/SENSITIVE tool without capability is blocked."""
    res = test_registry.execute("delete_database", {"target": "prod_users"})
    assert res.is_error
    assert "Safety Block" in res.content
    assert "requires a valid ToolAuthorizationCapability" in res.content


def test_forged_boolean_cannot_bypass_authorization(test_registry):
    """Passing allow_sensitive=True as kwargs/boolean flag cannot bypass authorization."""
    res = test_registry.execute(
        "delete_database",
        {"target": "prod_users"},
        allow_sensitive=True,  # Legacy forged boolean
    )
    assert res.is_error
    assert "Safety Block" in res.content
    assert "requires a valid ToolAuthorizationCapability" in res.content


def test_legitimate_capability_executes_successfully(test_registry, fresh_authorizer):
    """Valid cryptographic capability allows protected tool execution."""
    args = {"target": "test_db", "force": True}
    cap = fresh_authorizer.issue_capability(
        tool_name="delete_database",
        arguments=args,
        safety_level=SafetyLevel.DANGEROUS,
        tool_call_id="call_12345",
    )

    res = test_registry.execute(
        name="delete_database",
        arguments=args,
        tool_call_id="call_12345",
        authorization=cap,
        authorizer=fresh_authorizer,
    )
    assert not res.is_error
    assert "Database 'test_db' deleted successfully" in res.content


def test_modified_arguments_fail_execution(test_registry, fresh_authorizer):
    """Modifying arguments after authorization was issued is detected and blocked."""
    authorized_args = {"target": "staging_db", "force": False}
    cap = fresh_authorizer.issue_capability(
        tool_name="delete_database",
        arguments=authorized_args,
        safety_level=SafetyLevel.DANGEROUS,
    )

    # Attacker tries to execute against production DB instead
    tampered_args = {"target": "production_db", "force": True}
    res = test_registry.execute(
        name="delete_database",
        arguments=tampered_args,
        authorization=cap,
        authorizer=fresh_authorizer,
    )
    assert res.is_error
    assert "Safety Block" in res.content
    assert "altered after authorization" in res.content


def test_tool_name_mismatch_fails_execution(test_registry, fresh_authorizer):
    """Capability issued for one tool cannot be used on another tool."""
    cap = fresh_authorizer.issue_capability(
        tool_name="other_tool",
        arguments={"target": "test_db"},
        safety_level=SafetyLevel.DANGEROUS,
    )

    res = test_registry.execute(
        name="delete_database",
        arguments={"target": "test_db"},
        authorization=cap,
        authorizer=fresh_authorizer,
    )
    assert res.is_error
    assert "Safety Block" in res.content
    assert "tool mismatch" in res.content


def test_tool_call_id_mismatch_fails_execution(test_registry, fresh_authorizer):
    """Capability bound to a tool_call_id cannot be used with a different tool call ID."""
    args = {"target": "test_db"}
    cap = fresh_authorizer.issue_capability(
        tool_name="delete_database",
        arguments=args,
        safety_level=SafetyLevel.DANGEROUS,
        tool_call_id="legitimate_call_id",
    )

    res = test_registry.execute(
        name="delete_database",
        arguments=args,
        tool_call_id="spoofed_call_id",
        authorization=cap,
        authorizer=fresh_authorizer,
    )
    assert res.is_error
    assert "Safety Block" in res.content
    assert "tool_call_id mismatch" in res.content


def test_replayed_capability_fails_execution(test_registry, fresh_authorizer):
    """Replaying an already-consumed capability is blocked (single-use guarantee)."""
    args = {"target": "test_db"}
    cap = fresh_authorizer.issue_capability(
        tool_name="delete_database",
        arguments=args,
        safety_level=SafetyLevel.DANGEROUS,
    )

    # 1. First execution succeeds
    res1 = test_registry.execute(
        name="delete_database",
        arguments=args,
        authorization=cap,
        authorizer=fresh_authorizer,
    )
    assert not res1.is_error

    # 2. Second execution (replay) fails
    res2 = test_registry.execute(
        name="delete_database",
        arguments=args,
        authorization=cap,
        authorizer=fresh_authorizer,
    )
    assert res2.is_error
    assert "Safety Block" in res2.content
    assert "replay attack detected" in res2.content


def test_expired_capability_fails_execution(test_registry):
    """Expired capability cannot be used."""
    short_lived_authorizer = ToolAuthorizer(default_ttl_seconds=0.01)
    args = {"target": "test_db"}
    cap = short_lived_authorizer.issue_capability(
        tool_name="delete_database",
        arguments=args,
        safety_level=SafetyLevel.DANGEROUS,
        ttl_seconds=0.01,
    )

    # Wait for expiry
    time.sleep(0.05)

    res = test_registry.execute(
        name="delete_database",
        arguments=args,
        authorization=cap,
        authorizer=short_lived_authorizer,
    )
    assert res.is_error
    assert "Safety Block" in res.content
    assert "expired" in res.content


def test_forged_signature_fails_execution(test_registry, fresh_authorizer):
    """Capability with tampered signature is rejected."""
    args = {"target": "test_db"}
    cap = fresh_authorizer.issue_capability(
        tool_name="delete_database",
        arguments=args,
        safety_level=SafetyLevel.DANGEROUS,
    )
    cap.signature = "0123456789abcdef" * 4

    res = test_registry.execute(
        name="delete_database",
        arguments=args,
        authorization=cap,
        authorizer=fresh_authorizer,
    )
    assert res.is_error
    assert "Safety Block" in res.content
    assert "Forged or corrupted" in res.content


def test_agent_end_to_end_authorized_tool_execution(test_registry):
    """FridayAgent integrates with authorizer to issue capability and execute protected tool."""
    agent = FridayAgent(
        llm_provider=MockLLMProvider(),
        tool_registry=test_registry,
        authorizer=AutoApproveAuthorizer.create_for_testing(allow_dangerous=True),
    )

    # Agent executes a single tool call
    tc = ToolCall(
        id="call_agent_test",
        name="delete_database",
        arguments={"target": "agent_test_db"},
    )
    res = agent._execute_single_tool_call(tc)
    assert not res.is_error
    assert "Database 'agent_test_db' deleted successfully" in res.content


def test_agent_end_to_end_denied_tool_execution(test_registry):
    """FridayAgent respects AutoDenyAuthorizer and does not execute protected tool."""
    agent = FridayAgent(
        llm_provider=MockLLMProvider(),
        tool_registry=test_registry,
        authorizer=AutoDenyAuthorizer(),
    )

    tc = ToolCall(
        id="call_agent_denied",
        name="delete_database",
        arguments={"target": "agent_test_db"},
    )
    res = agent._execute_single_tool_call(tc)
    assert res.is_error
    assert "Authorization Block" in res.content


def test_task_execution_engine_end_to_end(test_registry):
    """TaskExecutionEngine issues capability through authorizer and executes step."""
    engine = TaskExecutionEngine(
        tool_registry=test_registry,
        authorizer=AutoApproveAuthorizer.create_for_testing(allow_dangerous=True),
    )

    plan = TaskPlan(
        goal="Clean up old test DB",
        steps=[
            PlanStep(
                step_id="step_1",
                description="Delete test db",
                tool_name="delete_database",
                parameters={"target": "engine_test_db"},
            )
        ],
    )

    result = engine.execute_plan(plan)
    assert result.success
    assert "step_1" in result.step_results
    assert result.step_results["step_1"].status == StepStatus.SUCCEEDED


def test_auto_approve_rejected_without_explicit_ack():
    """AutoApproveAuthorizer cannot be instantiated without explicit test acknowledgement."""
    from friday.core.exceptions import SecurityError
    with pytest.raises(SecurityError) as exc:
        AutoApproveAuthorizer()
    assert "strictly test-only" in str(exc.value)


def test_auto_approve_rejected_in_production_environment(monkeypatch):
    """AutoApproveAuthorizer is completely rejected in production environment."""
    from friday.core.exceptions import SecurityError
    monkeypatch.setenv("FRIDAY_ENV", "production")
    with pytest.raises(SecurityError) as exc:
        AutoApproveAuthorizer.create_for_testing(allow_dangerous=True)
    assert "strictly prohibited in production" in str(exc.value)


def test_auto_approve_blocks_dangerous_actions_by_default():
    """AutoApproveAuthorizer blocks DANGEROUS actions unless allow_dangerous_for_testing=True."""
    authz = AutoApproveAuthorizer.create_for_testing(allow_dangerous=False)
    req = AuthorizationRequest(
        tool_name="delete_database",
        safety_level=SafetyLevel.DANGEROUS,
        arguments={"target": "test_db"},
    )
    resp = authz.authorize(req)
    assert resp.decision == AuthorizationDecision.DENIED
    assert "safety guard: DANGEROUS tool" in resp.reason
