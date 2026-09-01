"""Unit tests for Full-Duplex Voice Engine2: True Semantic Vector Memory (ChromaDB + Gemini Embeddings)."""

import time

from friday.memory.embeddings.base import BaseEmbeddingProvider
from friday.memory.sqlite import SQLiteConversationMemory
from friday.memory.vector_store import ChromaVectorStore


class MockConceptEmbeddingProvider(BaseEmbeddingProvider):
    """Mock embedding provider that maps similar concepts (e.g., coding and programming) to close vectors."""

    def __init__(self, dimension: int = 4):
        super().__init__(model="mock-embedding-v2", dimension=dimension)

    @property
    def provider_name(self) -> str:
        return "mock_concept"

    def embed_text(self, text: str) -> list[float]:
        t = (text or "").lower()
        # "coding", "programming", "software", "python" -> vector [1.0, 0.0, 0.0, 0.0]
        if any(w in t for w in ["cod", "program", "software", "python", "script"]):
            return [1.0, 0.0, 0.0, 0.0]
        # "weather", "rain", "temperature", "cloud" -> vector [0.0, 1.0, 0.0, 0.0]
        elif any(w in t for w in ["weather", "rain", "temperature", "forecast", "cloud"]):
            return [0.0, 1.0, 0.0, 0.0]
        # Default fallback vector
        return [0.0, 0.0, 1.0, 0.0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]


def test_chroma_vector_store_crud(tmp_path):
    chroma_dir = str(tmp_path / "chroma_test")
    embedder = MockConceptEmbeddingProvider()
    store = ChromaVectorStore(
        persist_dir=chroma_dir,
        collection_name="test_collection",
        embedding_provider=embedder,
    )

    # Insert concept memories
    ok1 = store.add_memory("mem_1", "I love software engineering and python development", {"topic": "dev"})
    ok2 = store.add_memory("mem_2", "The weather in Seattle is cloudy with heavy rain", {"topic": "weather"})
    assert ok1 is True
    assert ok2 is True

    # Semantic Query: Querying for "coding" should retrieve "software engineering" even without the keyword "coding"
    hits = store.query_similar(query_text="writing some coding scripts", top_k=2)
    assert len(hits) >= 1
    assert hits[0]["id"] == "mem_1"
    assert "software engineering" in hits[0]["content"]
    assert hits[0]["similarity"] > 0.9

    # Deletion test
    del_ok = store.delete_memory("mem_1")
    assert del_ok is True

    remaining = store.query_similar(query_text="writing some coding scripts", top_k=2)
    assert not any(h["id"] == "mem_1" for h in remaining)


def test_sqlite_background_vector_indexing_and_semantic_retrieval(tmp_path):
    db_file = str(tmp_path / "vector_memory.db")
    embedder = MockConceptEmbeddingProvider()
    mem = SQLiteConversationMemory(db_path=db_file, embedding_provider=embedder)

    # Add semantic node with programming concept
    node_id = mem.add_memory_node(
        content="Surendra enjoys building complex software architectures in Python",
        memory_type="semantic",
        importance=0.9,
    )
    assert node_id is not None

    # Allow background indexing thread a brief moment to complete
    time.sleep(0.3)

    # Query with semantic concept "coding" (word "coding" is not present in stored text)
    results = mem.search_bounded_memories(
        query="Tell me about coding preferences",
        memory_type="semantic",
        top_k=3,
    )

    assert len(results) >= 1
    matched = next((r for r in results if r["id"] == node_id), None)
    assert matched is not None
    assert "software architectures" in matched["content"]
    assert matched.get("retrieval_source") in ("vector", "fts5")

    mem.close()
