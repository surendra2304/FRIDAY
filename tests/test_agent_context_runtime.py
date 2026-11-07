"""Versioned per-agent context must stay isolated in autonomous dispatch."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from friday.api import server
from friday.autonomous import daemon as daemon_module
from friday.autonomous.daemon import AutonomousDaemon
from friday.autonomous.enhanced_controller import (
    EnhancedAutonomousController,
    ExecutionPlan,
    SubTask,
)


def test_goal_api_accepts_only_the_versioned_agent_context_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    context = {
        "contract": "friday-agent-context/v1",
        "by_agent": {
            "intelx": {
                "private_memories": ["INTELX_PRIVATE_NOTE"],
                "verified_repair_lessons": ["INTELX_REPAIR_LESSON"],
            },
            "futuris": {
                "private_memories": ["FUTURIS_PRIVATE_NOTE"],
                "verified_repair_lessons": [],
            },
        },
        "handoff_policy": "verified_predecessor_result_and_evidence_only",
    }

    class GoalCapture:
        is_running = True

        def submit_goal(
            self,
            goal_text: str,
            priority: int,
            metadata: dict | None,
            execution_context: dict | None,
        ):
            self.submitted = (goal_text, priority, metadata, execution_context)
            return SimpleNamespace(
                id="test-goal",
                goal=goal_text,
                priority=priority,
                status="QUEUED",
            )

    capture = GoalCapture()
    monkeypatch.setattr(server, "autonomous_daemon", capture)
    client = TestClient(server.app)

    accepted = client.post(
        "/api/autonomous/goals",
        json={"goal": "Run a two-specialist test.", "execution_context": context},
    )
    assert accepted.status_code == 200, accepted.text
    assert capture.submitted[3] == context

    rejected = client.post(
        "/api/autonomous/goals",
        json={
            "goal": "Reject an unknown contract.",
            "execution_context": {**context, "contract": "friday-agent-context/v2"},
        },
    )
    assert rejected.status_code == 422


@pytest.mark.asyncio
async def test_runtime_dispatches_only_matching_private_context_and_completed_handoffs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    goal_text = "\n".join(
        [
            "Run a controlled multi-agent exercise.",
            "Shared context:",
            "- SHARED_TEAM_NOTE",
            "If the requested work cannot be completed as approved, stop and report what is blocked.",
            "Owner request:",
            "Use only synthetic data.",
        ]
    )
    execution_context = {
        "contract": "friday-agent-context/v1",
        "by_agent": {
            "intelx": {
                "private_memories": ["INTELX_PRIVATE_NOTE"],
                "verified_repair_lessons": ["INTELX_REPAIR_LESSON"],
            },
            "futuris": {
                "private_memories": ["FUTURIS_PRIVATE_NOTE"],
                "verified_repair_lessons": ["FUTURIS_REPAIR_LESSON"],
            },
            "forge": {
                "private_memories": ["FORGE_PRIVATE_NOTE"],
                "verified_repair_lessons": [],
            },
            "unassigned": {
                "private_memories": ["UNASSIGNED_PRIVATE_NOTE"],
                "verified_repair_lessons": [],
            },
        },
        "handoff_policy": "verified_predecessor_result_and_evidence_only",
    }

    plan = ExecutionPlan(goal=goal_text)
    plan.add_subtask(SubTask(id="research", description="Research synthetic evidence.", agent="INTELX"))
    plan.add_subtask(
        SubTask(
            id="forecast",
            description="Estimate using the completed research.",
            agent="FUTURIS",
            dependencies=["research"],
        )
    )
    plan.add_subtask(SubTask(id="independent", description="Review a separate sample.", agent="FORGE"))

    controller = EnhancedAutonomousController()
    captured: dict[str, str] = {}

    async def fake_dispatch(agent: str, directive: str):
        captured[agent.lower()] = directive
        if agent.lower() == "intelx":
            return {
                "status": "COMPLETED",
                "result": "VERIFIED_RESEARCH_RESULT",
                "evidence": [
                    {
                        "type": "SOURCE",
                        "label": "SYNTHETIC_SOURCE_LABEL",
                        "url": "https://example.invalid/source",
                        "detail": "Synthetic test evidence.",
                        "not_handoff_data": "UNRELATED_EVIDENCE_FIELD",
                    }
                ],
                "internal": "INTERNAL_RESPONSE_METADATA",
            }
        return {"status": "COMPLETED", "result": f"{agent.upper()}_RESULT", "evidence": []}

    monkeypatch.setattr(controller, "_dispatch_to_agent", fake_dispatch)
    monkeypatch.setattr(controller, "_record_action", lambda *_args: None)
    monkeypatch.setattr(controller, "decompose_goal", lambda _goal: plan)

    async def no_synthesis(*_args, **_kwargs) -> str:
        return ""

    monkeypatch.setattr(daemon_module, "synthesize_answer", no_synthesis)
    daemon = AutonomousDaemon()
    daemon.controller = controller
    daemon._persistence_path = tmp_path / "goals.json"
    goal = daemon.submit_goal(
        goal_text,
        execution_context=execution_context,
    )
    await daemon._start_goal(goal)

    for _ in range(300):
        if goal.status != "RUNNING":
            break
        await asyncio.sleep(0.01)
    assert goal.status == "COMPLETED"
    assert goal.execution_context == {}
    assert set(captured) == {"intelx", "futuris", "forge"}

    intelx_prompt = captured["intelx"]
    assert "INTELX_PRIVATE_NOTE" in intelx_prompt
    assert "INTELX_REPAIR_LESSON" in intelx_prompt
    assert "FUTURIS_PRIVATE_NOTE" not in intelx_prompt
    assert "FORGE_PRIVATE_NOTE" not in intelx_prompt
    assert "UNASSIGNED_PRIVATE_NOTE" not in intelx_prompt
    assert "SHARED_TEAM_NOTE" in intelx_prompt

    futuris_prompt = captured["futuris"]
    assert "FUTURIS_PRIVATE_NOTE" in futuris_prompt
    assert "FUTURIS_REPAIR_LESSON" in futuris_prompt
    assert "INTELX_PRIVATE_NOTE" not in futuris_prompt
    assert "INTELX_REPAIR_LESSON" not in futuris_prompt
    assert "FORGE_PRIVATE_NOTE" not in futuris_prompt
    assert "UNASSIGNED_PRIVATE_NOTE" not in futuris_prompt
    assert "SHARED_TEAM_NOTE" in futuris_prompt
    assert "VERIFIED_RESEARCH_RESULT" in futuris_prompt
    assert "SYNTHETIC_SOURCE_LABEL" in futuris_prompt
    assert "predecessor_step_id" in futuris_prompt
    assert "predecessor_agent_id" in futuris_prompt
    assert "INTERNAL_RESPONSE_METADATA" not in futuris_prompt
    assert "UNRELATED_EVIDENCE_FIELD" not in futuris_prompt

    forge_prompt = captured["forge"]
    assert "FORGE_PRIVATE_NOTE" in forge_prompt
    assert "INTELX_PRIVATE_NOTE" not in forge_prompt
    assert "FUTURIS_PRIVATE_NOTE" not in forge_prompt
    assert "VERIFIED_RESEARCH_RESULT" not in forge_prompt
    assert "SHARED_TEAM_NOTE" in forge_prompt

    running_predecessor = SubTask(
        id="not-done",
        description="Not completed.",
        agent="INTELX",
        status="RUNNING",
        result="UNFINISHED_RESULT",
    )
    downstream = SubTask(
        id="downstream",
        description="Wait for completion.",
        agent="FUTURIS",
        dependencies=["not-done"],
    )
    unverified_plan = ExecutionPlan(goal="Wait.", subtasks=[running_predecessor, downstream])
    assert controller._dependency_context(downstream, unverified_plan) == ""
