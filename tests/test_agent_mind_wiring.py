"""The nine agents, each with a mind, sharing one memory.

These tests build real `BaseAgent` objects with a deterministic mock model and a
real tool registry, and check the three things the owner asked for: an agent
recalls, an agent learns from its own outcomes, and agents can find each other.
No network, no live model.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from friday.agents.base_agent import AgentTask, BaseAgent
from friday.cognition.memory_bridge import SharedMemory
from friday.cognition.mind import Mind, MindRegistry, get_mind_registry, set_mind_registry
from friday.core.types import Message, Role
from friday.llm.mock_provider import MockLLMProvider
from friday.tools.registry import ToolRegistry


class ScriptedProvider(MockLLMProvider):
    """A model that answers once, without tools, so the task loop terminates."""

    def __init__(self, reply: str = "done") -> None:
        super().__init__(model="scripted")
        self.reply = reply
        self.seen_messages: list[list[Message]] = []

    def generate(self, messages: list[Message], tools: Any = None, **_: Any) -> Message:  # type: ignore[override]
        self.seen_messages.append(list(messages))
        return Message(role=Role.ASSISTANT, content=self.reply)


class FailingProvider(ScriptedProvider):
    def generate(self, messages: list[Message], tools: Any = None, **_: Any) -> Message:  # type: ignore[override]
        raise RuntimeError("the model is down")


@pytest.fixture()
def registry(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> MindRegistry:
    memory = SharedMemory(tmp_path / "episodes.jsonl")
    registry = MindRegistry(memory=memory)
    set_mind_registry(registry)
    yield registry
    set_mind_registry(MindRegistry(memory=SharedMemory(tmp_path / "reset.jsonl")))


def _agent(provider: Any, *, agent_id: str = "developer_01", role: str = "developer") -> BaseAgent:
    return BaseAgent(
        agent_id=agent_id,
        role=role,
        instructions="write and test code",
        llm_provider=provider,
        tool_registry=ToolRegistry(),
        allowed_tools=[],
        max_iterations=2,
    )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_a_new_agent_has_a_mind_of_its_own(registry: MindRegistry) -> None:
    agent = _agent(ScriptedProvider())

    assert isinstance(agent.mind, Mind)
    assert agent.mind.agent_id == "developer_01"
    assert agent.mind.role == "developer"
    assert registry.for_agent("developer_01") is agent.mind


def test_agents_share_the_fleet_registry_not_private_minds(registry: MindRegistry) -> None:
    first = _agent(ScriptedProvider(), agent_id="a1", role="researcher")
    second = _agent(ScriptedProvider(), agent_id="a2", role="critic")

    assert {mind.agent_id for mind in registry.all()} == {"a1", "a2"}
    assert first.mind.memory is second.mind.memory


def test_a_successful_task_is_recorded_in_the_ledger_and_shared_memory(
    registry: MindRegistry,
) -> None:
    agent = _agent(ScriptedProvider("the tests pass"))

    result = _run(agent.execute_task(AgentTask(goal="run the test suite")))

    assert result.success is True
    record = agent.mind.ledger.get("developer.task")
    assert record is not None
    assert record.successes == 1
    episodes = agent.mind.memory.all(agent="developer_01")
    assert any(episode.summary.startswith("developer_01 completed") for episode in episodes)


def test_a_failed_generation_is_recorded_as_a_failure_not_a_success(
    registry: MindRegistry,
) -> None:
    agent = _agent(FailingProvider())

    result = _run(agent.execute_task(AgentTask(goal="fix the parser")))

    assert result.success is False
    record = agent.mind.ledger.get("developer.generate")
    assert record is not None
    assert record.failures == 1
    assert agent.mind.can("developer.generate")["answer"] == "evidence_against"


def test_an_agent_without_a_model_does_not_claim_to_have_worked(
    registry: MindRegistry,
) -> None:
    """The old behaviour returned success=True and 'Executed task ...'. It lied."""
    agent = _agent(None)

    result = agent.run("do something useful")

    assert result.success is False
    assert result.metadata["attempted"] is False
    assert "not attempted" in result.output
    assert agent.mind.ledger.get("developer.no_model") is not None


def test_an_agent_recalls_another_agents_experience_into_its_prompt(
    registry: MindRegistry,
) -> None:
    veteran = _agent(ScriptedProvider(), agent_id="self_developer_01", role="self_developer")
    veteran.mind.observe(
        "source_repair",
        True,
        detail="the parser import test failed; adding the missing import fixed it",
        summary="self_developer_01 completed: fix the parser import test",
    )

    provider = ScriptedProvider("acknowledged")
    newcomer = _agent(provider, agent_id="developer_02", role="developer")
    _run(newcomer.execute_task(AgentTask(goal="fix the parser import test")))

    assert provider.seen_messages, "the agent never called the model"
    system_message = next(
        message for message in provider.seen_messages[0] if message.role is Role.SYSTEM
    )
    assert "Relevant prior experience" in system_message.content
    assert "self_developer_01" in system_message.content
    assert "worked" in system_message.content


def test_shared_recall_reaches_every_agent(registry: MindRegistry) -> None:
    writer = _agent(ScriptedProvider(), agent_id="writer", role="developer")
    writer.mind.observe("write_code", True, detail="created the widget module", summary="writer made a widget")

    reader = _agent(ScriptedProvider(), agent_id="reader", role="critic")

    hits = reader.mind.recall("widget module")

    assert hits
    assert hits[0].episode.agent == "writer"
    assert "widget" in hits[0].why


def test_the_registry_sends_a_capability_to_the_agent_with_evidence(
    registry: MindRegistry,
) -> None:
    good = _agent(ScriptedProvider(), agent_id="good", role="developer")
    bad = _agent(ScriptedProvider(), agent_id="bad", role="developer")
    for _ in range(3):
        good.mind.observe("run_tests", True, summary="ran the suite")
    bad.mind.observe("run_tests", False, summary="the suite broke")

    choice = registry.consult("run_tests")

    assert choice["chosen"] == "good"
    assert "3/3" in choice["why"]


def test_get_mind_registry_returns_one_process_wide_registry(registry: MindRegistry) -> None:
    assert get_mind_registry() is registry
