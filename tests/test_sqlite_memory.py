"""Unit tests for SQLiteConversationMemory persistent storage."""

import os
import sqlite3
import threading
from datetime import datetime, timezone
import pytest
from friday.core.config import Settings
from friday.core.types import Message, Role, ToolCall
from friday.memory.sqlite import SQLiteConversationMemory


def test_sqlite_memory_db_and_schema_creation(tmp_path):
    db_file = tmp_path / "subdir" / "test.db"
    assert not db_file.exists()

    mem = SQLiteConversationMemory(db_path=str(db_file))
    assert db_file.exists()

    # Check tables exist
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
    conn.close()

    assert "conversations" in tables
    assert "messages" in tables


def test_sqlite_memory_conversation_lifecycle(tmp_path):
    db_file = str(tmp_path / "test.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    # Initial default conversation created
    convs = mem.list_conversations()
    assert len(convs) >= 1
    default_id = mem.active_conversation_id
    assert default_id == convs[0]["id"]

    # Create new custom conversation
    conv2_id = mem.create_conversation(title="Second Topic", metadata={"category": "work"})
    assert mem.active_conversation_id == conv2_id

    convs = mem.list_conversations()
    assert len(convs) == 2
    assert convs[0]["id"] == conv2_id
    assert convs[0]["title"] == "Second Topic"
    assert convs[0]["metadata"] == {"category": "work"}

    # Switch back to default
    mem.load_conversation(default_id)
    assert mem.active_conversation_id == default_id

    # Deleting conversation
    deleted = mem.delete_conversation(conv2_id, confirm=True)
    assert deleted is True
    assert len(mem.list_conversations()) == 1

    # Attempting to load invalid conversation
    with pytest.raises(ValueError, match="does not exist"):
        mem.load_conversation("non-existent-uuid-12345")


def test_sqlite_memory_message_crud_and_ordering(tmp_path):
    db_file = str(tmp_path / "test.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    msg1 = Message(role=Role.USER, content="Hello Friday")
    settings = Settings()
    user_name = settings.user_name
    msg2 = Message(role=Role.ASSISTANT, content=f"Hello {user_name}, how can I help you?")

    mem.add_message(msg1)
    mem.add_message(msg2)

    messages = mem.get_messages()
    assert len(messages) == 2
    assert messages[0].role == Role.USER
    assert messages[0].content == "Hello Friday"
    assert messages[1].role == Role.ASSISTANT
    assert messages[1].content == f"Hello {user_name}, how can I help you?"
    assert len(mem) == 2


def test_sqlite_memory_tool_metadata_preservation(tmp_path):
    db_file = str(tmp_path / "test.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    tool_call = ToolCall(id="call_abc_123", name="calculator", arguments={"expression": "25 * 4"})
    assistant_msg = Message(
        role=Role.ASSISTANT,
        content="I will calculate that.",
        tool_calls=[tool_call],
    )
    tool_result_msg = Message(
        role=Role.TOOL,
        name="calculator",
        content="100",
        tool_call_id="call_abc_123",
    )

    mem.add_message(assistant_msg)
    mem.add_message(tool_result_msg)

    messages = mem.get_messages()
    assert len(messages) == 2

    # Verify tool calls reconstructed accurately
    retrieved_assistant = messages[0]
    assert retrieved_assistant.tool_calls is not None
    assert len(retrieved_assistant.tool_calls) == 1
    assert retrieved_assistant.tool_calls[0].id == "call_abc_123"
    assert retrieved_assistant.tool_calls[0].name == "calculator"
    assert retrieved_assistant.tool_calls[0].arguments == {"expression": "25 * 4"}

    # Verify tool result reconstructed accurately
    retrieved_tool = messages[1]
    assert retrieved_tool.role == Role.TOOL
    assert retrieved_tool.name == "calculator"
    assert retrieved_tool.content == "100"
    assert retrieved_tool.tool_call_id == "call_abc_123"


def test_sqlite_memory_context_window(tmp_path):
    db_file = str(tmp_path / "test.db")
    mem = SQLiteConversationMemory(db_path=db_file, max_messages=10)

    for i in range(8):
        mem.add_message(Message(role=Role.USER, content=f"Message {i}"))

    # Slicing context window
    window = mem.get_context_window(3)
    assert len(window) == 3
    assert window[0].content == "Message 5"
    assert window[1].content == "Message 6"
    assert window[2].content == "Message 7"

    # Zero or negative window
    assert mem.get_context_window(0) == []
    assert mem.get_context_window(-5) == []


def test_sqlite_memory_clear(tmp_path):
    db_file = str(tmp_path / "test.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    mem.add_message(Message(role=Role.USER, content="Query 1"))
    mem.add_message(Message(role=Role.ASSISTANT, content="Answer 1"))
    assert len(mem) == 2

    mem.clear(confirm=True)
    assert len(mem) == 0
    assert mem.get_messages() == []


def test_sqlite_memory_multiple_conversations_isolation(tmp_path):
    db_file = str(tmp_path / "test.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    conv_a = mem.create_conversation(title="Topic A")
    mem.add_message(Message(role=Role.USER, content="Message in A"))

    conv_b = mem.create_conversation(title="Topic B")
    mem.add_message(Message(role=Role.USER, content="Message in B 1"))
    mem.add_message(Message(role=Role.USER, content="Message in B 2"))

    # Check isolation via explicit argument and active loading
    assert len(mem.get_messages(conv_a)) == 1
    assert mem.get_messages(conv_a)[0].content == "Message in A"

    assert len(mem.get_messages(conv_b)) == 2
    assert mem.get_messages(conv_b)[1].content == "Message in B 2"

    mem.load_conversation(conv_a)
    assert len(mem) == 1


def test_sqlite_memory_persistence_across_recreation(tmp_path):
    db_file = str(tmp_path / "persisted.db")

    # Session 1: write messages
    mem1 = SQLiteConversationMemory(db_path=db_file)
    conv_id = mem1.active_conversation_id
    mem1.add_message(Message(role=Role.USER, content="Persistent message across shutdown"))

    # Session 2: re-instantiate memory on same file
    mem2 = SQLiteConversationMemory(db_path=db_file, conversation_id=conv_id)
    messages = mem2.get_messages()
    assert len(messages) == 1
    assert messages[0].content == "Persistent message across shutdown"


def test_sqlite_memory_thread_safety(tmp_path):
    db_file = str(tmp_path / "concurrent.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    def worker(worker_id: int):
        for i in range(10):
            mem.add_message(Message(role=Role.USER, content=f"Worker {worker_id} msg {i}"))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    messages = mem.get_messages()
    assert len(messages) == 50
