"""Unit and integration tests for persistent conversation management."""

import pytest

from friday.agent.agent import FridayAgent
from friday.core.config import Settings
from friday.llm.mock_provider import MockLLMProvider


def test_create_and_list_conversations(tmp_path):
    db_file = str(tmp_path / "conv_mgr.db")
    settings = Settings(
        env="testing",
        memory_backend="sqlite",
        memory_db_path=db_file,
    )
    agent = FridayAgent(settings=settings, llm_provider=MockLLMProvider())

    # Initially has 1 default conversation
    convs = agent.list_conversations()
    assert len(convs) == 1
    default_id = agent.conversation_id
    assert convs[0]["id"] == default_id

    # Create new conversation
    new_id = agent.create_new_conversation(title="Project Alpha")
    assert new_id != default_id
    assert agent.conversation_id == new_id

    # List conversations reflects both
    convs_after = agent.list_conversations()
    assert len(convs_after) == 2
    titles = [c["title"] for c in convs_after]
    assert "Project Alpha" in titles


def test_switch_and_isolate_conversations(tmp_path):
    db_file = str(tmp_path / "conv_switch.db")
    settings = Settings(
        env="testing",
        memory_backend="sqlite",
        memory_db_path=db_file,
    )
    agent = FridayAgent(settings=settings, llm_provider=MockLLMProvider())

    conv1 = agent.conversation_id
    agent.process_message("Conversation 1 secret: Apple")

    # Create and switch to conversation 2
    conv2 = agent.create_new_conversation(title="Topic 2")
    agent.process_message("Conversation 2 secret: Banana")

    assert len(agent.get_history()) == 2
    assert "Banana" in agent.get_history()[0].content

    # Switch back to conversation 1
    agent.switch_conversation(conv1)
    assert agent.conversation_id == conv1
    assert len(agent.get_history()) == 2
    assert "Apple" in agent.get_history()[0].content


def test_rename_conversation(tmp_path):
    db_file = str(tmp_path / "conv_rename.db")
    settings = Settings(
        env="testing",
        memory_backend="sqlite",
        memory_db_path=db_file,
    )
    agent = FridayAgent(settings=settings, llm_provider=MockLLMProvider())

    conv_id = agent.conversation_id
    ok = agent.rename_conversation("Renamed Title")
    assert ok is True

    curr = agent.get_current_conversation()
    assert curr is not None
    assert curr["title"] == "Renamed Title"

    # Rename non-existent
    ok_bad = agent.rename_conversation("Bad", conversation_id="nonexistent-id-12345")
    assert ok_bad is False


def test_get_current_conversation_metadata(tmp_path):
    db_file = str(tmp_path / "conv_curr.db")
    settings = Settings(
        env="testing",
        memory_backend="sqlite",
        memory_db_path=db_file,
    )
    agent = FridayAgent(settings=settings, llm_provider=MockLLMProvider())

    agent.process_message("Turn 1")
    curr = agent.get_current_conversation()
    assert curr is not None
    assert curr["id"] == agent.conversation_id
    assert curr["message_count"] == 2
    assert "created_at" in curr
    assert "updated_at" in curr


def test_delete_conversation_lifecycle(tmp_path):
    db_file = str(tmp_path / "conv_del.db")
    settings = Settings(
        env="testing",
        memory_backend="sqlite",
        memory_db_path=db_file,
    )
    agent = FridayAgent(settings=settings, llm_provider=MockLLMProvider())

    conv1 = agent.conversation_id
    conv2 = agent.create_new_conversation(title="To be deleted")

    assert len(agent.list_conversations()) == 2

    # Delete conv2
    deleted = agent.delete_conversation(conv2)
    assert deleted is True

    # Remaining conversation is 1 and active session switches
    convs = agent.list_conversations()
    assert len(convs) == 1
    assert convs[0]["id"] == conv1


def test_invalid_and_nonexistent_conversation_switching(tmp_path):
    db_file = str(tmp_path / "conv_invalid.db")
    settings = Settings(
        env="testing",
        memory_backend="sqlite",
        memory_db_path=db_file,
    )
    agent = FridayAgent(settings=settings, llm_provider=MockLLMProvider())

    with pytest.raises(ValueError, match="does not exist"):
        agent.switch_conversation("completely-fake-id-999")


def test_conversation_persistence_across_agent_restarts(tmp_path):
    db_file = str(tmp_path / "conv_restart.db")
    settings = Settings(
        env="testing",
        memory_backend="sqlite",
        memory_db_path=db_file,
    )

    # Session 1: Create 2 conversations
    agent1 = FridayAgent(settings=settings, llm_provider=MockLLMProvider())
    id1 = agent1.conversation_id
    agent1.rename_conversation("First Chat")
    agent1.process_message("Remember 12345")

    id2 = agent1.create_new_conversation(title="Second Chat")
    agent1.process_message("Remember 67890")

    # Session 2: Fresh agent instance attaching to same database file by resuming conversation id2
    agent2 = FridayAgent(settings=settings, llm_provider=MockLLMProvider(), conversation_id=id2)
    convs = agent2.list_conversations()
    assert len(convs) == 2

    # Check both conversations are retrievable
    agent2.switch_conversation(id1)
    assert "12345" in agent2.get_history()[0].content

    agent2.switch_conversation(id2)
    assert "67890" in agent2.get_history()[0].content
