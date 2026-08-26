# -*- coding: utf-8 -*-
"""Unit tests for FRIDAY Lab FRIDAY Lab: Experiments, SQLite Metrics, CLI runner, and Dynamic Routing."""

import pytest
from friday.lab.experiment import ExperimentRunner, ExperimentTask, TrialResult, run_standard_lab_suite
from friday.llm.base import BaseLLMProvider
from friday.core.types import Message, Role
from friday.memory.sqlite import SQLiteConversationMemory
from friday.agents.base_agent import BaseAgent
from friday.agents.registry import AgentRegistry
from friday.agents.router import AgentRouter
from friday.agents.decomposer import DecomposedSubtask


class MockFastLLM(BaseLLMProvider):
    def __init__(self, model="fast-model"):
        super().__init__(model=model)

    @property
    def provider_name(self) -> str:
        return "mock_fast"

    def generate(self, messages, tools=None):
        return Message(role=Role.ASSISTANT, content="The result is 540 and Python def return.")


class MockSlowLLM(BaseLLMProvider):
    def __init__(self, model="slow-model"):
        super().__init__(model=model)

    @property
    def provider_name(self) -> str:
        return "mock_slow"

    def generate(self, messages, tools=None):
        return Message(role=Role.ASSISTANT, content="Slow calculations...")


def test_experiment_runner_ab_comparison(tmp_path):
    db_file = str(tmp_path / "lab_test.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    p1 = MockFastLLM()
    p2 = MockSlowLLM()

    runner = ExperimentRunner(providers=[p1, p2], memory=mem)
    task = ExperimentTask(
        task_id="t_calc",
        task_type="reasoning",
        prompt="Calculate 45 * 12",
        expected_keywords=["540"],
    )

    results = runner.run_benchmark([task])
    assert len(results) == 2

    fast_res = next(r for r in results if r.provider_name == "mock_fast")
    slow_res = next(r for r in results if r.provider_name == "mock_slow")

    assert fast_res.success is True
    assert fast_res.accuracy == 1.0
    assert slow_res.accuracy == 0.0

    # Verify SQLite experiments table
    stats = mem.get_provider_performance_stats(task_type="reasoning")
    assert len(stats) >= 2
    assert stats[0]["provider_name"] == "mock_fast"

    mem.close()


def test_dynamic_router_prioritizes_lab_metrics(tmp_path):
    db_file = str(tmp_path / "dynamic_route.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    # Seed historical experiments
    mem.record_experiment(
        experiment_name="bench",
        task_prompt="code task",
        task_type="coder",
        provider_name="groq",
        model_name="gpt-oss-120b",
        accuracy=1.0,
        success=True,
        latency_ms=85.0,
    )
    mem.record_experiment(
        experiment_name="bench",
        task_prompt="code task",
        task_type="coder",
        provider_name="slow_provider",
        model_name="slow-model",
        accuracy=0.2,
        success=False,
        latency_ms=2500.0,
    )

    reg = AgentRegistry()
    a1 = BaseAgent(
        agent_id="fast_coder",
        role="coder",
        instructions="Write code fast",
        llm_provider=MockFastLLM(),
        preferred_models=["gpt-oss-120b"],
    )
    a2 = BaseAgent(
        agent_id="slow_coder",
        role="coder",
        instructions="Write code slow",
        llm_provider=MockSlowLLM(),
        preferred_models=["slow-model"],
    )
    reg.register_agent(a1)
    reg.register_agent(a2)

    router = AgentRouter(registry=reg, memory=mem)
    subtask = DecomposedSubtask(
        title="Code script",
        description="Write code",
        suggested_role="coder",
    )
    decision = router.route_subtask(subtask)

    # Fast coder should get bonus from experiments table
    assert decision.selected_agent == a1
    assert "Historical experiment score bonus" in decision.rationale

    mem.close()


def test_experiment_runner_with_verifier_llm(tmp_path):
    db_file = str(tmp_path / "verifier_test.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    class VerifierLLM(BaseLLMProvider):
        def __init__(self, model="verifier-model"):
            super().__init__(model=model)

        @property
        def provider_name(self) -> str:
            return "verifier"

        def generate(self, messages, tools=None):
            return Message(role=Role.ASSISTANT, content="0.95 (Highly accurate solution)")

    p1 = MockFastLLM()
    v_llm = VerifierLLM()

    runner = ExperimentRunner(providers=[p1], memory=mem, verifier_llm=v_llm)
    task = ExperimentTask(
        task_id="t_v",
        task_type="coding",
        prompt="Write a function",
    )

    results = runner.run_benchmark([task])
    assert len(results) == 1
    assert results[0].accuracy == 0.95

    mem.close()


def test_run_standard_lab_suite(tmp_path):
    db_file = str(tmp_path / "suite_test.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    trials = run_standard_lab_suite(memory=mem)
    assert len(trials) >= 1
    for t in trials:
        assert isinstance(t, TrialResult)
        assert t.latency_ms >= 0.0

    mem.close()
