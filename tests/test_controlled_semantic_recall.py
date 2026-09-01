"""Tests for controlled semantic memory recall, bounded context injection, and user observability."""

from unittest import mock

from friday.agent.agent import FridayAgent
from friday.core.config import Settings
from friday.core.types import Message, Role
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.embeddings.mock import MockEmbeddingProvider
from friday.memory.sqlite import SQLiteConversationMemory


def test_controlled_recall_retrieves_relevant_memory(tmp_path):
    """Verify agent retrieves relevant historical memory and injects it into LLM context."""
    db_path = str(tmp_path / "test_recall.db")
    embed_provider = MockEmbeddingProvider(dimension=64)
    mem = SQLiteConversationMemory(db_path=db_path, embedding_provider=embed_provider)

    # Store a historical fact in conversation 1
    conv_1 = mem.create_conversation(title="Preferences")
    mem.load_conversation(conv_1)
    mem.add_message(Message(role=Role.USER, content="My favorite code editor is VS Code with Dracula theme."))

    # Switch to conversation 2
    conv_2 = mem.create_conversation(title="New Task")
    mem.load_conversation(conv_2)

    settings = Settings(
        memory_backend="sqlite",
        memory_db_path=db_path,
        embedding_provider="mock",
        retrieval_mode="hybrid",
        max_recalled_memories=2,
        recall_similarity_threshold=0.5,
        enable_auto_recall=True,
    )
    llm_provider = MockLLMProvider()
    agent = FridayAgent(settings=settings, llm_provider=llm_provider, memory=mem)

    # Process query that semantically/lexically matches preference
    query = "What is my favorite code editor and theme?"
    with mock.patch.object(llm_provider, "generate", wraps=llm_provider.generate) as mock_gen:
        resp = agent.process_message(query)

    assert resp.is_done is True
    assert "recalled_memories" in resp.metadata
    recalled = resp.metadata["recalled_memories"]
    assert len(recalled) >= 1
    assert "VS Code with Dracula theme" in recalled[0]["content"]

    # Verify context passed to LLM contained the historical block
    call_messages = mock_gen.call_args[1]["messages"]
    system_msg = call_messages[0].content
    assert "[Relevant Historical Memories]" in system_msg
    assert "VS Code with Dracula theme" in system_msg


def test_controlled_recall_excludes_irrelevant_memories(tmp_path):
    """Verify irrelevant historical conversations are not injected into the prompt."""
    db_path = str(tmp_path / "test_irrelevant.db")
    embed_provider = MockEmbeddingProvider(dimension=64)
    mem = SQLiteConversationMemory(db_path=db_path, embedding_provider=embed_provider)

    conv_1 = mem.create_conversation(title="Cooking")
    mem.load_conversation(conv_1)
    mem.add_message(Message(role=Role.USER, content="How do you make spicy pasta with garlic?"))

    settings = Settings(
        memory_backend="sqlite",
        memory_db_path=db_path,
        retrieval_mode="hybrid",
        enable_auto_recall=True,
    )
    llm_provider = MockLLMProvider()
    agent = FridayAgent(settings=settings, llm_provider=llm_provider, memory=mem)

    # Query completely unrelated to pasta
    resp = agent.process_message("Show system memory and CPU utilization")

    assert resp.is_done is True
    # Pasta memory should NOT be recalled for a CPU query
    recalled = resp.metadata.get("recalled_memories", [])
    assert not any("pasta" in r["content"].lower() for r in recalled)


def test_controlled_recall_bounded_limits_and_character_ceiling(tmp_path):
    """Verify max_recalled_memories and max_recall_chars enforce strict bounds."""
    db_path = str(tmp_path / "test_bounds.db")
    embed_provider = MockEmbeddingProvider(dimension=64)
    mem = SQLiteConversationMemory(db_path=db_path, embedding_provider=embed_provider)

    conv_1 = mem.create_conversation(title="Multi Memory")
    mem.load_conversation(conv_1)

    # Insert multiple matching memories
    for i in range(10):
        mem.add_message(Message(role=Role.USER, content=f"Database migration checkpoint step {i}: table created."))

    settings = Settings(
        memory_backend="sqlite",
        memory_db_path=db_path,
        retrieval_mode="hybrid",
        max_recalled_memories=2,  # Strict cap of 2
        max_recall_chars=120,      # Strict char limit
        enable_auto_recall=True,
    )
    llm_provider = MockLLMProvider()
    agent = FridayAgent(settings=settings, llm_provider=llm_provider, memory=mem)

    resp = agent.process_message("What were the database migration steps?")
    recalled = resp.metadata.get("recalled_memories", [])
    assert len(recalled) <= 2
    total_chars = sum(len(r["content"]) for r in recalled)
    assert total_chars <= 120


def test_controlled_recall_fts_fallback_when_embedding_disabled(tmp_path):
    """Verify agent uses FTS keyword recall cleanly when embedding provider is disabled."""
    db_path = str(tmp_path / "test_fts_recall.db")
    mem = SQLiteConversationMemory(db_path=db_path, embedding_provider=None)

    conv_1 = mem.create_conversation(title="Deployment Notes")
    mem.load_conversation(conv_1)
    mem.add_message(Message(role=Role.USER, content="Kubernetes cluster deployed in us-west-2 region."))

    conv_2 = mem.create_conversation(title="Active Session")
    mem.load_conversation(conv_2)

    settings = Settings(
        memory_backend="sqlite",
        memory_db_path=db_path,
        embedding_provider="none",
        retrieval_mode="hybrid",  # Hybrid with None embedding provider -> FTS fallback
        enable_auto_recall=True,
    )
    llm_provider = MockLLMProvider()
    agent = FridayAgent(settings=settings, llm_provider=llm_provider, memory=mem)

    resp = agent.process_message("Where is our Kubernetes cluster deployed?")
    recalled = resp.metadata.get("recalled_memories", [])
    assert len(recalled) >= 1
    assert "us-west-2" in recalled[0]["content"]


def test_controlled_recall_persistence_across_agent_restart(tmp_path):
    """Verify creating a new FridayAgent instance across process restarts retains and recalls memory."""
    db_path = str(tmp_path / "test_restart_recall.db")
    embed_provider = MockEmbeddingProvider(dimension=64)

    # Session 1: Store information
    settings = Settings(
        memory_backend="sqlite",
        memory_db_path=db_path,
        embedding_provider="mock",
        retrieval_mode="hybrid",
        enable_auto_recall=True,
    )
    mem1 = SQLiteConversationMemory(db_path=db_path, embedding_provider=embed_provider)
    agent1 = FridayAgent(settings=settings, llm_provider=MockLLMProvider(), memory=mem1)
    agent1.process_message("Remember that project Phoenix deadline is September 30.")

    # Session 2: "Restart" with fresh agent and memory instance
    mem2 = SQLiteConversationMemory(db_path=db_path, embedding_provider=embed_provider)
    conv_new = mem2.create_conversation(title="Follow Up")
    mem2.load_conversation(conv_new)
    agent2 = FridayAgent(settings=settings, llm_provider=MockLLMProvider(), memory=mem2)

    resp2 = agent2.process_message("When is the Phoenix deadline?")
    recalled = resp2.metadata.get("recalled_memories", [])
    assert len(recalled) >= 1
    assert "September 30" in recalled[0]["content"]
