# -*- coding: utf-8 -*-
"""Unit tests for Phases 20-21: AI Universe Integration API, Mock Client, and Orchestration."""

import pytest
from friday.integrations.universe_api import WorldConfig, UniverseAgentConfig
from friday.integrations.mock_universe import MockUniverseClient
from friday.integrations.universe_orchestrator import UniverseOrchestrator
from friday.memory.sqlite import SQLiteConversationMemory


def test_mock_universe_client_crud():
    client = MockUniverseClient()
    world_state = client.create_world(WorldConfig(name="Alpha World"))
    assert world_state.world_id.startswith("world_")
    assert world_state.is_running is False
    assert len(world_state.active_agents) == 0

    ag1 = client.create_agent(UniverseAgentConfig(name="Explorer 1", persona="Navigator"))
    assert ag1["name"] == "Explorer 1"

    # Start simulation
    state_after_start = client.start_simulation(steps=50)
    assert state_after_start.is_running is True
    assert state_after_start.step == 50
    assert len(state_after_start.active_agents) == 1

    # Retrieve experiment results
    results = client.get_experiment_results()
    assert results.success is True
    assert results.agent_count == 1
    assert "accuracy" in results.metrics
    assert results.total_steps == 50


def test_universe_orchestrator_execution_and_sqlite_persistence(tmp_path):
    db_file = str(tmp_path / "universe_test.db")
    mem = SQLiteConversationMemory(db_path=db_file)
    client = MockUniverseClient()

    orchestrator = UniverseOrchestrator(universe_api=client, memory=mem)
    prompt = "Create a world with 10 agents and run an experiment"

    assert orchestrator.can_handle(prompt) is True
    res = orchestrator.execute_universe_goal(prompt, agent_count=10, steps=120)

    assert res["agent_count"] == 10
    assert res["total_steps"] == 120
    assert "🪐 **Universe Simulation Completed**" in res["synthesis"]

    # Verify SQLite experiments table
    stats = mem.get_provider_performance_stats(task_type="universe_simulation")
    assert len(stats) == 1
    assert stats[0]["provider_name"] == "UniverseAPI"
    assert stats[0]["model_name"] == "SimAgentEngine"
    assert stats[0]["success_rate"] == 1.0

    mem.close()


def test_universe_orchestrator_can_handle_patterns():
    orchestrator = UniverseOrchestrator()
    assert orchestrator.can_handle("spawn a world with 5 agents") is True
    assert orchestrator.can_handle("run simulation with 12 agents") is True
    assert orchestrator.can_handle("start a universe experiment") is True
    assert orchestrator.can_handle("what is the weather in Delhi?") is False
