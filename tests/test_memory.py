"""Tests for memory subsystem."""

from friday.core.types import Message, Role
from friday.memory.in_memory import InMemoryConversationMemory


def test_in_memory_add_and_retrieve():
    mem = InMemoryConversationMemory(max_messages=5)
    msg1 = Message(role=Role.USER, content="Hello")
    msg2 = Message(role=Role.ASSISTANT, content="Hi there")

    mem.add_message(msg1)
    mem.add_message(msg2)

    messages = mem.get_messages()
    assert len(messages) == 2
    assert messages[0].content == "Hello"
    assert messages[1].content == "Hi there"


def test_in_memory_sliding_window():
    mem = InMemoryConversationMemory(max_messages=3)
    for i in range(5):
        mem.add_message(Message(role=Role.USER, content=f"Msg {i}"))

    messages = mem.get_messages()
    assert len(messages) == 3
    assert messages[0].content == "Msg 2"
    assert messages[1].content == "Msg 3"
    assert messages[2].content == "Msg 4"


def test_in_memory_context_window():
    mem = InMemoryConversationMemory(max_messages=10)
    for i in range(6):
        mem.add_message(Message(role=Role.USER, content=f"Msg {i}"))

    window = mem.get_context_window(2)
    assert len(window) == 2
    assert window[0].content == "Msg 4"
    assert window[1].content == "Msg 5"


def test_in_memory_clear():
    mem = InMemoryConversationMemory(max_messages=5)
    mem.add_message(Message(role=Role.USER, content="Test"))
    assert len(mem) == 1

    mem.clear()
    assert len(mem) == 0
    assert mem.get_messages() == []
