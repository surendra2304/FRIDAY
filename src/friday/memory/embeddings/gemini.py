"""Google Gemini Cloud Embedding Provider using the official google-genai SDK."""

import math
import re
import time
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from friday.core.exceptions import LLMProviderError
from friday.core.logging import get_logger
from friday.memory.embeddings.base import BaseEmbeddingProvider

logger = get_logger("memory.embeddings.gemini")

# Patterns for sensitive data that should never be sent unmasked to remote cloud embeddings
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+PRIVATE KEY-----"),
    re.compile(r"TEST_GEMINI_API_KEY_PLACEHOLDER_17[A-Za-z0-9_-]{33}"),
    re.compile(r"sk-[a-zA-Z0-9]{20,48}"),
    re.compile(r"(?:api[_-]?key|secret|password|bearer|auth|token)[\s:=\"']+([a-zA-Z0-9_\-\.]{16,})", re.IGNORECASE),
]


class GeminiEmbeddingProvider(BaseEmbeddingProvider):
    """Generates text embeddings remotely using Google Gemini API (gemini-embedding-2)."""
    
    _circuit_breaker_cooldown_until: float = 0.0

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        model: str = "gemini-embedding-2",
        dimension: int = 768,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        max_batch_size: int = 16,
    ):
        super().__init__(model=model, dimension=dimension)
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.max_batch_size = max(1, min(max_batch_size, 32))
        self._client: Optional[genai.Client] = None
        if self.api_key:
            try:
                self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Failed to initialize GenAI embedding client: {self._mask_key(str(e))}")

    @property
    def client(self) -> genai.Client:
        """Retrieve or create the cached GenAI Client instance."""
        if self._client is None:
            if not self.api_key:
                raise LLMProviderError("Gemini API key is required for semantic embeddings.")
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    @property
    def provider_name(self) -> str:
        return "gemini"

    def _mask_key(self, text: str) -> str:
        """Mask API key in any error or diagnostic string."""
        if self.api_key and self.api_key in text:
            return text.replace(self.api_key, "***")
        return text

    @staticmethod
    def sanitize_text_for_embedding(text: str) -> str:
        """Sanitize text before cloud transmission to prevent leaking secrets/keys."""
        if not text:
            return ""
        sanitized = text
        for pattern in SECRET_PATTERNS:
            sanitized = pattern.sub("[REDACTED_SECRET]", sanitized)
        return sanitized

    @staticmethod
    def normalize_vector(vec: List[float]) -> List[float]:
        """Normalize a float vector to unit length (L2 norm)."""
        if not vec:
            return []
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]

    def _get_model_path(self) -> str:
        model_name = self.model
        if not model_name.startswith("models/"):
            return f"models/{model_name}"
        return model_name

    def embed_text(self, text: str) -> List[float]:
        """Generate embedding for a single text chunk."""
        if time.time() < GeminiEmbeddingProvider._circuit_breaker_cooldown_until:
            raise LLMProviderError("Gemini embedding circuit breaker is open due to recent quota limits.")

        if not self.api_key:
            raise LLMProviderError("Gemini API key is required for semantic embeddings.")

        clean_text = self.sanitize_text_for_embedding(text)
        if not clean_text.strip():
            return [0.0] * self.dimension

        config = genai_types.EmbedContentConfig(
            output_dimensionality=self.dimension if self.dimension else None
        )

        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.models.embed_content(
                    model=self.model,
                    contents=clean_text,
                    config=config,
                )

                if response.embeddings:
                    values = getattr(response.embeddings[0], "values", None)
                    if values:
                        return self.normalize_vector(values)
                raise LLMProviderError("Empty embedding vector returned from Gemini API.")

            except genai_errors.APIError as e:
                err_msg = self._mask_key(str(e.message or e))
                code = getattr(e, "code", None) or getattr(e, "status_code", 500)
                status_str = f"status {code}: {err_msg}"
                if code == 429:
                    cooldown = 60.0
                    if hasattr(e, "response") and hasattr(e.response, "headers"):
                        retry_after = e.response.headers.get("retry-after") or e.response.headers.get("Retry-After")
                        if retry_after:
                            try:
                                cooldown = float(retry_after)
                            except ValueError:
                                pass
                    GeminiEmbeddingProvider._circuit_breaker_cooldown_until = time.time() + cooldown
                    logger.error(f"Gemini embedding quota exhausted (429). Opening circuit breaker for {cooldown}s.")
                    raise LLMProviderError(f"Gemini embedding rate-limited: {err_msg}")
                if code in (500, 502, 503, 504) and attempt < self.max_retries:
                    wait = 1.0 * (self.backoff_factor ** attempt)
                    logger.warning(f"Gemini embedding API error [{code}]: {err_msg}. Retrying in {wait:.2f}s...")
                    time.sleep(wait)
                    continue
                logger.error(f"Gemini embedding error after retries: {status_str}")
                raise LLMProviderError(f"Gemini embedding request failed ({status_str})") from e

            except LLMProviderError:
                raise

            except Exception as e:
                err_msg = self._mask_key(str(e))
                err_lower = err_msg.lower()
                if "429" in err_lower or "quota" in err_lower or "resource exhausted" in err_lower:
                    GeminiEmbeddingProvider._circuit_breaker_cooldown_until = time.time() + 60.0
                    logger.error(f"Gemini embedding quota exhausted. Opening circuit breaker for 60s.")
                    raise LLMProviderError(f"Gemini embedding rate-limited: {err_msg}")
                if attempt < self.max_retries:
                    wait = 1.0 * (self.backoff_factor ** attempt)
                    logger.warning(f"Gemini embedding API error: {err_msg}. Retrying in {wait:.2f}s...")
                    time.sleep(wait)
                    continue
                raise LLMProviderError(f"Gemini embedding error: {err_msg}") from e

        raise LLMProviderError("Failed to obtain embedding from Gemini API after retries.")

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts using bounded batch requests."""
        if time.time() < GeminiEmbeddingProvider._circuit_breaker_cooldown_until:
            raise LLMProviderError("Gemini embedding circuit breaker is open due to recent quota limits.")

        if not texts:
            return []

        if not self.api_key:
            raise LLMProviderError("Gemini API key is required for semantic embeddings.")

        all_vectors: List[List[float]] = []

        config = genai_types.EmbedContentConfig(
            output_dimensionality=self.dimension if self.dimension else None
        )

        for i in range(0, len(texts), self.max_batch_size):
            chunk = texts[i : i + self.max_batch_size]
            clean_chunk = [self.sanitize_text_for_embedding(t) or " " for t in chunk]

            chunk_success = False
            for attempt in range(self.max_retries + 1):
                try:
                    response = self.client.models.embed_content(
                        model=self.model,
                        contents=clean_chunk,
                        config=config,
                    )
                    if response.embeddings:
                        for emb in response.embeddings:
                            vals = getattr(emb, "values", None) or []
                            all_vectors.append(self.normalize_vector(vals) if vals else [0.0] * self.dimension)
                        chunk_success = True
                        break
                except Exception as e:
                    err_msg = str(e).lower()
                    if "429" in err_msg or "quota" in err_msg or "resource exhausted" in err_msg:
                        GeminiEmbeddingProvider._circuit_breaker_cooldown_until = time.time() + 60.0
                        logger.error("Gemini batch embedding quota exhausted. Opening circuit breaker.")
                        raise LLMProviderError("Gemini embedding rate-limited.")
                    if attempt < self.max_retries:
                        time.sleep(1.0 * (self.backoff_factor ** attempt))
                        continue
                    logger.warning(f"Batch embedding failed: {self._mask_key(str(e))}. Falling back to single embeds.")
                    break

            if not chunk_success:
                # Fallback to sequential embedding for this chunk
                for t in chunk:
                    try:
                        all_vectors.append(self.embed_text(t))
                    except Exception as e:
                        logger.warning(f"Individual fallback embedding failed: {self._mask_key(str(e))}")
                        all_vectors.append([0.0] * self.dimension)

        return all_vectors
