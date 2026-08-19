"""Comprehensive Memory Quality and Ranking Tests for FRIDAY.

Covers:
- Exact query retrieval
- Paraphrased query retrieval
- No-match query handling
- Trivial query bypass heuristics
- Substantive embedding selection
- Embedding vector deduplication
- Quota exhaustion failover to FTS5
- Embedding/Semantic failure resilience
- Conversation isolation
- Restart persistence
"""

import os
import sqlite3
import tempfile
import time
from unittest import mock
import pytest

from friday.core.types import Message, Role
from friday.memory.policies import should_embed_message, should_retrieve_memory
from friday.memory.sqlite import SQLiteConversationMemory
from friday.memory.embeddings.mock import MockEmbeddingProvider
from friday.core.exceptions import LLMProviderError


@pytest.mark.unit
def test_memory_retrieval_policy_heuristics():
    """Verify should_retrieve_memory correctly filters trivial vs memory-intent queries."""
    # Greetings & pleasantries -> NO RETRIEVAL
    assert should_retrieve_memory("hello") is False
    assert should_retrieve_memory("Hi FRIDAY") is False
    assert should_retrieve_memory("Good morning!") is False
    assert should_retrieve_memory("how are you?") is False

    # Pure math -> NO RETRIEVAL
    assert should_retrieve_memory("what is 2 + 2?") is False
    assert should_retrieve_memory("15 * 84") is False
    assert should_retrieve_memory("calculate 100 / 5") is False

    # Current time/date -> NO RETRIEVAL
    assert should_retrieve_memory("what time is it?") is False
    assert should_retrieve_memory("tell me the time") is False
    assert should_retrieve_memory("what is today's date?") is False

    # Commands & acknowledgements -> NO RETRIEVAL
    assert should_retrieve_memory("stop") is False
    assert should_retrieve_memory("ok thanks") is False

    # Substantive memory inquiries -> RETRIEVAL
    assert should_retrieve_memory("Which editor do I use?") is True
    assert should_retrieve_memory("What did we decide about the website?") is True
    assert should_retrieve_memory("What were my FRIDAY architecture decisions?") is True
    assert should_retrieve_memory("Do you remember my favorite programming language?") is True
    assert should_retrieve_memory("Who is the lead developer on this project?") is True


@pytest.mark.unit
def test_embedding_policy_heuristics():
    """Verify should_embed_message filters trivial/transient messages and retains substantive ones."""
    # Trivial / greeting / acknowledgement messages -> NO EMBEDDING
    assert should_embed_message(Message(role=Role.USER, content="Hello")) is False
    assert should_embed_message(Message(role=Role.USER, content="ok, thanks!")) is False
    assert should_embed_message(Message(role=Role.USER, content="Stop")) is False
    assert should_embed_message(Message(role=Role.USER, content="2 + 2 = 4")) is False
    assert should_embed_message(Message(role=Role.TOOL, content="Execution error: Timeout")) is False

    # Substantive facts and preferences -> EMBEDDING
    assert should_embed_message(Message(role=Role.USER, content="Remember that my favorite code editor is VS Code.")) is True
    assert should_embed_message(Message(role=Role.ASSISTANT, content="We decided to use SQLite with FTS5 and Google Gemini embeddings for hybrid ranking.")) is True
    assert should_embed_message(Message(role=Role.USER, content="Architecture decision: Cloud-first LLM inference with local audio I/O.")) is True


@pytest.mark.integration
def test_exact_and_paraphrased_query_retrieval(tmp_path):
    """Verify exact phrase matching via FTS5 and semantic retrieval via embeddings."""
    db_file = tmp_path / "memory_test.db"
    provider = MockEmbeddingProvider(dimension=32)
    memory = SQLiteConversationMemory(db_path=str(db_file), embedding_provider=provider)

    conv_id = memory.create_conversation("Project Notes")
    memory.add_message(
        Message(role=Role.USER, content="We decided to deploy the web application on Google Cloud Run with PostgreSQL."),
        conversation_id=conv_id,
        auto_embed=True,
    )
    memory.add_message(
        Message(role=Role.USER, content="My favorite code editor is Visual Studio Code."),
        conversation_id=conv_id,
        auto_embed=True,
    )

    # 1. Exact query matching
    exact_results = memory.search("Visual Studio Code", conversation_id=conv_id)
    assert len(exact_results) >= 1
    assert "Visual Studio Code" in exact_results[0].content

    # 2. Hybrid search retrieval
    hybrid_results = memory.search_hybrid("Which cloud service did we choose for deploying the web app?", conversation_id=conv_id)
    assert len(hybrid_results) >= 1
    assert "Google Cloud Run" in hybrid_results[0].content

    # 3. No-match query returns empty without error
    no_match = memory.search_hybrid("Quantum teleportation algorithms in Python", conversation_id=conv_id)
    # If no relevant items pass threshold, should be empty or safe
    assert isinstance(no_match, list)


@pytest.mark.integration
def test_embedding_deduplication(tmp_path):
    """Verify that adding identical text repeatedly reuses cached embeddings and makes 0 additional provider calls."""
    db_file = tmp_path / "dedup_test.db"
    provider = mock.MagicMock(spec=MockEmbeddingProvider)
    provider.dimension = 16
    provider.model = "mock-embed"
    provider.embed_text.return_value = [0.1] * 16

    memory = SQLiteConversationMemory(db_path=str(db_file), embedding_provider=provider)
    conv_id = memory.create_conversation("Dedup Test")

    msg_content = "FRIDAY architecture uses SQLite for zero-cloud persistent storage."

    # First add: calls provider
    memory.add_message(Message(role=Role.USER, content=msg_content), conversation_id=conv_id, auto_embed=True)
    assert provider.embed_text.call_count == 1

    # Second add of identical content: reuses cache from embeddings table
    memory.add_message(Message(role=Role.ASSISTANT, content=msg_content), conversation_id=conv_id, auto_embed=True)
    assert provider.embed_text.call_count == 1  # No additional provider call!


@pytest.mark.integration
def test_quota_exhausted_failover_to_fts5(tmp_path):
    """Verify that when the embedding provider fails with 429 quota exhaustion, FTS5 handles search seamlessly."""
    db_file = tmp_path / "quota_test.db"
    provider = mock.MagicMock()
    provider.dimension = 16
    provider.model = "gemini-embed"
    provider.embed_text.side_effect = LLMProviderError("Gemini embedding rate-limited: 429 Resource Exhausted")

    memory = SQLiteConversationMemory(db_path=str(db_file), embedding_provider=provider)
    conv_id = memory.create_conversation("Quota Failover")

    # Message is saved to SQLite even when embedding provider fails
    memory.add_message(
        Message(role=Role.USER, content="Important project specification: use TLS 1.3 encryption for all connections."),
        conversation_id=conv_id,
        auto_embed=True,
    )

    # Search falls back to FTS5 without raising unhandled exception
    results = memory.search_hybrid("TLS 1.3 encryption", conversation_id=conv_id)
    assert len(results) >= 1
    assert "TLS 1.3" in results[0].content


@pytest.mark.integration
def test_conversation_isolation_and_restart_persistence(tmp_path):
    """Verify conversation isolation and database restart persistence."""
    db_file = str(tmp_path / "persistence_test.db")
    provider = MockEmbeddingProvider(dimension=16)

    # 1. Create and populate conversation A and B
    mem1 = SQLiteConversationMemory(db_path=db_file, embedding_provider=provider)
    conv_a = mem1.create_conversation("Conv A")
    conv_b = mem1.create_conversation("Conv B")

    mem1.add_message(Message(role=Role.USER, content="Secret passcode for Project Alpha is RedFox99."), conversation_id=conv_a)
    mem1.add_message(Message(role=Role.USER, content="Secret passcode for Project Beta is BlueHawk88."), conversation_id=conv_b)

    # Isolation check
    res_a = mem1.search("Secret passcode", conversation_id=conv_a)
    assert len(res_a) == 1
    assert "RedFox99" in res_a[0].content
    assert "BlueHawk88" not in res_a[0].content

    # 2. Simulate complete restart (new instance on same db file)
    mem2 = SQLiteConversationMemory(db_path=db_file, embedding_provider=provider)
    res_b = mem2.search("Secret passcode", conversation_id=conv_b)
    assert len(res_b) == 1
    assert "BlueHawk88" in res_b[0].content
