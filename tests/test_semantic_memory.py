"""Tests for FRIDAY's provider-independent semantic memory architecture."""

from datetime import datetime, timezone
import uuid
from unittest import mock
import pytest
from friday.core.config import Settings
from friday.core.exceptions import LLMProviderError
from friday.core.types import EmbeddingRecord, Message, Role
from friday.memory.embeddings.base import BaseEmbeddingProvider
from friday.memory.embeddings.factory import create_embedding_provider
from friday.memory.embeddings.gemini import GeminiEmbeddingProvider
from friday.memory.embeddings.mock import MockEmbeddingProvider
from friday.memory.factory import create_memory
from friday.memory.in_memory import InMemoryConversationMemory
from friday.memory.sqlite import SQLiteConversationMemory


def test_mock_embedding_provider_deterministic_unit_vectors():
    """Verify mock embedding provider generates deterministic, normalized unit vectors."""
    provider = MockEmbeddingProvider(dimension=128)
    vec1 = provider.embed_text("My favorite IDE is VS Code")
    vec2 = provider.embed_text("My favorite IDE is VS Code")
    vec_diff = provider.embed_text("Quantum computing algorithms")

    assert len(vec1) == 128
    assert vec1 == vec2  # Deterministic
    assert vec1 != vec_diff  # Distinct texts yield distinct vectors

    # Verify unit length (L2 norm approx 1.0)
    norm = sum(x * x for x in vec1) ** 0.5
    assert pytest.approx(norm, rel=1e-3) == 1.0


def test_gemini_embedding_provider_remote_call_and_api_key_check():
    """Verify Gemini embedding provider calls GenAI SDK with correct schema."""
    from google.genai import types

    provider_missing_key = GeminiEmbeddingProvider(api_key="")
    with pytest.raises(LLMProviderError) as exc_info:
        provider_missing_key.embed_text("Test prompt")
    assert "Gemini API key is required" in str(exc_info.value)

    provider = GeminiEmbeddingProvider(api_key="TEST_GEMINI_API_KEY", model="gemini-embedding-2", dimension=768)
    mock_resp = types.EmbedContentResponse(
        embeddings=[types.ContentEmbedding(values=[0.123] * 768)]
    )

    provider._client = mock.Mock()
    provider._client.models.embed_content.return_value = mock_resp

    vec = provider.embed_text("Hello Gemini embeddings")

    assert len(vec) == 768
    norm = sum(x * x for x in vec) ** 0.5
    assert pytest.approx(norm, rel=1e-3) == 1.0
    assert provider._client.models.embed_content.called
    call_kwargs = provider._client.models.embed_content.call_args[1]
    assert call_kwargs["model"] == "gemini-embedding-2"
    assert call_kwargs["config"].output_dimensionality == 768


def test_embedding_factory_creation():
    """Verify embedding factory correctly instantiates providers based on Settings."""
    mock_settings = Settings(embedding_provider="mock", embedding_dimension=256)
    prov = create_embedding_provider(mock_settings)
    assert isinstance(prov, MockEmbeddingProvider)
    assert prov.dimension == 256

    gemini_settings = Settings(embedding_provider="gemini", gemini_api_key="TEST_GEMINI_API_KEY")
    prov_gemini = create_embedding_provider(gemini_settings)
    assert isinstance(prov_gemini, GeminiEmbeddingProvider)

    disabled_settings = Settings(embedding_provider="none")
    assert create_embedding_provider(disabled_settings) is None


def test_sqlite_embedding_storage_and_semantic_retrieval(tmp_path):
    """Verify storing embedding records in SQLite and retrieving via cosine similarity."""
    db_path = str(tmp_path / "test_semantic.db")
    embed_provider = MockEmbeddingProvider(dimension=64)
    mem = SQLiteConversationMemory(db_path=db_path, embedding_provider=embed_provider)

    conv_id = mem.create_conversation(title="Tech Preferences")

    # Store 3 distinct semantic memories
    mem1_text = "I prefer developing in Python using FastAPI."
    rec1 = EmbeddingRecord(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        source_text=mem1_text,
        embedding=embed_provider.embed_text(mem1_text),
        model="mock-embedding-v1",
        dimension=64,
        metadata={"category": "coding"},
    )
    mem.add_embedding(rec1)

    mem2_text = "My favorite food is spicy chicken curry."
    rec2 = EmbeddingRecord(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        source_text=mem2_text,
        embedding=embed_provider.embed_text(mem2_text),
        model="mock-embedding-v1",
        dimension=64,
        metadata={"category": "food"},
    )
    mem.add_embedding(rec2)

    # Verify retrieval
    stored = mem.get_embeddings_for_conversation(conv_id)
    assert len(stored) == 2

    # Query with exact semantic match
    results = mem.search_semantic(query=mem1_text, conversation_id=conv_id, limit=5)
    assert len(results) >= 1
    assert results[0].source_text == mem1_text
    assert pytest.approx(results[0].score, rel=1e-2) == 1.0
    assert results[0].metadata["category"] == "coding"


def test_semantic_search_dimension_mismatch_resilience(tmp_path):
    """Verify dimension mismatches are caught safely without crashing the search."""
    db_path = str(tmp_path / "test_dim_mismatch.db")
    embed_provider = MockEmbeddingProvider(dimension=64)
    mem = SQLiteConversationMemory(db_path=db_path, embedding_provider=embed_provider)

    conv_id = mem.create_conversation(title="Dimension Test")

    # Insert a record with dimension 32 (mismatched with provider dimension 64)
    bad_rec = EmbeddingRecord(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        source_text="Mismatched vector size text",
        embedding=[0.5] * 32,
        model="legacy-model",
        dimension=32,
    )
    mem.add_embedding(bad_rec)

    # Also insert a valid record
    good_text = "Correctly dimensioned memory"
    good_rec = EmbeddingRecord(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        source_text=good_text,
        embedding=embed_provider.embed_text(good_text),
        model="mock-embedding-v1",
        dimension=64,
    )
    mem.add_embedding(good_rec)

    # Search with dimension 64 provider: should skip bad_rec and return good_rec
    results = mem.search_semantic(query=good_text, conversation_id=conv_id)
    assert len(results) == 1
    assert results[0].source_text == good_text


def test_semantic_search_provider_failure_recovery(tmp_path):
    """Verify semantic search returns empty result safely when embedding provider raises an error."""
    db_path = str(tmp_path / "test_fail.db")
    embed_provider = MockEmbeddingProvider(dimension=64)
    mem = SQLiteConversationMemory(db_path=db_path, embedding_provider=embed_provider)

    with mock.patch.object(embed_provider, "embed_text", side_effect=Exception("API connection timeout")):
        results = mem.search_semantic("Any query")

    assert results == []


def test_hybrid_search_fts_fallback_when_embedding_unavailable(tmp_path):
    """Verify hybrid search seamlessly falls back to FTS5 keyword retrieval if embedding provider is None or fails."""
    db_path = str(tmp_path / "test_fallback.db")
    # Initialize without embedding provider (None)
    mem = SQLiteConversationMemory(db_path=db_path, embedding_provider=None)
    conv_id = mem.create_conversation(title="Project Discussion")
    mem.load_conversation(conv_id)

    # Add message into FTS5
    mem.add_message(Message(role=Role.USER, content="We are migrating our database to PostgreSQL."))
    mem.add_message(Message(role=Role.ASSISTANT, content="PostgreSQL migration plan prepared."))

    # Hybrid search should automatically fall back to FTS5
    results = mem.search_hybrid(query="PostgreSQL", conversation_id=conv_id)
    assert len(results) >= 1
    assert "PostgreSQL" in results[0].content


def test_semantic_memory_privacy_and_conversation_isolation(tmp_path):
    """Verify semantic searches respect conversation_id boundaries and do not leak across conversations."""
    db_path = str(tmp_path / "test_isolation.db")
    embed_provider = MockEmbeddingProvider(dimension=64)
    mem = SQLiteConversationMemory(db_path=db_path, embedding_provider=embed_provider)

    conv_a = mem.create_conversation(title="Work Conversation")
    conv_b = mem.create_conversation(title="Personal Conversation")

    secret_work = "Confidential API token 994829184"
    mem.add_embedding(
        EmbeddingRecord(
            id=str(uuid.uuid4()),
            conversation_id=conv_a,
            source_text=secret_work,
            embedding=embed_provider.embed_text(secret_work),
            model="mock",
            dimension=64,
        )
    )

    personal_text = "Grocery list: apples, milk, bread"
    mem.add_embedding(
        EmbeddingRecord(
            id=str(uuid.uuid4()),
            conversation_id=conv_b,
            source_text=personal_text,
            embedding=embed_provider.embed_text(personal_text),
            model="mock",
            dimension=64,
        )
    )

    # Search within conv_b for work text: must NEVER leak conv_a secret record
    results = mem.search_semantic(query=secret_work, conversation_id=conv_b)
    assert all(r.conversation_id == conv_b for r in results)
    assert not any(secret_work in r.source_text for r in results)

    # Search within conv_b with high threshold: conv_b has no matching record
    results_threshold = mem.search_semantic(query=secret_work, conversation_id=conv_b, threshold=0.9)
    assert len(results_threshold) == 0

    # Search within conv_a: must find the work record
    results_work = mem.search_semantic(query=secret_work, conversation_id=conv_a, threshold=0.9)
    assert len(results_work) == 1
    assert results_work[0].source_text == secret_work
    assert results_work[0].conversation_id == conv_a
