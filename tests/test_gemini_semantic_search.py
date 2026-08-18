"""Tests for Gemini Semantic Embeddings, Batching, RRF Hybrid Search, and Privacy Controls."""

import math
import uuid
from unittest import mock
import pytest
from friday.core.types import EmbeddingRecord, Message, Role
from friday.memory.embeddings.gemini import GeminiEmbeddingProvider
from friday.memory.embeddings.mock import MockEmbeddingProvider
from friday.memory.sqlite import SQLiteConversationMemory


def test_gemini_embedding_output_dimensionality():
    """Verify GeminiEmbeddingProvider sends outputDimensionality in payload and normalizes vector."""
    provider = GeminiEmbeddingProvider(
        api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12",
        model="text-embedding-004",
        dimension=256,
    )

    mock_resp = mock.Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "embedding": {
            "values": [0.5] * 256
        }
    }

    with mock.patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        vec = provider.embed_text("Test dimensionality payload")

    assert len(vec) == 256
    norm = math.sqrt(sum(x * x for x in vec))
    assert pytest.approx(norm, rel=1e-3) == 1.0

    call_payload = mock_post.call_args[1]["json"]
    assert call_payload["outputDimensionality"] == 256
    assert "models/text-embedding-004:embedContent" in mock_post.call_args[0][0]


def test_gemini_batch_embed_contents_endpoint():
    """Verify embed_batch calls batchEmbedContents with safe chunking."""
    provider = GeminiEmbeddingProvider(
        api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12",
        model="text-embedding-004",
        dimension=64,
        max_batch_size=4,
    )

    texts = [f"Text item number {i}" for i in range(10)]

    mock_resp = mock.Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "embeddings": [
            {"values": [0.1] * 64} for _ in range(4)
        ]
    }

    with mock.patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        batch_vectors = provider.embed_batch(texts)

    assert len(batch_vectors) == 12  # 3 chunks of 4 (padded by mock return in test)
    assert mock_post.call_count == 3  # 10 items in chunks of 4 -> 3 requests
    assert "batchEmbedContents" in mock_post.call_args[0][0]


def test_gemini_batch_embed_fallback_to_individual_on_batch_failure():
    """Verify embed_batch falls back gracefully to individual single-embed calls if batch endpoint fails."""
    provider = GeminiEmbeddingProvider(
        api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12",
        model="text-embedding-004",
        dimension=32,
    )

    texts = ["Item 1", "Item 2"]

    batch_fail_resp = mock.Mock()
    batch_fail_resp.status_code = 404
    batch_fail_resp.text = "batchEmbedContents Not Found"
    batch_fail_resp.json.side_effect = Exception("Not JSON")

    single_ok_resp = mock.Mock()
    single_ok_resp.status_code = 200
    single_ok_resp.json.return_value = {"embedding": {"values": [0.2] * 32}}

    with mock.patch("httpx.Client.post", side_effect=[batch_fail_resp, single_ok_resp, single_ok_resp]):
        results = provider.embed_batch(texts)

    assert len(results) == 2
    assert len(results[0]) == 32


def test_secret_sanitization_before_cloud_embedding():
    """Verify secrets, private keys, and API keys are redacted before sending to external Gemini API."""
    provider = GeminiEmbeddingProvider(api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12")

    sensitive_text = "Here is my secret API key: TEST_GEMINI_API_KEY_PLACEHOLDER_08 and token sk-123456789012345678901234"
    sanitized = provider.sanitize_text_for_embedding(sensitive_text)

    assert "TEST_GEMINI_API_KEY_PLACEHOLDER_17ABCDEF" not in sanitized
    assert "sk-1234567890" not in sanitized
    assert "[REDACTED_SECRET]" in sanitized

    mock_resp = mock.Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"embedding": {"values": [0.1] * 768}}

    with mock.patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        provider.embed_text(sensitive_text)

    sent_payload = mock_post.call_args[1]["json"]
    sent_text = sent_payload["content"]["parts"][0]["text"]
    assert "TEST_GEMINI_API_KEY_PLACEHOLDER_17ABCDEF" not in sent_text
    assert "[REDACTED_SECRET]" in sent_text


def test_reciprocal_rank_fusion_hybrid_search(tmp_path):
    """Verify hybrid search fuses FTS5 lexical scores and semantic similarity using RRF."""
    db_path = str(tmp_path / "test_rrf.db")
    embed_provider = MockEmbeddingProvider(dimension=64)
    mem = SQLiteConversationMemory(db_path=db_path, embedding_provider=embed_provider)

    conv_id = mem.create_conversation(title="Hybrid Search Project")
    mem.load_conversation(conv_id)

    # 1. Message with strong lexical match for 'microservices'
    mem.add_message(Message(role=Role.USER, content="Our architecture uses Kubernetes microservices."))
    mem.add_embedding(
        EmbeddingRecord(
            id=str(uuid.uuid4()),
            conversation_id=conv_id,
            source_text="Our architecture uses Kubernetes microservices.",
            embedding=embed_provider.embed_text("Our architecture uses Kubernetes microservices."),
            model="mock",
            dimension=64,
            metadata={"role": "user"},
        )
    )

    # 2. Message with strong semantic relevance to 'distributed systems'
    mem.add_message(Message(role=Role.ASSISTANT, content="Distributed consensus protocols ensure data integrity."))
    mem.add_embedding(
        EmbeddingRecord(
            id=str(uuid.uuid4()),
            conversation_id=conv_id,
            source_text="Distributed consensus protocols ensure data integrity.",
            embedding=embed_provider.embed_text("Distributed consensus protocols ensure data integrity."),
            model="mock",
            dimension=64,
            metadata={"role": "assistant"},
        )
    )

    # Hybrid query matching full semantic string + lexical query
    target_query = "Our architecture uses Kubernetes microservices."
    results = mem.search_hybrid(query=target_query, conversation_id=conv_id, limit=5)
    assert len(results) >= 1
    assert "microservices" in results[0].content
    assert results[0].score > 0.0

    # Lexical-only hybrid query
    lex_results = mem.search_hybrid(query="consensus", conversation_id=conv_id, limit=5)
    assert len(lex_results) >= 1
    assert "consensus" in lex_results[0].content


def test_hybrid_search_graceful_fallback_when_embedding_fails(tmp_path):
    """Verify hybrid search continues functioning cleanly via FTS5 if embedding provider raises an exception."""
    db_path = str(tmp_path / "test_hybrid_fallback.db")
    embed_provider = MockEmbeddingProvider(dimension=64)
    mem = SQLiteConversationMemory(db_path=db_path, embedding_provider=embed_provider)

    conv_id = mem.create_conversation(title="Resilience Test")
    mem.load_conversation(conv_id)
    mem.add_message(Message(role=Role.USER, content="Docker container optimization techniques."))

    # Force embed_text to fail
    with mock.patch.object(embed_provider, "embed_text", side_effect=Exception("Gemini 503 Service Unavailable")):
        results = mem.search_hybrid(query="Docker", conversation_id=conv_id)

    assert len(results) >= 1
    assert "Docker" in results[0].content
