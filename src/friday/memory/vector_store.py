# -*- coding: utf-8 -*-
"""ChromaDB local-first vector store for Phase 22 Semantic Vector Memory."""

import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from friday.core.logging import get_logger
from friday.memory.embeddings.base import BaseEmbeddingProvider

logger = get_logger("memory.vector_store")


class ChromaVectorStore:
    """Lightweight, local-first vector database using ChromaDB with Gemini embedding support."""

    def __init__(
        self,
        persist_dir: str = "data/chroma",
        collection_name: str = "friday_memories",
        embedding_provider: Optional[BaseEmbeddingProvider] = None,
    ) -> None:
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self.embedding_provider = embedding_provider
        self._lock = threading.RLock()

        os.makedirs(self.persist_dir, exist_ok=True)
        try:
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
        metadata: Optional[Dict[str, Any]] = None,
        embedding: Optional[List[float]] = None,
    ) -> bool:
        """Embed text and insert or update vector record in ChromaDB."""
        if not text or not text.strip():
            return False

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
        where_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Query ChromaDB for semantically similar memories by text embedding."""
        if not query_text or not query_text.strip():
            return []

        if self.embedding_provider is None:
            logger.debug("No embedding provider configured for ChromaVectorStore query")
            return []

        clean_query = query_text.strip()
        try:
            query_vec = self.embedding_provider.embed_text(clean_query)
        except Exception as e:
            logger.warning(f"Failed to embed query for semantic vector search: {e}")
            return []

        with self._lock:
            try:
                kwargs: Dict[str, Any] = {
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

        return results

    def delete_memory(self, memory_id: str) -> bool:
        """Remove a memory record by ID from ChromaDB."""
        with self._lock:
            try:
                self._collection.delete(ids=[memory_id])
                logger.debug(f"Deleted memory '{memory_id}' from ChromaDB")
                return True
            except Exception as e:
                logger.warning(f"Could not delete memory '{memory_id}' from ChromaDB: {e}")
                return False

    def clear(self) -> None:
        """Clear all entries in collection."""
        with self._lock:
            try:
                self._client.delete_collection(self.collection_name)
                self._collection = self._client.get_or_create_collection(
                    name=self.collection_name,
                    metadata={"hnsw:space": "cosine"},
                )
            except Exception as e:
                logger.warning(f"Error clearing ChromaVectorStore collection: {e}")
