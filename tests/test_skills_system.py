"""Comprehensive test suite for the OpenJarvis-inspired Skills System and Capability Gating."""

from typing import Any

from friday.agent.agent import FridayAgent
from friday.agent.state import TaskState
from friday.agents.registry import AgentRegistry
from friday.agents.router import AgentRouter
from friday.core.config import Settings
from friday.core.types import SafetyLevel
from friday.security.authorization import ToolAuthorizer
from friday.skills.base_skill import BaseSkill, SkillExecutionResult
from friday.skills.builtins.network_diagnostic import NetworkDiagnosticSkill
from friday.skills.builtins.system_health_audit import SystemHealthAuditSkill
from friday.skills.registry import SkillRegistry
from friday.tools.base import BaseTool


class DummyEchoTool(BaseTool):
    name = "dummy_echo"
    description = "Echo tool"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]}

    def execute(self, msg: str = "", **kwargs: Any):
        from friday.core.types import ToolResult
        return ToolResult(name=self.name, content=f"Echo: {msg}", is_error=False, safety_level=self.safety_level)


class CustomTestSkill(BaseSkill):
    name = "custom_test_skill"
    description = "Custom test macro skill"
    required_capabilities = ["custom_cap_alpha", "file_read"]
    tools = ["dummy_echo"]
    match_patterns = [r"\brun\s+custom\s+skill\b", r"\bexecute\s+custom\s+macro\b"]

    def execute(self, user_request: str, **kwargs: Any) -> SkillExecutionResult:
        return SkillExecutionResult(
            skill_name=self.name,
            success=True,
            output="Custom skill executed successfully.",
            step_results=[{"step": 1, "status": "ok"}],
        )


def test_base_skill_properties_and_matching():
    """Verify BaseSkill match score, pattern matching, and serialization."""
    skill = CustomTestSkill()
    assert skill.name == "custom_test_skill"
    assert skill.can_handle("Please run custom skill now") is True
    assert skill.can_handle("Unrelated prompt") is False
    assert skill.match_score("run custom skill") >= 0.9

    data = skill.to_dict()
    assert data["name"] == "custom_test_skill"
    assert "custom_cap_alpha" in data["required_capabilities"]


def test_skill_registry_crud_and_builtins():
    """Test registering, unregistering, looking up, and finding matching skills in SkillRegistry."""
    registry = SkillRegistry()
    assert len(registry.list_skills()) == 0

    custom = CustomTestSkill()
    registry.register(custom)
    assert registry.get("custom_test_skill") is custom
    assert len(registry.list_skills()) == 1

    matched = registry.find_matching_skill("execute custom macro")
    assert matched is not None
    skill, score = matched
    assert skill.name == "custom_test_skill"
    assert score >= 0.9

    # Unregister
    assert registry.unregister("custom_test_skill") is True
    assert registry.get("custom_test_skill") is None
    assert registry.find_matching_skill("execute custom macro") is None

    # Load builtins
    registry.load_builtins()
    assert registry.get("network_diagnostic") is not None
    assert registry.get("system_health_audit") is not None
    assert registry.get("file_search_and_read") is not None


def test_capability_gating_authorizer_permit():
    """Capability gating approves skills with permitted capabilities."""
    authorizer = ToolAuthorizer()
    is_auth, reason = authorizer.check_skill_capabilities(
        skill_name="test_skill",
        required_capabilities=["file_read", "network_access"],
        environment="development",
    )
    assert is_auth is True
    assert "permitted" in reason


def test_capability_gating_authorizer_explicit_block():
    """Capability gating strictly rejects skills with blocked capabilities."""
    authorizer = ToolAuthorizer()
    is_auth, reason = authorizer.check_skill_capabilities(
        skill_name="dangerous_skill",
        required_capabilities=["file_read", "destructive_shell"],
        blocked_capabilities={"destructive_shell"},
    )
    assert is_auth is False
    assert "destructive_shell" in reason
    assert "blocked" in reason


def test_capability_gating_authorizer_environment_variable(monkeypatch):
    """Capability gating respects FRIDAY_BLOCKED_CAPABILITIES environment variable."""
    monkeypatch.setenv("FRIDAY_BLOCKED_CAPABILITIES", "shell_exec,unrestricted_admin")
    authorizer = ToolAuthorizer()

    # Network diagnostic requires shell_exec -> Should be rejected
    is_auth, reason = authorizer.check_skill_capabilities(
        skill_name="network_diagnostic",
        required_capabilities=["shell_exec", "network_access"],
    )
    assert is_auth is False
    assert "shell_exec" in reason
    assert "blocked" in reason

    # Skill with safe file_read -> Approved
    is_auth, reason = authorizer.check_skill_capabilities(
        skill_name="file_reader_skill",
        required_capabilities=["file_read"],
    )
    assert is_auth is True


def test_capability_gating_allowed_whitelist():
    """Capability gating enforces allowed capabilities whitelist."""
    authorizer = ToolAuthorizer()
    is_auth, reason = authorizer.check_skill_capabilities(
        skill_name="custom_skill",
        required_capabilities=["file_read", "ui_automation"],
        allowed_capabilities={"file_read"},  # ui_automation is missing
    )
    assert is_auth is False
    assert "ui_automation" in reason


def test_agent_autonomous_skill_execution():
    """Agent automatically matches registered skill and executes its tool chain autonomously."""
    reg = SkillRegistry()
    reg.register(CustomTestSkill())

    agent = FridayAgent(
        settings=Settings(env="testing"),
        skill_registry=reg,
    )

    response = agent.process_message("Please run custom skill for me")
    assert response.is_done is True
    assert response.content == "Custom skill executed successfully."
    assert response.metadata["skill_name"] == "custom_test_skill"
    assert response.metadata["skill_executed"] is True
    assert response.metadata["success"] is True
    assert agent.state_machine.current_state == TaskState.COMPLETED


def test_agent_skill_execution_blocked_by_capability_gating(monkeypatch):
    """When a skill required capability is blocked, agent halts and reports capability gating rejection."""
    monkeypatch.setenv("FRIDAY_BLOCKED_CAPABILITIES", "custom_cap_alpha")

    reg = SkillRegistry()
    reg.register(CustomTestSkill())

    agent = FridayAgent(
        settings=Settings(env="testing"),
        skill_registry=reg,
    )

    response = agent.process_message("run custom skill")
    assert response.is_done is True
    assert "Skill execution blocked" in response.content
    assert "custom_cap_alpha" in response.content
    assert response.metadata["skill_blocked"] is True
    assert response.metadata["success"] is False
    assert agent.state_machine.current_state == TaskState.FAILED


def test_builtin_network_diagnostic_skill_execution():
    """Test built-in NetworkDiagnosticSkill execution."""
    skill = NetworkDiagnosticSkill()
    assert skill.can_handle("Diagnose the network connectivity") is True

    res = skill.execute(user_request="Diagnose network")
    assert isinstance(res, SkillExecutionResult)
    assert res.skill_name == "network_diagnostic"
    assert len(res.output) > 0


def test_builtin_system_health_audit_skill_execution():
    """Test built-in SystemHealthAuditSkill execution."""
    skill = SystemHealthAuditSkill()
    assert skill.can_handle("audit system health and performance") is True

    res = skill.execute(user_request="audit system health")
    assert isinstance(res, SkillExecutionResult)
    assert res.skill_name == "system_health_audit"
    assert res.success is True
    assert "System Health Audit Report" in res.output


def test_router_integration_with_skill_registry():
    """AgentRouter integrates with SkillRegistry and finds matching skills."""
    skill_reg = SkillRegistry()
    skill_reg.register(CustomTestSkill())

    agent_reg = AgentRegistry()
    router = AgentRouter(registry=agent_reg, skill_registry=skill_reg)

    matched = router.find_matching_skill("run custom skill")
    assert matched is not None
    skill, score = matched
    assert skill.name == "custom_test_skill"
    assert score >= 0.9

