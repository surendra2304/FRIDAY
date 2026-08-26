# -*- coding: utf-8 -*-
"""Comprehensive test suite for Trace-Based Learning, TraceAnalyzer, and Dynamic Routing."""

import os
from typing import Any, Dict, List, Optional
import pytest

from friday.agents.base_agent import BaseAgent
from friday.agents.decomposer import DecomposedSubtask
from friday.agents.registry import AgentRegistry
from friday.agents.router import AgentRouter
from friday.core.types import Message, Role
from friday.learning.trace_analyzer import TraceAnalyzer
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.sqlite import SQLiteConversationMemory


class MockNamedLLM(MockLLMProvider):
    """Mock LLM Provider with custom provider name."""
    def __init__(self, prov_name: str = "mock"):
        super().__init__()
        self._prov_name = prov_name

    @property
    def provider_name(self) -> str:
        return self._prov_name


class DummySpecialistAgent(BaseAgent):
    """Specialist agent for testing routing."""
    def __init__(self, name: str, role: str, allowed_tools: Optional[List[str]] = None, provider_name: str = "mock"):
        llm = MockNamedLLM(prov_name=provider_name)
        super().__init__(
            agent_id=f"agent_{name}",
            role=role,
            instructions=f"Specialist in {role}",
            llm_provider=llm,
            allowed_tools=allowed_tools or [],
        )

    def execute_subtask(self, subtask: DecomposedSubtask) -> Any:
        return f"Executed {subtask.title}"


@pytest.fixture
def sqlite_memory(tmp_path):
    db_file = str(tmp_path / "test_traces.db")
    mem = SQLiteConversationMemory(db_path=db_file)
    yield mem
    mem.close()


def test_execution_trace_logging_and_retrieval(sqlite_memory):
    """Test logging execution traces and retrieving stats in SQLiteMemory."""
    # 1. Log a successful trace
    tid1 = sqlite_memory.log_execution_trace(
        goal="Search for python project files",
        tools_used=["search_files", "file_reader"],
        models_used=["gemini-2.5-pro"],
        provider="gemini",
        latency_ms=850.0,
        success=True,
        task_type="file_search",
    )
    assert tid1.startswith("tr_")

    # 2. Log a failed trace
    tid2 = sqlite_memory.log_execution_trace(
        goal="Execute bash script",
        tools_used=["execute_command"],
        models_used=["cerebras-llama3"],
        provider="cerebras",
        latency_ms=3500.0,
        success=False,
        error_message="Command timed out after 3.5s",
        task_type="shell_execution",
    )
    assert tid2.startswith("tr_")

    # 3. Retrieve all traces
    traces = sqlite_memory.get_execution_traces()
    assert len(traces) == 2
    assert traces[0]["trace_id"] == tid2
    assert traces[1]["trace_id"] == tid1

    # 4. Filter by success_only
    succ_traces = sqlite_memory.get_execution_traces(success_only=True)
    assert len(succ_traces) == 1
    assert succ_traces[0]["trace_id"] == tid1

    # 5. Check trace stats
    stats = sqlite_memory.get_trace_stats()
    assert stats["total_traces"] == 2
    assert stats["successful_traces"] == 1
    assert stats["failed_traces"] == 1
    assert stats["success_rate"] == 0.5


def test_trace_analyzer_tool_success_rates_and_patterns(sqlite_memory):
    """TraceAnalyzer discovers tool success rates (e.g. search_files succeeds 95%, execute_command only 50%)."""
    # 9 successes and 1 failure for search_files (90% success rate)
    for i in range(9):
        sqlite_memory.log_execution_trace(
            goal="search for files",
            tools_used=["search_files"],
            provider="gemini",
            latency_ms=900.0,
            success=True,
        )
    sqlite_memory.log_execution_trace(
        goal="search for files",
        tools_used=["search_files"],
        provider="gemini",
        latency_ms=1200.0,
        success=False,
    )

    # 5 successes and 5 failures for execute_command (50% success rate)
    for i in range(5):
        sqlite_memory.log_execution_trace(
            goal="search for files using dir",
            tools_used=["execute_command"],
            provider="local",
            latency_ms=2500.0,
            success=True,
        )
        sqlite_memory.log_execution_trace(
            goal="search for files using dir",
            tools_used=["execute_command"],
            provider="local",
            latency_ms=3000.0,
            success=False,
        )

    analyzer = TraceAnalyzer(memory=sqlite_memory)
    rates = analyzer.get_tool_success_rates(goal_query="search")

    assert "search_files" in rates
    assert "execute_command" in rates
    assert rates["search_files"]["success_rate"] == 0.9
    assert rates["execute_command"]["success_rate"] == 0.5


def test_trace_analyzer_identifies_failing_providers(sqlite_memory):
    """TraceAnalyzer identifies providers with high failure rates (e.g. Cerebras 90% failure)."""
    # 9 failures and 1 success for cerebras
    for _ in range(9):
        sqlite_memory.log_execution_trace(
            goal="complex coding prompt",
            tools_used=["write_code"],
            provider="cerebras",
            latency_ms=5000.0,
            success=False,
        )
    sqlite_memory.log_execution_trace(
        goal="complex coding prompt",
        tools_used=["write_code"],
        provider="cerebras",
        latency_ms=4500.0,
        success=True,
    )

    # 10 successes for anthropic
    for _ in range(10):
        sqlite_memory.log_execution_trace(
            goal="complex coding prompt",
            tools_used=["write_code"],
            provider="anthropic",
            latency_ms=1100.0,
            success=True,
        )

    analyzer = TraceAnalyzer(memory=sqlite_memory)
    failing = analyzer.get_failing_providers(failure_threshold=0.80)
    assert "cerebras" in failing
    assert "anthropic" not in failing

    # Reorder fallback providers: anthropic first, cerebras last
    ranked = analyzer.filter_and_rank_fallback_providers(["cerebras", "anthropic", "openai"])
    assert ranked[0] == "anthropic"
    assert ranked[-1] == "cerebras"


def test_trace_analyzer_optimal_tool_and_provider(sqlite_memory):
    """TraceAnalyzer finds optimal tool and provider combinations under 2 seconds."""
    sqlite_memory.log_execution_trace(
        goal="find and summarize document notes",
        tools_used=["search_files"],
        provider="gemini",
        latency_ms=1100.0,
        success=True,
    )

    analyzer = TraceAnalyzer(memory=sqlite_memory)
    optimal = analyzer.get_optimal_tool_and_provider(
        goal="find document notes",
        available_tools=["search_files", "execute_command"],
    )
    assert optimal is not None
    assert optimal["preferred_tool"] == "search_files"
    assert optimal["preferred_provider"] == "gemini"
    assert optimal["fast_path"] is True
    assert optimal["historical_latency_ms"] == 1100.0


def test_router_dynamic_priority_and_failing_provider_deprioritization(sqlite_memory):
    """AgentRouter dynamically boosts fast high-success tools and de-prioritizes failing providers."""
    # Populate historical traces:
    # 1. search_files + gemini is fast (< 2s) and successful
    sqlite_memory.log_execution_trace(
        goal="search files in workspace",
        tools_used=["search_files"],
        provider="gemini_fast",
        latency_ms=750.0,
        success=True,
    )
    # 2. cerebras has high failure rate
    for _ in range(4):
        sqlite_memory.log_execution_trace(
            goal="search files in workspace",
            tools_used=["search_files"],
            provider="cerebras_flaky",
            latency_ms=4000.0,
            success=False,
        )

    registry = AgentRegistry()
    good_agent = DummySpecialistAgent(
        name="fast_searcher",
        role="file_searcher",
        allowed_tools=["search_files"],
        provider_name="gemini_fast",
    )
    bad_agent = DummySpecialistAgent(
        name="unreliable_searcher",
        role="file_searcher",
        allowed_tools=["search_files"],
        provider_name="cerebras_flaky",
    )

    registry.register_agent(good_agent)
    registry.register_agent(bad_agent)

    analyzer = TraceAnalyzer(memory=sqlite_memory)
    router = AgentRouter(registry=registry, memory=sqlite_memory, trace_analyzer=analyzer)

    subtask = DecomposedSubtask(
        subtask_id="st_1",
        title="search files",
        description="search files in workspace",
        suggested_role="file_searcher",
    )

    decision = router.route_subtask(subtask)
    assert decision.selected_agent == good_agent
    assert decision.score > 0.8
    assert "Trace-Based Learning bonus" in decision.rationale
