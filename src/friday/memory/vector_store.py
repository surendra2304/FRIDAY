"""ChromaDB local-first vector store for Full-Duplex Voice Engine2 Semantic Vector Memory."""

import os
import threading
import time
from typing import Any

from friday.core.logging import get_logger
from friday.memory.embeddings.base import BaseEmbeddingProvider

logger = get_logger("memory.vector_store")


class ChromaVectorStore:
    """Lightweight, local-first vector database using ChromaDB with Gemini embedding support."""

    def __init__(
        self,
        persist_dir: str = "data/chroma",
        collection_name: str = "friday_memories",
        embedding_provider: BaseEmbeddingProvider | None = None,
        cache_ttl_seconds: float = 60.0,
    ) -> None:
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self.embedding_provider = embedding_provider
        self.cache_ttl_seconds = cache_ttl_seconds
        self._lock = threading.RLock()
        self._client = None
        self._collection = None
        # In-memory query cache: key -> (timestamp, results)
        self._query_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    def _ensure_initialized(self) -> None:
        """Lazily initialize ChromaDB client and collection on first use."""
        if self._collection is not None:
            return
        with self._lock:
            if self._collection is not None:
                return
            os.makedirs(self.persist_dir, exist_ok=True)
            try:
                import chromadb
                from chromadb.config import Settings as ChromaSettings

                self._client = chromadb.PersistentClient(
                    path=self.persist_dir,
                    settings=ChromaSettings(anonymized_telemetry=False, is_persistent=True),
                )
                self._collection = self._client.get_or_create_collection(
                    name=self.collection_name,
                    metadata={"hnsw:space": "cosine"},
                )
                logger.info(f"Initialized ChromaVectorStore at '{self.persist_dir}' with collection '{self.collection_name}'")
            except Exception as e:
                logger.error(f"Failed to initialize ChromaDB PersistentClient: {e}")
                raise

    def add_memory(
        self,
        memory_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
    ) -> bool:
        """Embed text and insert or update vector record in ChromaDB."""
        if not text or not text.strip():
            return False

        self._ensure_initialized()
        clean_text = text.strip()
        vec = embedding
        if vec is None and self.embedding_provider is not None:
            try:
                vec = self.embedding_provider.embed_text(clean_text)
            except Exception as e:
                logger.warning(f"Failed to generate embedding for memory '{memory_id}': {e}")
                return False

        if vec is None:
            logger.debug("No embedding vector or provider available for ChromaVectorStore.add_memory")
            return False

        meta = metadata or {}
        # Ensure metadata values are supported by Chroma (str, int, float, bool)
        sanitized_meta = {
            k: (str(v) if not isinstance(v, (str, int, float, bool)) else v)
            for k, v in meta.items()
        }

        with self._lock:
            try:
                self._collection.upsert(
                    ids=[memory_id],
                    embeddings=[vec],
                    documents=[clean_text],
                    metadatas=[sanitized_meta],
                )
                # Invalidate query cache upon new insertions
                self._query_cache.clear()
                logger.debug(f"Upserted memory '{memory_id}' into Chroma collection '{self.collection_name}'")
                return True
            except Exception as e:
                logger.warning(f"Error upserting memory '{memory_id}' into ChromaDB: {e}")
                return False

    def query_similar(
        self,
        query_text: str,
        top_k: int = 5,
        min_similarity: float = 0.0,
        where_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Query ChromaDB for semantically similar memories with 60-second caching."""
        if not query_text or not query_text.strip():
            return []

        clean_query = query_text.strip().lower()
        cache_key = f"{clean_query}:{top_k}:{min_similarity}:{where_filter!s}"
        now = time.time()

        # Check 60-second cache
        with self._lock:
            if cache_key in self._query_cache:
                cached_time, cached_res = self._query_cache[cache_key]
                if (now - cached_time) < self.cache_ttl_seconds:
                    logger.debug(f"Vector search cache hit for '{clean_query[:30]}'")
                    return cached_res

        self._ensure_initialized()
        if self.embedding_provider is None:
            logger.debug("No embedding provider configured for ChromaVectorStore query")
            return []

        try:
            query_vec = self.embedding_provider.embed_text(query_text.strip())
        except Exception as e:
            logger.warning(f"Failed to embed query for semantic vector search: {e}")
            return []

        with self._lock:
            try:
                kwargs: dict[str, Any] = {
                    "query_embeddings": [query_vec],
                    "n_results": max(1, top_k),
                }
                if where_filter:
                    kwargs["where"] = where_filter

                res = self._collection.query(**kwargs)
            except Exception as e:
                logger.warning(f"ChromaDB semantic query failed: {e}")
                return []

        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        distances = res.get("distances", [[]])[0]

        results = []
        for i, mid in enumerate(ids):
            dist = distances[i] if i < len(distances) else 1.0
            # For cosine distance in Chroma: similarity = 1.0 - distance
            similarity = max(0.0, min(1.0, 1.0 - dist))
            if similarity < min_similarity:
                continue

            results.append({
                "id": mid,
                "content": docs[i] if i < len(docs) else "",
                "metadata": metas[i] if i < len(metas) else {},
                "similarity": similarity,
            })

        # Save to cache
        with self._lock:
            self._query_cache[cache_key] = (now, results)

        return results

    def delete_memory(self, memory_id: str) -> bool:
        """Remove a memory record by ID from ChromaDB."""
        self._ensure_initialized()
        with self._lock:
            try:
                self._collection.delete(ids=[memory_id])
                self._query_cache.clear()
                logger.debug(f"Deleted memory '{memory_id}' from ChromaDB")
                return True
            except Exception as e:
                logger.warning(f"Could not delete memory '{memory_id}' from ChromaDB: {e}")
                return False

    def clear(self) -> None:
        """Clear all entries in collection."""
        self._ensure_initialized()
        with self._lock:
            try:
                self._client.delete_collection(self.collection_name)
                self._collection = self._client.get_or_create_collection(
                    name=self.collection_name,
                    metadata={"hnsw:space": "cosine"},
                )
                self._query_cache.clear()
            except Exception as e:
                logger.warning(f"Error clearing ChromaVectorStore collection: {e}")
