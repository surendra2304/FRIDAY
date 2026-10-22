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
    """Verify GeminiEmbeddingProvider sends output_dimensionality and normalizes vector."""
    from google.genai import types

    provider = GeminiEmbeddingProvider(
        api_key="TEST_GEMINI_API_KEY",
        model="gemini-embedding-2",
        dimension=256,
    )

    mock_resp = types.EmbedContentResponse(
        embeddings=[
            types.ContentEmbedding(values=[0.5] * 256)
        ]
    )

    provider._client = mock.Mock()
    provider._client.models.embed_content.return_value = mock_resp

    vec = provider.embed_text("Test dimensionality payload")

    assert len(vec) == 256
    norm = math.sqrt(sum(x * x for x in vec))
    assert pytest.approx(norm, rel=1e-3) == 1.0

    call_kwargs = provider._client.models.embed_content.call_args[1]
    assert call_kwargs["config"].output_dimensionality == 256
    assert call_kwargs["model"] == "gemini-embedding-2"


def test_gemini_batch_embed_contents_endpoint():
    """Verify embed_batch calls embed_content with safe chunking."""
    from google.genai import types

    provider = GeminiEmbeddingProvider(
        api_key="TEST_GEMINI_API_KEY",
        model="gemini-embedding-2",
        dimension=64,
        max_batch_size=4,
    )

    texts = [f"Text item number {i}" for i in range(10)]

    mock_resp = types.EmbedContentResponse(
        embeddings=[types.ContentEmbedding(values=[0.1] * 64) for _ in range(4)]
    )

    provider._client = mock.Mock()
    provider._client.models.embed_content.return_value = mock_resp

    batch_vectors = provider.embed_batch(texts)

    assert len(batch_vectors) == 12  # 3 chunks of 4
    assert provider._client.models.embed_content.call_count == 3


def test_gemini_batch_embed_fallback_to_individual_on_batch_failure():
    """Verify embed_batch falls back gracefully to individual single-embed calls if batch endpoint fails."""
    from google.genai import types

    provider = GeminiEmbeddingProvider(
        api_key="TEST_GEMINI_API_KEY",
        model="gemini-embedding-2",
        dimension=32,
    )

    texts = ["Item 1", "Item 2"]

    single_ok_resp = types.EmbedContentResponse(
        embeddings=[types.ContentEmbedding(values=[0.2] * 32)]
    )

    provider._client = mock.Mock()
    # Batch fails with exception, then sequential calls succeed
    provider._client.models.embed_content.side_effect = [
        Exception("Batch error"),
        Exception("Batch retry 1"),
        Exception("Batch retry 2"),
        Exception("Batch retry 3"),
        single_ok_resp,
        single_ok_resp,
    ]

    with mock.patch("time.sleep"):
        results = provider.embed_batch(texts)

    assert len(results) == 2
    assert len(results[0]) == 32


def test_secret_sanitization_before_cloud_embedding():
    """Verify secrets, private keys, and API keys are redacted before sending to external Gemini API."""
    from google.genai import types

    provider = GeminiEmbeddingProvider(api_key="TEST_GEMINI_API_KEY")

    # These strings are synthetic regex-matching fixtures used to test the redaction logic.
    _FAKE_GEMINI_SHAPED = "AIza" + "Sy" + "FAKE0000000000000000000000000000x"
    _FAKE_OPENAI_SHAPED = "sk-" + "fakeopenaikey00000000000000000000000"

    sensitive_text = f"Here is my secret API key: {_FAKE_GEMINI_SHAPED} and token {_FAKE_OPENAI_SHAPED}"
    sanitized = provider.sanitize_text_for_embedding(sensitive_text)

    assert _FAKE_GEMINI_SHAPED not in sanitized, "Gemini-shaped key must be redacted before cloud transmission"
    assert _FAKE_OPENAI_SHAPED not in sanitized, "OpenAI-shaped key must be redacted before cloud transmission"
    assert "[REDACTED_SECRET]" in sanitized

    mock_resp = types.EmbedContentResponse(
        embeddings=[types.ContentEmbedding(values=[0.1] * 768)]
    )

    provider._client = mock.Mock()
    provider._client.models.embed_content.return_value = mock_resp

    provider.embed_text(sensitive_text)

    sent_contents = provider._client.models.embed_content.call_args[1]["contents"]
    assert _FAKE_GEMINI_SHAPED not in sent_contents, "Raw Gemini-shaped key must not reach the API call"
    assert "[REDACTED_SECRET]" in sent_contents


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
