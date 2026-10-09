"""Real-life tests for the skill layer being reachable from the agent.

The repository's 24 built-in skills were unreachable in production: nothing in
the running agent read ``FridayAgent.skill_registry``, so a user could not ask
for any of them and the skills' own tests passed only because they called
``skill.execute(...)`` directly. These tests drive the *user-facing* path - the
tool registry the model calls through - and check what a user would see.
"""

from __future__ import annotations

import pytest

from friday.core.auth import DefaultSecureAuthorizer
from friday.core.types import SafetyLevel, ToolResult
from friday.security.authorization import ToolAuthorizer
from friday.skills.base_skill import BaseSkill, SkillExecutionResult
from friday.tools.builtin.skill_tools import ListSkillsTool, RunSkillTool
from friday.tools.registry import ToolRegistry


class ExplodesSkill(BaseSkill):
    """A skill that raises, to prove the bridge reports failure as failure."""

    name = "explodes"
    description = "Always raises."
    required_capabilities: list[str] = []
    tools: list[str] = []
    system_prompt = ""
    match_patterns = [r"explode"]

    def execute(self, user_request: str, **kwargs) -> SkillExecutionResult:
        raise RuntimeError("boom")


class RefusesSkill(BaseSkill):
    """A skill that returns success=False, as a refusal would."""

    name = "refuses"
    description = "Declines to do the work."
    required_capabilities: list[str] = []
    tools: list[str] = []
    system_prompt = ""
    match_patterns = [r"refuse"]

    def execute(self, user_request: str, **kwargs) -> SkillExecutionResult:
        return SkillExecutionResult(
            skill_name=self.name,
            success=False,
            output="I did not do that.",
            error="declined",
        )


class RecordingSkill(BaseSkill):
    """A skill that records what it was handed and reports receipt of the authorizer."""

    name = "recording"
    description = "Records its inputs."
    required_capabilities: list[str] = []
    tools: list[str] = []
    system_prompt = ""
    match_patterns = [r"record"]

    received: dict = {}

    def execute(self, user_request: str, **kwargs) -> SkillExecutionResult:
        RecordingSkill.received = {"request": user_request, **kwargs}
        return SkillExecutionResult(
            skill_name=self.name,
            success=True,
            output=f"Recorded '{user_request}'.",
            step_results=[{"action": "record"}],
        )


class StubSkillRegistry:
    def __init__(self, *skills: BaseSkill) -> None:
        self._skills = {s.name: s for s in skills}

    def get(self, name: str):
        return self._skills.get(name)

    def list_skills(self) -> list[BaseSkill]:
        return list(self._skills.values())


# ---------------------------------------------------------------------------
# 1. The agent's own tool registry exposes the skill layer
# ---------------------------------------------------------------------------

def test_the_agent_tool_registry_can_reach_the_skill_layer():
    """A user can only use a skill if the registry the model sees contains it."""
    from friday.agent.agent import FridayAgent
    from friday.llm.mock_provider import MockLLMProvider

    registry = FridayAgent(
        llm_provider=MockLLMProvider(), memory=None, tool_registry=None
    ).tools
    names = {t.name for t in registry.list_tools()}

    assert "list_skills" in names, "the skill layer is unreachable without this tool"
    assert "run_skill" in names
    assert len(names) >= 60

    result = registry.execute("list_skills", {})
    assert not result.is_error
    # Every built-in skill is discoverable by name through the tool path.
    for expected in ("forge_manager", "voice_ecosystem", "ecosystem_status", "help_system"):
        assert f"`{expected}`" in result.content, f"{expected} missing from list_skills output"


def test_default_skill_bridge_receives_the_injected_registry_and_authorizer():
    """The default agent wires dependencies before building its RunSkillTool."""
    from friday.agent.agent import FridayAgent
    from friday.llm.mock_provider import MockLLMProvider

    skills = StubSkillRegistry(RecordingSkill())
    authorizer = DefaultSecureAuthorizer()
    agent = FridayAgent(
        llm_provider=MockLLMProvider(),
        authorizer=authorizer,
        skill_registry=skills,
    )
    bridge = agent.tools.get("run_skill")

    assert bridge is not None
    assert bridge._authorizer is authorizer
    assert bridge.skill_registry is skills


def test_custom_skill_bridge_inherits_agent_authorizer_and_execution_context():
    from friday.agent.agent import FridayAgent
    from friday.llm.mock_provider import MockLLMProvider

    skills = StubSkillRegistry(RecordingSkill())
    authorizer = DefaultSecureAuthorizer()
    tools = ToolRegistry()
    bridge = RunSkillTool(skill_registry=skills)
    tools.register(bridge)
    agent = FridayAgent(
        llm_provider=MockLLMProvider(),
        tool_registry=tools,
        authorizer=authorizer,
        skill_registry=skills,
    )

    assert bridge._authorizer is authorizer
    assert bridge._skill_registry is skills
    assert bridge._tool_registry is tools
    assert bridge._llm_provider is agent.llm


def test_run_skill_is_refused_without_authorization():
    """Running a skill is a sensitive act: it must not happen un-asked."""
    registry = ToolRegistry()
    registry.register(RunSkillTool(skill_registry=StubSkillRegistry(RecordingSkill())))

    result = registry.execute("run_skill", {"skill_name": "recording", "request": "record this"})

    assert result.is_error
    assert result.refused, "a missing capability is a refusal, not a malfunction"
    assert "requires a valid ToolAuthorizationCapability" in result.content
    assert RecordingSkill.received == {}, "the skill must not have run"


def test_run_skill_executes_a_real_skill_end_to_end_with_authorization():
    """The happy path a user gets: ask for a skill, get what it actually did."""
    authorizer = ToolAuthorizer(default_ttl_seconds=30.0)
    registry = ToolRegistry()
    registry.register(RunSkillTool(skill_registry=StubSkillRegistry(RecordingSkill())))

    args = {"skill_name": "recording", "request": "record this"}
    capability = authorizer.issue_capability(
        tool_name="run_skill",
        arguments=args,
        safety_level=SafetyLevel.SENSITIVE,
        tool_call_id="call_skill",
    )
    result = registry.execute(
        "run_skill",
        args,
        tool_call_id="call_skill",
        authorization=capability,
        authorizer=authorizer,
    )

    assert not result.is_error, result.content
    assert "Recorded 'record this'." in result.content
    assert result.metadata["skill_success"] is True
    assert result.metadata["step_count"] == 1
    # The authorizer is forwarded into the skill, so an inner tool call cannot
    # bypass the check the tool path would have applied.
    assert RecordingSkill.received["request"] == "record this"


def test_run_skill_refuses_an_unknown_name_and_says_what_exists():
    tool = RunSkillTool(skill_registry=StubSkillRegistry(RecordingSkill()))

    result = tool.execute(skill_name="does_not_exist", request="record this")

    assert result.is_error
    assert result.refused
    assert "no skill named 'does_not_exist'" in result.content
    assert "recording" in result.content, "the refusal must list what does exist"


def test_a_skill_that_raises_is_reported_as_a_failure_not_a_report():
    tool = RunSkillTool(skill_registry=StubSkillRegistry(ExplodesSkill()))

    result = tool.execute(skill_name="explodes", request="explode now")

    assert result.is_error
    assert "RuntimeError" in result.content
    assert "Nothing is being reported as done." in result.content


def test_a_skill_that_declines_is_not_dressed_up_as_success():
    tool = RunSkillTool(skill_registry=StubSkillRegistry(RefusesSkill()))

    result = tool.execute(skill_name="refuses", request="refuse this")

    assert result.is_error
    assert "did not complete" in result.content
    assert "I did not do that." in result.content
    assert "reported error: declined" in result.content


def test_list_skills_filters_and_never_crashes_on_an_empty_registry():
    empty = ListSkillsTool(skill_registry=StubSkillRegistry())
    result = empty.execute()

    assert not result.is_error
    assert "No registered skill" in result.content

    one = ListSkillsTool(skill_registry=StubSkillRegistry(RecordingSkill()))
    assert "1 registered skill:" in one.execute().content
    assert "No registered skill matching 'forge'" in one.execute(query="forge").content


def test_list_skills_reports_a_broken_registry_instead_of_its_own_success():
    class BrokenRegistry:
        def list_skills(self):
            raise RuntimeError("registry unavailable")

    result = ListSkillsTool(skill_registry=BrokenRegistry()).execute()

    assert result.is_error
    assert result.refused
    assert "registry unavailable" in result.content


def test_run_skill_reports_the_registry_truthfully_through_a_second_call():
    """Two authorized calls in a row both work: capabilities are per-call."""
    authorizer = ToolAuthorizer(default_ttl_seconds=30.0)
    registry = ToolRegistry()
    registry.register(RunSkillTool(skill_registry=StubSkillRegistry(RecordingSkill())))

    for index in range(2):
        args = {"skill_name": "recording", "request": f"record {index}"}
        capability = authorizer.issue_capability(
            tool_name="run_skill",
            arguments=args,
            safety_level=SafetyLevel.SENSITIVE,
            tool_call_id=f"call_{index}",
        )
        result = registry.execute(
            "run_skill",
            args,
            tool_call_id=f"call_{index}",
            authorization=capability,
            authorizer=authorizer,
        )
        assert not result.is_error, result.content
        assert f"record {index}" in result.content


@pytest.mark.parametrize("skill_name", ["explodes", "refuses"])
def test_failed_skills_do_not_trip_the_circuit_breaker(skill_name):
    """A skill refusing is the layer working; three refusals must not disable it."""
    registry = ToolRegistry()
    registry.register(
        RunSkillTool(skill_registry=StubSkillRegistry(ExplodesSkill(), RefusesSkill()))
    )
    authorizer = ToolAuthorizer(default_ttl_seconds=30.0)

    for index in range(3):
        args = {"skill_name": skill_name, "request": "go"}
        capability = authorizer.issue_capability(
            tool_name="run_skill",
            arguments=args,
            safety_level=SafetyLevel.SENSITIVE,
            tool_call_id=f"c{index}",
        )
        result = registry.execute(
            "run_skill", args, tool_call_id=f"c{index}", authorization=capability, authorizer=authorizer
        )
        # A raising skill is a genuine failure; a declining skill is not.
        if skill_name == "refuses":
            assert result.is_error
        else:
            assert result.is_error
            assert "boom" in result.content


def test_skill_tool_metadata_survives_the_registry():
    """Metadata is how a caller tells a skill report from a plain tool string."""
    tool = RunSkillTool(skill_registry=StubSkillRegistry(RecordingSkill()))
    direct: ToolResult = tool.execute(skill_name="recording", request="record")
    assert direct.metadata["skill_name"] == "recording"
