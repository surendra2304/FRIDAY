"""Tests for ECC Built-in Skills in FRIDAY.

Validates:
1. CodeReviewSkill
2. VerificationLoopSkill
3. AgentShieldSkill
4. InstinctManagementSkill
"""

from unittest.mock import MagicMock

from friday.skills.builtins import (
    AgentShieldSkill,
    CodeReviewSkill,
    InstinctManagementSkill,
    VerificationLoopSkill,
)
from friday.tools.registry import ToolRegistry


def test_code_review_skill_can_handle_and_execute():
    skill = CodeReviewSkill()
    assert skill.name == "code_review"
    assert skill.can_handle("Please review the code in src/friday/agent.py") is True
    assert skill.can_handle("Can you do a code review on this pull request?") is True
    assert skill.can_handle("What is the current time?") is False

    mock_tool_registry = MagicMock(spec=ToolRegistry)
    mock_tool_registry.get.return_value = None

    result = skill.execute("Review src/test.py", tool_registry=mock_tool_registry)
    assert result.skill_name == "code_review"
    assert result.success is True


def test_verification_loop_skill_can_handle_and_execute():
    skill = VerificationLoopSkill()
    assert skill.name == "verification_loop"
    assert skill.can_handle("Run the verification loop") is True
    assert skill.can_handle("Execute pytest suite") is True
    assert skill.can_handle("Show me today's news") is False

    mock_tool_registry = MagicMock(spec=ToolRegistry)
    mock_run_tool = MagicMock()
    mock_run_tool.execute.return_value = MagicMock(content="5 passed in 0.2s", success=True)
    mock_tool_registry.get.return_value = mock_run_tool

    result = skill.execute("Run verification", tool_registry=mock_tool_registry)
    assert result.skill_name == "verification_loop"
    assert result.success is True
    assert "PASSED" in result.output


def test_agent_shield_skill_can_handle_and_execute():
    skill = AgentShieldSkill()
    assert skill.name == "agent_shield"
    assert skill.can_handle("Run security scan") is True
    assert skill.can_handle("Audit system security") is True
    assert skill.can_handle("What is the weather today?") is False

    result = skill.execute("Run security scan", target_dir="tests")
    assert result.skill_name == "agent_shield"
    assert "AGENTSHIELD AUDIT REPORT" in result.output
    assert "grade" in result.step_results[0]


def test_instinct_management_skill_can_handle_and_execute(tmp_path):
    skill = InstinctManagementSkill()
    assert skill.name == "instinct_management"
    assert skill.can_handle("Show learned instincts") is True
    assert skill.can_handle("Continuous learning status") is True
    assert skill.can_handle("Export instincts") is True
    assert skill.can_handle("Hello assistant") is False

    from friday.learning.instinct_engine import InstinctEngine
    engine = InstinctEngine(storage_path=str(tmp_path / "instincts.json"))
    engine.learn_from_feedback("task A", "action A", "testing", "success")

    result = skill.execute("Show instincts", instinct_engine=engine)
    assert result.skill_name == "instinct_management"
    assert result.success is True
    assert "Continuous Learning Instinct Engine" in result.output
    assert "TESTING" in result.output
