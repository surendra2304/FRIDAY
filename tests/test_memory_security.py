"""Security and privacy tests for persistent memory and data retention."""

from datetime import datetime, timedelta, timezone

from friday.agent.agent import FridayAgent
from friday.core.config import Settings
from friday.core.types import Message, Role
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.sqlite import SQLiteConversationMemory


def test_deletion_isolation_does_not_affect_other_conversations(tmp_path):
    db_file = str(tmp_path / "privacy_isolation.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    c1 = mem.create_conversation(title="Private Medical Notes")
    mem.load_conversation(c1)
    mem.add_message(Message(role=Role.USER, content="Sensitive medical record #9988"))

    c2 = mem.create_conversation(title="Work Project")
    mem.load_conversation(c2)
    mem.add_message(Message(role=Role.USER, content="Work task #1234"))

    assert len(mem.list_conversations()) == 3  # Default + c1 + c2

    # Delete c1
    mem.delete_conversation(c1, confirm=True)

    # c2 must remain intact
    mem.load_conversation(c2)
    msgs_c2 = mem.get_messages()
    assert len(msgs_c2) == 1
    assert "Work task #1234" in msgs_c2[0].content

    # Search for c1 content must yield empty
    search_res = mem.search("medical record")
    assert len(search_res) == 0


def test_search_privacy_isolation(tmp_path):
    db_file = str(tmp_path / "search_privacy.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    c_secret = mem.create_conversation(title="Confidential")
    mem.load_conversation(c_secret)
    mem.add_message(Message(role=Role.USER, content="Project Blue password is alpha_bravo_charlie"))

    c_public = mem.create_conversation(title="Public Chat")
    mem.load_conversation(c_public)
    mem.add_message(Message(role=Role.USER, content="Discussing general topics."))

    # Searching with scope c_public must NEVER find secret from c_secret
    scoped_results = mem.search("alpha_bravo_charlie", conversation_id=c_public)
    assert len(scoped_results) == 0

    # Scoped search to c_secret finds it
    secret_results = mem.search("alpha_bravo_charlie", conversation_id=c_secret)
    assert len(secret_results) == 1


def test_purge_all_memory_security(tmp_path):
    db_file = str(tmp_path / "purge_test.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    for i in range(5):
        c_id = mem.create_conversation(title=f"Chat {i}")
        mem.load_conversation(c_id)
        mem.add_message(Message(role=Role.USER, content=f"Secret message {i}"))

    assert len(mem.list_conversations()) == 6  # Default + 5

    # Purge all
    purged_count = mem.purge_all()
    assert purged_count == 6

    # Verify only 1 fresh default conversation exists and contains 0 messages
    convs_after = mem.list_conversations()
    assert len(convs_after) == 1
    assert convs_after[0]["message_count"] == 0

    # Search must find nothing
    assert mem.search("Secret message") == []


def test_configurable_retention_prunes_only_old_messages(tmp_path):
    db_file = str(tmp_path / "retention_test.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=40)
    recent_time = now - timedelta(days=5)

    msg_expired = Message(role=Role.USER, content="Old message from last month", timestamp=old_time)
    msg_valid = Message(role=Role.USER, content="Recent message from this week", timestamp=recent_time)

    mem.add_message(msg_expired)
    mem.add_message(msg_valid)

    assert len(mem.get_messages()) == 2

    # Prune with 30-day retention policy
    pruned_count = mem.prune_expired_messages(retention_days=30)
    assert pruned_count == 1

    remaining = mem.get_messages()
    assert len(remaining) == 1
    assert remaining[0].content == "Recent message from this week"


def test_auto_prune_on_agent_startup(tmp_path):
    db_file = str(tmp_path / "agent_retention.db")
    
    # Pre-populate database with old and new messages
    mem = SQLiteConversationMemory(db_path=db_file)
    c1 = mem.active_conversation_id
    now = datetime.now(timezone.utc)
    mem.add_message(Message(role=Role.USER, content="Expired turn", timestamp=now - timedelta(days=60)))
    mem.add_message(Message(role=Role.USER, content="Fresh turn", timestamp=now - timedelta(days=2)))

    # Startup FridayAgent with memory_retention_days=30
    settings = Settings(
        env="testing",
        memory_backend="sqlite",
        memory_db_path=db_file,
        memory_retention_days=30,
    )
    agent = FridayAgent(settings=settings, llm_provider=MockLLMProvider(), conversation_id=c1)

    history = agent.get_history()
    assert len(history) == 1
    assert history[0].content == "Fresh turn"


def test_secret_masking_in_agent_status(tmp_path):
    settings = Settings(
        env="testing",
        llm_api_key="sk-super-secret-key-12345",
        memory_backend="sqlite",
        memory_db_path=str(tmp_path / "status_test.db"),
    )
    agent = FridayAgent(settings=settings, llm_provider=MockLLMProvider())
    status = agent.get_status()

    # Status must NOT contain the raw API key anywhere in its keys/values
    for k, v in status.items():
        assert "sk-super-secret-key-12345" not in str(k)
        assert "sk-super-secret-key-12345" not in str(v)
