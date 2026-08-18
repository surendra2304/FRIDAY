"""Tests for FridayAgent integration with persistent SQLite memory."""

import sqlite3
from typing import Any, Dict, List, Optional
import pytest
from friday.agent.agent import FridayAgent
from friday.core.config import Settings
from friday.core.types import Message, Role, ToolCall
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.memory.sqlite import SQLiteConversationMemory


def test_agent_with_in_memory_backend(mock_settings, mock_llm_provider):
    agent = FridayAgent(
        settings=mock_settings,
        llm_provider=mock_llm_provider,
        memory=InMemoryConversationMemory(max_messages=5),
    )
    assert agent.conversation_id is None
    resp = agent.process_message("Hello")
    assert resp.content
    assert len(agent.get_history()) == 2


def test_agent_with_sqlite_backend(tmp_path):
    db_file = str(tmp_path / "agent_test.db")
    settings = Settings(
        env="testing",
        memory_backend="sqlite",
        memory_db_path=db_file,
        memory_max_messages=10,
    )
    agent = FridayAgent(
        settings=settings,
        llm_provider=MockLLMProvider(),
    )
    assert agent.conversation_id is not None
    active_id = agent.conversation_id

    resp = agent.process_message("My favorite programming language is Python.")
    assert resp.content
    assert len(agent.get_history()) == 2

    # Check directly inside the SQLite database
    conn = sqlite3.connect(db_file)
    rows = conn.execute("SELECT role, content FROM messages WHERE conversation_id = ?", (active_id,)).fetchall()
    conn.close()

    assert len(rows) == 2
    assert rows[0][0] == "user"
    assert rows[0][1] == "My favorite programming language is Python."


def test_agent_restart_simulation_reloads_conversation(tmp_path):
    db_file = str(tmp_path / "restart_test.db")
    settings = Settings(
        env="testing",
        memory_backend="sqlite",
        memory_db_path=db_file,
        memory_max_messages=10,
    )

    # Session 1: User gives information
    agent_session_1 = FridayAgent(
        settings=settings,
        llm_provider=MockLLMProvider(),
    )
    conv_id = agent_session_1.conversation_id
    assert conv_id is not None

    agent_session_1.process_message("My favorite editor is VS Code.")
    history_1 = agent_session_1.get_history()
    assert len(history_1) == 2

    # Session 2: Process restart simulation by instantiating new FridayAgent targeting the same conversation
    agent_session_2 = FridayAgent(
        settings=settings,
        llm_provider=MockLLMProvider(),
        conversation_id=conv_id,
    )
    assert agent_session_2.conversation_id == conv_id

    history_2 = agent_session_2.get_history()
    assert len(history_2) == 2
    assert history_2[0].content == "My favorite editor is VS Code."

    # Process next turn in resumed session
    agent_session_2.process_message("What is my favorite editor?")
    history_after_turn = agent_session_2.get_history()
    assert len(history_after_turn) == 4


def test_agent_tool_call_and_result_persistence(tmp_path):
    db_file = str(tmp_path / "tools_persisted.db")
    settings = Settings(
        env="testing",
        memory_backend="sqlite",
        memory_db_path=db_file,
        memory_max_messages=10,
    )

    # Custom responder that triggers a calculator tool call
    def mock_tool_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        # If tool result is in context, synthesize final answer
        if any(m.role == Role.TOOL for m in messages):
            return Message(role=Role.ASSISTANT, content="The calculation result is 2500.")
        return Message(
            role=Role.ASSISTANT,
            content="Calculating 50 * 50...",
            tool_calls=[ToolCall(id="calc_1", name="calculator", arguments={"expression": "50 * 50"})],
        )

    agent = FridayAgent(
        settings=settings,
        llm_provider=MockLLMProvider(custom_responder=mock_tool_responder),
    )
    conv_id = agent.conversation_id

    response = agent.process_message("Calculate 50 * 50")
    assert "2500" in response.content

    # Inspect messages saved: User -> Assistant (with tool_calls) -> Tool -> Assistant (final)
    history = agent.get_history()
    assert len(history) == 4
    assert history[0].role == Role.USER
    assert history[1].role == Role.ASSISTANT
    assert history[1].tool_calls is not None
    assert history[1].tool_calls[0].name == "calculator"
    assert history[2].role == Role.TOOL
    assert history[2].content == "2500"
    assert history[3].role == Role.ASSISTANT

    # Restart and verify persistent reconstruction
    restarted_agent = FridayAgent(
        settings=settings,
        llm_provider=MockLLMProvider(),
        conversation_id=conv_id,
    )
    reloaded_history = restarted_agent.get_history()
    assert len(reloaded_history) == 4
    assert reloaded_history[1].tool_calls is not None
    assert reloaded_history[1].tool_calls[0].arguments == {"expression": "50 * 50"}
    assert reloaded_history[2].role == Role.TOOL
    assert reloaded_history[2].content == "2500"


def test_agent_conversation_switching_and_isolation(tmp_path):
    db_file = str(tmp_path / "conv_switch.db")
    settings = Settings(
        env="testing",
        memory_backend="sqlite",
        memory_db_path=db_file,
    )
    agent = FridayAgent(
        settings=settings,
        llm_provider=MockLLMProvider(),
    )
    conv1 = agent.conversation_id
    agent.process_message("Message in conversation 1")

    # Create and switch to conversation 2
    conv2 = agent.create_new_conversation(title="Project Alpha")
    assert conv2 != conv1
    assert agent.conversation_id == conv2

    agent.process_message("Message in conversation 2")
    assert len(agent.get_history()) == 2
    assert agent.get_history()[0].content == "Message in conversation 2"

    # Switch back to conversation 1
    agent.switch_conversation(conv1)
    assert agent.conversation_id == conv1
    assert len(agent.get_history()) == 2
    assert agent.get_history()[0].content == "Message in conversation 1"


def test_agent_context_window_sliding(tmp_path):
    db_file = str(tmp_path / "sliding_window.db")
    settings = Settings(
        env="testing",
        memory_backend="sqlite",
        memory_db_path=db_file,
        memory_max_messages=4,
    )

    passed_context_sizes = []
    def recording_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        # Exclude system message
        non_system = [m for m in messages if m.role != Role.SYSTEM]
        passed_context_sizes.append(len(non_system))
        return Message(role=Role.ASSISTANT, content="Acknowledged.")

    agent = FridayAgent(
        settings=settings,
        llm_provider=MockLLMProvider(custom_responder=recording_responder),
    )

    # Perform 5 turns (10 messages total: 5 user, 5 assistant)
    for i in range(5):
        agent.process_message(f"Turn {i}")

    # Total persistent history in SQLite is 10 messages
    assert len(agent.get_history()) == 10

    # But the working context passed to the LLM was constrained by memory_max_messages (4)
    # Turn 0: 1 msg (User)
    # Turn 1: 3 msgs (User, Assistant, User)
    # Turn 2: 4 msgs (capped at 4)
    # Turn 3: 4 msgs (capped at 4)
    # Turn 4: 4 msgs (capped at 4)
    assert passed_context_sizes[-1] == 4


def test_agent_clear_memory_sqlite(tmp_path):
    db_file = str(tmp_path / "clear_test.db")
    settings = Settings(
        env="testing",
        memory_backend="sqlite",
        memory_db_path=db_file,
    )
    agent = FridayAgent(
        settings=settings,
        llm_provider=MockLLMProvider(),
    )
    agent.process_message("Test message")
    assert len(agent.get_history()) == 2

    agent.clear_memory()
    assert len(agent.get_history()) == 0

    # Ensure DB is also cleared
    conn = sqlite3.connect(db_file)
    count = conn.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (agent.conversation_id,)).fetchone()[0]
    conn.close()
    assert count == 0
