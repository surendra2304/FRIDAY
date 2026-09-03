"""Tests for Mem0 Memory Adapter and graceful SQLite fallback."""

import pytest
from friday.core.types import Message, Role
from friday.memory.adapters.mem0_adapter import Mem0MemoryAdapter
from friday.memory.in_memory import InMemoryConversationMemory
from friday.memory.sqlite import SQLiteConversationMemory


def test_mem0_adapter_fallback_on_missing_dependency():
    fallback = InMemoryConversationMemory()
    mem = Mem0MemoryAdapter(user_id="user_123", fallback_memory=fallback)

    # mem0ai is not installed, must report is_available=False honestly
    assert mem.is_available is False

    # Storing messages still persists into fallback memory
    mem.add_message(Message(role=Role.USER, content="Remember that my preferred theme is dark mode."))
    mem.add_message(Message(role=Role.ASSISTANT, content="Understood, I will use dark mode."))

    messages = mem.get_messages()
    assert len(messages) == 2
    assert messages[0].content == "Remember that my preferred theme is dark mode."


def test_mem0_adapter_search_with_fallback():
    fallback = InMemoryConversationMemory()
    mem = Mem0MemoryAdapter(user_id="test_user", fallback_memory=fallback)

    mem.add_message(Message(role=Role.USER, content="Python is my preferred programming language for scripting."))
    mem.add_message(Message(role=Role.USER, content="I live in Tokyo."))

    # Keyword search across fallback memory
    results = mem.search("programming language")
    assert len(results) >= 1
    assert any("Python" in r.content for r in results)


def test_mem0_adapter_clear():
    fallback = InMemoryConversationMemory()
    mem = Mem0MemoryAdapter(user_id="test_user", fallback_memory=fallback)

    mem.add_message(Message(role=Role.USER, content="Temp fact"))
    assert len(mem.get_messages()) == 1

    mem.clear()
    assert len(mem.get_messages()) == 0
