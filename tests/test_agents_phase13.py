"""Unit tests for Multi-Agent Specialist System: BaseAgent, Registry, Decomposer, Router."""

import asyncio

from friday.agents.base_agent import AgentTask, AgentTaskResult, BaseAgent
from friday.agents.decomposer import (
    DecomposedSubtask,
    TaskDecomposer,
)
from friday.agents.registry import AgentRegistry
from friday.agents.router import AgentRouter
from friday.core.types import Message, Role
from friday.llm.base import BaseLLMProvider


class DummyLLM(BaseLLMProvider):
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return "dummy"

    @property
    def model(self) -> str:
        return "dummy-model"

    def generate(self, messages, tools=None):
        self.call_count += 1
        if self.responses:
            return self.responses.pop(0)
        return Message(role=Role.ASSISTANT, content="Dummy response")


def test_base_agent_initialization():
    llm = DummyLLM()
    agent = BaseAgent(
        agent_id="test_01",
        role="researcher",
        instructions="Perform deep research.",
        llm_provider=llm,
        allowed_tools=["web_search"],
        preferred_models=["gpt-oss-120b"],
        memory_scope="task",
    )
    assert agent.agent_id == "test_01"
    assert agent.role == "researcher"
    assert agent.allowed_tools == ["web_search"]
    assert agent.memory_scope == "task"


def test_base_agent_execute_task():
    llm = DummyLLM(
        responses=[
            Message(role=Role.ASSISTANT, content="Research completed with 3 key insights.")
        ]
    )
    agent = BaseAgent(
        agent_id="res_01",
        role="researcher",
        instructions="Research user questions.",
        llm_provider=llm,
    )
    task = AgentTask(goal="Find latest quantum computing breakthroughs")
    result = asyncio.run(agent.execute_task(task))

    assert isinstance(result, AgentTaskResult)
    assert result.success is True
    assert "Research completed" in result.output
    assert result.agent_id == "res_01"


def test_agent_registry():
    llm = DummyLLM()
    reg = AgentRegistry()
    a1 = BaseAgent(agent_id="a1", role="coder", instructions="Code things", llm_provider=llm)
    a2 = BaseAgent(agent_id="a2", role="writer", instructions="Write things", llm_provider=llm)

    reg.register_agent(a1)
    reg.register_agent(a2)

    assert len(reg.list_agents()) == 2
    assert reg.get_agent("coder") == a1
    assert reg.get_agent("a2") == a2
    assert reg.get_agent("unknown") is None

    assert reg.unregister_agent("a1") is True
    assert len(reg.list_agents()) == 1


def test_task_decomposer_simple():
    llm = DummyLLM(
        responses=[
            Message(
                role=Role.ASSISTANT,
                content='{"is_complex": false, "rationale": "Single query", "subtasks": []}',
            )
        ]
    )
    decomposer = TaskDecomposer(llm_provider=llm)
    result = decomposer.decompose("What is the capital of France?")
    assert result.is_complex is False
    assert len(result.subtasks) == 1
    assert result.subtasks[0].title == "Execute Goal"


def test_task_decomposer_complex():
    complex_json = """{
        "is_complex": true,
        "rationale": "Multi-stage project",
        "subtasks": [
            {"title": "Search API docs", "description": "Look up weather API specs", "suggested_role": "researcher"},
            {"title": "Write client", "description": "Implement python wrapper", "suggested_role": "coder"}
        ]
    }"""
    llm = DummyLLM(responses=[Message(role=Role.ASSISTANT, content=complex_json)])
    decomposer = TaskDecomposer(llm_provider=llm)
    result = decomposer.decompose("Build a full weather forecast integration with tests")

    assert result.is_complex is True
    assert len(result.subtasks) == 2
    assert result.subtasks[0].suggested_role == "researcher"
    assert result.subtasks[1].suggested_role == "coder"


def test_agent_router():
    llm = DummyLLM()
    reg = AgentRegistry()
    researcher = BaseAgent(agent_id="r1", role="researcher", instructions="Search docs", llm_provider=llm)
    coder = BaseAgent(agent_id="c1", role="coder", instructions="Write python code", llm_provider=llm)
    general = BaseAgent(agent_id="g1", role="general", instructions="General helper", llm_provider=llm)

    reg.register_agent(researcher)
    reg.register_agent(coder)
    reg.register_agent(general)

    router = AgentRouter(registry=reg)

    subtask_research = DecomposedSubtask(title="Look up API", description="search web", suggested_role="researcher")
    decision1 = router.route_subtask(subtask_research)
    assert decision1.selected_agent == researcher
    assert decision1.score >= 0.6

    subtask_code = DecomposedSubtask(title="Write script", description="write code", suggested_role="coder")
    decision2 = router.route_subtask(subtask_code)
    assert decision2.selected_agent == coder
