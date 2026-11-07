import asyncio

import pytest
from fastapi import HTTPException

from friday.autonomous.daemon import AutonomousDaemon, AutonomousGoal
from friday.autonomous.enhanced_controller import (
    EnhancedAutonomousController,
    ExecutionPlan,
    SubTask,
)


class BlockingController:
    def __init__(self):
        self.started = asyncio.Event()
        self.cleanup_started = asyncio.Event()
        self.allow_cleanup = asyncio.Event()
        self.cleanup_finished = asyncio.Event()

    def decompose_goal(self, goal: str) -> ExecutionPlan:
        plan = ExecutionPlan(goal=goal, plan_id="plan_safe_cancel_test")
        plan.add_subtask(
            SubTask(
                id="step_safe_cancel_test",
                description="Wait without external side effects",
                agent="INFERENCE",
            )
        )
        return plan

    async def execute_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cleanup_started.set()
            await self.allow_cleanup.wait()
            self.cleanup_finished.set()
            raise


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    monkeypatch.setattr(AutonomousDaemon, "_load_state", lambda self: None)
    result = AutonomousDaemon()
    result._persistence_path = tmp_path / "goals.json"
    return result


@pytest.mark.asyncio
async def test_running_goal_is_not_cancelled_until_execution_cleanup_finishes(daemon):
    controller = BlockingController()
    daemon.controller = controller
    goal = AutonomousGoal(id="goal_safe_cancel_test", goal="Wait safely")

    await daemon._start_goal(goal)
    await asyncio.wait_for(controller.started.wait(), timeout=1)

    stop = asyncio.create_task(daemon.cancel_goal(goal.id))
    await asyncio.wait_for(controller.cleanup_started.wait(), timeout=1)

    assert goal.status == "RUNNING"
    assert not stop.done()

    controller.allow_cleanup.set()
    payload = await asyncio.wait_for(stop, timeout=1)

    assert controller.cleanup_finished.is_set()
    assert payload["status"] == "CANCELLED"
    assert goal.id not in daemon._running_goals
    assert goal in daemon._completed_goals
    assert goal.completed_at > 0


@pytest.mark.asyncio
async def test_queued_goal_can_be_cancelled_without_execution(daemon):
    goal = AutonomousGoal(id="goal_queued_cancel_test", goal="Wait safely")
    daemon._goal_queue.append(goal)

    payload = await daemon.cancel_goal(goal.id)

    assert payload["status"] == "CANCELLED"
    assert goal not in daemon._goal_queue
    assert goal in daemon._completed_goals


@pytest.mark.asyncio
async def test_controller_waits_for_all_subtask_cleanup_before_propagating_cancel(monkeypatch):
    controller = EnhancedAutonomousController()
    started = asyncio.Event()
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()
    cleanup_finished = asyncio.Event()

    async def blocking_subtask(subtask, plan):
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cleanup_started.set()
            await allow_cleanup.wait()
            cleanup_finished.set()
            raise

    monkeypatch.setattr(controller, "execute_subtask", blocking_subtask)
    plan = ExecutionPlan(goal="Wait safely")
    plan.add_subtask(
        SubTask(
            id="step_controller_cancel_test",
            description="Wait without external side effects",
            agent="INFERENCE",
        )
    )

    execution = asyncio.create_task(controller.execute_plan(plan))
    await asyncio.wait_for(started.wait(), timeout=1)
    execution.cancel()
    await asyncio.wait_for(cleanup_started.wait(), timeout=1)

    assert not execution.done()

    allow_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(execution, timeout=1)
    assert cleanup_finished.is_set()


@pytest.mark.asyncio
async def test_cancel_route_rejects_missing_or_non_cancelled_goals(monkeypatch):
    from friday.api import server

    class FakeDaemon:
        async def cancel_goal(self, goal_id):
            if goal_id == "missing":
                return None
            return {"id": goal_id, "status": "COMPLETED"}

    monkeypatch.setattr(server, "autonomous_daemon", FakeDaemon())

    with pytest.raises(HTTPException) as missing:
        await server.cancel_autonomous_goal("missing")
    assert missing.value.status_code == 404

    with pytest.raises(HTTPException) as completed:
        await server.cancel_autonomous_goal("already-completed")
    assert completed.value.status_code == 409


@pytest.mark.asyncio
async def test_cancel_route_returns_only_a_confirmed_stopped_goal(monkeypatch):
    from friday.api import server

    class FakeDaemon:
        async def cancel_goal(self, goal_id):
            return {"id": goal_id, "status": "CANCELLED"}

    monkeypatch.setattr(server, "autonomous_daemon", FakeDaemon())

    payload = await server.cancel_autonomous_goal("goal_safe_cancel_test")

    assert payload == {"id": "goal_safe_cancel_test", "status": "CANCELLED"}
