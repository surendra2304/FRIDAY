"""Tests for ECC Verification Workflow in FRIDAY.

Validates:
1. VerificationWorkflow trigger matching.
2. End-to-end execution of the 6-stage engineering cycle:
   PLAN -> TEST -> IMPLEMENT -> REVIEW -> VERIFY -> REMEMBER
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from friday.learning.instinct_engine import InstinctEngine
from friday.tools.registry import ToolRegistry
from friday.workflows.verification_workflow import VerificationWorkflow


@pytest.mark.asyncio
async def test_verification_workflow_can_handle():
    workflow = VerificationWorkflow()
    assert workflow.can_handle("Run full cycle implementation of feature X") is True
    assert workflow.can_handle("Execute plan test implement cycle") is True
    assert workflow.can_handle("Verify and remember this improvement") is True
    assert workflow.can_handle("What is the stock price of Apple?") is False


@pytest.mark.asyncio
async def test_verification_workflow_execute_cycle_success(tmp_path: Path):
    storage = str(tmp_path / "instincts.json")
    engine = InstinctEngine(storage_path=storage)
    tool_registry = MagicMock(spec=ToolRegistry)

    mock_run_tool = MagicMock()
    mock_run_tool.execute.return_value = MagicMock(content="All 10 tests passed", success=True)
    tool_registry.get.return_value = mock_run_tool

    workflow = VerificationWorkflow(
        tool_registry=tool_registry,
        instinct_engine=engine,
    )

    with patch.object(workflow.verification_loop, "execute") as mock_v_exec:
        from friday.skills.base_skill import SkillExecutionResult
        mock_v_exec.return_value = SkillExecutionResult(
            skill_name="verification_loop",
            success=True,
            output="All 10 tests passed",
        )

        result = await workflow.execute_cycle("implement secure session token hashing")

        assert result["success"] is True
        assert len(result["stages"]) == 6

        stages = [s["stage"] for s in result["stages"]]
        assert stages == ["PLAN", "TEST", "IMPLEMENT", "REVIEW", "VERIFY", "REMEMBER"]

        # Verify that instinct was synthesized during REMEMBER
        remember_stage = result["stages"][-1]
        assert remember_stage["status"] == "COMPLETED"
        assert len(engine.list_instincts()) >= 1
