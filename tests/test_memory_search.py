"""Unit and integration tests for searchable historical conversation memory."""

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from friday.agent.agent import FridayAgent
from friday.core.config import Settings
from friday.core.types import Message, Role, ToolCall
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.memory.sqlite import SQLiteConversationMemory
from friday.tools.builtin.memory_search import MemorySearchTool


def test_in_memory_search_substring_and_empty():
    mem = InMemoryConversationMemory(max_messages=10)
    mem.add_message(Message(role=Role.USER, content="I prefer using Python for data analysis."))
    mem.add_message(Message(role=Role.ASSISTANT, content="Python is an excellent choice."))
    mem.add_message(Message(role=Role.USER, content="What about TypeScript for UI?"))

    # Empty search
    assert mem.search("") == []
    assert mem.search("   ") == []

    # Exact and partial substring search
    results_python = mem.search("python")
    assert len(results_python) == 2
    assert results_python[0].content == "I prefer using Python for data analysis."

    results_ts = mem.search("typescript")
    assert len(results_ts) == 1
    assert "TypeScript" in results_ts[0].content

    # No match
    assert mem.search("Rust") == []


def test_sqlite_search_exact_and_partial(tmp_path):
    db_file = str(tmp_path / "search_test.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    c1 = mem.active_conversation_id
    mem.add_message(Message(role=Role.USER, content="My favorite IDE is VS Code with dark theme."))
    mem.add_message(Message(role=Role.ASSISTANT, content="VS Code is configured."))

    c2 = mem.create_conversation(title="Trading Project")
    mem.load_conversation(c2)
    mem.add_message(Message(role=Role.USER, content="The automated trading algorithm generated 15% return."))
    mem.add_message(Message(role=Role.ASSISTANT, content="Reviewing trading strategy."))

    # Exact token search
    res_ide = mem.search("VS Code")
    assert len(res_ide) >= 1
    assert any("favorite IDE is VS Code" in r.content for r in res_ide)

    # Prefix/partial search
    res_algo = mem.search("trad")
    assert len(res_algo) >= 2
    assert any("trading algorithm" in r.content for r in res_algo)

    # Empty query
    assert mem.search("") == []
    assert mem.search("   ") == []

    # Non-existent keyword
    assert mem.search("Kubernetes") == []


def test_sqlite_search_conversation_filtering(tmp_path):
    db_file = str(tmp_path / "search_filter.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    conv_a = mem.active_conversation_id
    mem.rename_conversation(conv_a, "Alpha")
    mem.add_message(Message(role=Role.USER, content="Project Alpha deployment on AWS."))

    conv_b = mem.create_conversation(title="Beta")
    mem.load_conversation(conv_b)
    mem.add_message(Message(role=Role.USER, content="Project Beta deployment on Azure."))

    # Search without conversation filter
    all_results = mem.search("deployment")
    assert len(all_results) == 2

    # Search with conversation filter for Alpha
    alpha_results = mem.search("deployment", conversation_id=conv_a)
    assert len(alpha_results) == 1
    assert "Alpha" in alpha_results[0].conversation_title
    assert "AWS" in alpha_results[0].content

    # Search with conversation filter for Beta
    beta_results = mem.search("deployment", conversation_id=conv_b)
    assert len(beta_results) == 1
    assert "Beta" in beta_results[0].conversation_title
    assert "Azure" in beta_results[0].content


def test_sqlite_search_result_limit(tmp_path):
    db_file = str(tmp_path / "search_limit.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    for i in range(10):
        mem.add_message(Message(role=Role.USER, content=f"Log entry #{i}: status operational"))

    results = mem.search("operational", limit=3)
    assert len(results) == 3


def test_sqlite_search_date_filtering(tmp_path):
    db_file = str(tmp_path / "search_date.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=5)
    future_time = now + timedelta(days=5)

    msg1 = Message(role=Role.USER, content="Past event note", timestamp=old_time)
    msg2 = Message(role=Role.USER, content="Current event note", timestamp=now)

    mem.add_message(msg1)
    mem.add_message(msg2)

    # Filter messages from the last 1 day
    cutoff = now - timedelta(days=1)
    results = mem.search("event note", start_time=cutoff)
    assert len(results) == 1
    assert results[0].content == "Current event note"


def test_memory_search_tool_execution(tmp_path):
    db_file = str(tmp_path / "tool_search.db")
    mem = SQLiteConversationMemory(db_path=db_file)
    mem.add_message(Message(role=Role.USER, content="My favorite pizza topping is pineapple."))

    tool = MemorySearchTool(memory=mem)
    assert tool.name == "search_memory"
    assert tool.safety_level.value == "SAFE"

    # Execution with matches
    output = tool.execute(query="pineapple")
    assert not output.is_error
    assert "pineapple" in output.content
    assert "USER" in output.content

    # Execution with empty query
    empty_output = tool.execute(query="")
    assert empty_output.is_error
    assert "cannot be empty" in empty_output.content

    # Execution with no matches
    nomatch_output = tool.execute(query="chocolate")
    assert not nomatch_output.is_error
    assert "No historical messages found" in nomatch_output.content


def test_agent_memory_search_end_to_end(tmp_path):
    db_file = str(tmp_path / "agent_search.db")
    settings = Settings(
        env="testing",
        memory_backend="sqlite",
        memory_db_path=db_file,
    )

    # Session 1: User says favorite car
    agent1 = FridayAgent(settings=settings, llm_provider=MockLLMProvider())
    c1 = agent1.conversation_id
    agent1.process_message("My favorite car is Porsche 911.")

    # Session 2: Create new conversation and search memory
    agent2 = FridayAgent(settings=settings, llm_provider=MockLLMProvider())
    c2 = agent2.create_new_conversation(title="Car discussion")

    # Custom responder that calls search_memory tool
    def search_responder(messages: list[Message], tools: list[dict[str, Any]] | None) -> Message:
        if any(m.role == Role.TOOL and "Porsche" in m.content for m in messages):
            return Message(role=Role.ASSISTANT, content="You previously mentioned your favorite car is the Porsche 911.")
        return Message(
            role=Role.ASSISTANT,
            content="Searching previous conversations...",
            tool_calls=[ToolCall(id="search_1", name="search_memory", arguments={"query": "favorite car"})],
        )

    agent2.llm = MockLLMProvider(custom_responder=search_responder)
    response = agent2.process_message("Do you remember my favorite car?")

    assert "Porsche 911" in response.content
    assert response.tool_calls is not None
    assert response.tool_calls[0].name == "search_memory"


def test_sqlite_search_performance_synthetic_dataset(tmp_path):
    db_file = str(tmp_path / "perf_test.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    # Insert 500 messages across 5 conversations
    for c_idx in range(5):
        conv_id = mem.create_conversation(title=f"Synthetic Batch {c_idx}")
        mem.load_conversation(conv_id)
        for m_idx in range(100):
            if m_idx == 42 and c_idx == 3:
                content = "Target needle in synthetic haystack: SECRET_TOKEN_7788"
            else:
                content = f"Synthetic turn {m_idx} in conversation {c_idx} about data metrics."
            mem.add_message(Message(role=Role.USER, content=content))

    start = time.perf_counter()
    results = mem.search("SECRET_TOKEN_7788")
    duration = time.perf_counter() - start

    assert len(results) == 1
    assert "SECRET_TOKEN_7788" in results[0].content
    # Ensure search latency is well under 100ms
    assert duration < 0.2
