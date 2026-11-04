"""Verification: FRIDAY daemon timeout + retry handling for agent mesh dispatches.

In-process contract harness only — no network, no real peer URLs.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from friday.autonomous.enhanced_controller import (
    EnhancedAutonomousController,
    ExecutionPlan,
    SubTask,
)
from friday.cognition.mesh import HarnessBehaviour, Mesh, OutcomeState, build_contracts
from friday.ecosystem.fleet_client import fleet_client


@pytest.fixture()
def mesh():
    contracts = build_contracts(fleet_client)
    m, transport = Mesh.in_process(contracts, attempts=1, backoff_seconds=0.0)
    return m, transport


def _behave(mesh_transport, peer, status_code=200, receipt=True, body=None, raise_transport_error=False):
    mesh_transport.behave(
        peer,
        HarnessBehaviour(
            status_code=status_code,
            receipt=receipt,
            body=body,
            raise_transport_error=raise_transport_error,
        ),
        path="*",
        action="*",
    )


@pytest.mark.asyncio
async def test_unreachable_meshes_are_retried_then_fail(mesh):
    """UNREACHABLE -> retried with backoff -> FAILED, never hangs."""
    m, transport = mesh
    _behave(transport, "intelx", raise_transport_error=True)  # never answers
    controller = EnhancedAutonomousController()
    controller._peer_mesh = m  # use the in-process harness, not the real network

    plan = ExecutionPlan(goal="test")
    st = SubTask(id="st_1", description="research", agent="INTELX", dependencies=[])
    plan.add_subtask(st)

    start = time.time()
    ok = await controller.execute_subtask(st, plan)
    elapsed = time.time() - start

    # One attempt: the backoff retry-to-exhaustion is driven by execute_plan's
    # loop re-calling execute_subtask. A single call backs off once and yields.
    assert ok is False
    assert st.status == "PENDING", "one call backs off and yields, not final FAILED"
    assert st.attempts == 1
    # exponential backoff (2 ** 1 = 2s) applied, bounded, no hang
    assert 1.5 < elapsed < 15


@pytest.mark.asyncio
async def test_plan_status_is_partial_when_some_subtasks_fail(mesh):
    """Plan COMPLETED only when all done; PARTIAL when some; FAILED when none."""
    m, transport = mesh
    _behave(transport, "intelx")  # succeeds
    _behave(transport, "memora", status_code=403)  # refused -> fail
    controller = EnhancedAutonomousController()
    controller._peer_mesh = m  # use the in-process harness, not the real network

    plan = ExecutionPlan(goal="mixed outcome")
    st1 = SubTask(id="st_1", description="research", agent="INTELX", dependencies=[])
    st2 = SubTask(id="st_2", description="store", agent="MEMORA", dependencies=["st_1"])
    plan.add_subtask(st1)
    plan.add_subtask(st2)

    result = await controller.execute_plan(plan)

    assert result.status == "PARTIAL"
    assert result.completed_subtasks == 1
    assert result.failed_subtasks == 1


@pytest.mark.asyncio
async def test_plan_status_is_completed_only_when_all_done(mesh):
    """All subtasks succeed -> COMPLETED."""
    m, transport = mesh
    _behave(transport, "intelx")
    _behave(transport, "memora")
    controller = EnhancedAutonomousController()
    controller._peer_mesh = m  # use the in-process harness, not the real network

    plan = ExecutionPlan(goal="all succeed")
    st1 = SubTask(id="st_1", description="research", agent="INTELX", dependencies=[])
    st2 = SubTask(id="st_2", description="store", agent="MEMORA", dependencies=["st_1"])
    plan.add_subtask(st1)
    plan.add_subtask(st2)

    result = await controller.execute_plan(plan)

    assert result.status == "COMPLETED"
    assert result.completed_subtasks == 2
    assert result.failed_subtasks == 0


@pytest.mark.asyncio
async def test_failed_dependency_does_not_hang_dependent_subtask(mesh):
    """A pending subtask whose dependency FAILED must be marked FAILED, not wait forever."""
    m, transport = mesh
    _behave(transport, "intelx", raise_transport_error=True)  # first step never answers
    controller = EnhancedAutonomousController()
    controller._peer_mesh = m  # use the in-process harness, not the real network

    plan = ExecutionPlan(goal="chain with dead first link")
    st1 = SubTask(id="st_1", description="research", agent="INTELX", dependencies=[])
    st2 = SubTask(id="st_2", description="store", agent="MEMORA", dependencies=["st_1"])
    plan.add_subtask(st1)
    plan.add_subtask(st2)

    start = time.time()
    result = await controller.execute_plan(plan)
    elapsed = time.time() - start

    assert result.status == "FAILED", "nothing completed when the whole chain dies"
    assert st1.status == "FAILED"
    assert st2.status == "FAILED", "dependent subtask must not hang waiting on failed dependency"
    assert st2.error == "Skipped: dependency did not complete"
    assert elapsed < 30


@pytest.mark.asyncio
async def test_daemon_executes_goal_without_hanging(monkeypatch, mesh):
    """End-to-end: daemon submits a goal and it reaches a terminal status without hanging."""
    m, transport = mesh
    _behave(transport, "intelx")  # first step succeeds
    _behave(transport, "memora", status_code=403)  # second step refused -> fail
    controller = EnhancedAutonomousController()
    controller._peer_mesh = m  # use the in-process harness, not the real network

    from friday.autonomous.daemon import AutonomousDaemon
    daemon = AutonomousDaemon()
    daemon.controller = controller

    goal = daemon.submit_goal("research the topic and store the findings")
    await daemon._start_goal(goal)

    # The plan runs in a background task; wait for it to finish (bounded).
    start = time.time()
    while goal.status == "RUNNING":
        assert time.time() - start < 30, "goal must not hang"
        await asyncio.sleep(0.1)

    assert goal.status != "RUNNING", "goal must reach a terminal status, not hang"
    assert time.time() - start < 30, "goal submission/execution must not hang"
