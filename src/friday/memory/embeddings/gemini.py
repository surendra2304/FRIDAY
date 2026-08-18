"""Google Gemini Cloud Embedding Provider using HTTPX."""

import math
import re
import time
from typing import Any, Dict, List, Optional
import httpx
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
    """Generates text embeddings remotely using Google Gemini API (models/text-embedding-004)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        model: str = "text-embedding-004",
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

    @property
    def provider_name(self) -> str:
        return "gemini"

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
        if not self.api_key:
            raise LLMProviderError("Gemini API key is required for semantic embeddings.")

        clean_text = self.sanitize_text_for_embedding(text)
        if not clean_text.strip():
            return [0.0] * self.dimension

        model_path = self._get_model_path()
        url = f"{self.base_url}/{model_path}:embedContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }
        payload: Dict[str, Any] = {
            "model": model_path,
            "content": {
                "parts": [{"text": clean_text}],
            },
        }
        if self.dimension:
            payload["outputDimensionality"] = self.dimension

        initial_delay = 1.0
        data = None

        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(url, headers=headers, json=payload)

                if response.status_code == 200:
                    data = response.json()
                    break

                error_detail = response.text
                try:
                    err_json = response.json()
                    error_detail = err_json.get("error", {}).get("message") or response.text
                except Exception:
                    pass

                if self.api_key and self.api_key in error_detail:
                    error_detail = error_detail.replace(self.api_key, "***")

                if response.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    wait_time = initial_delay * (self.backoff_factor ** attempt)
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            wait_time = float(retry_after)
                        except (ValueError, TypeError):
                            pass
                    logger.warning(
                        f"Gemini embedding rate-limited/failed [{response.status_code}]. "
                        f"Retrying in {wait_time:.2f}s (Attempt {attempt+1}/{self.max_retries+1})"
                    )
                    time.sleep(wait_time)
                    continue

                raise LLMProviderError(f"Gemini embedding request failed [{response.status_code}]: {error_detail}")

            except httpx.RequestError as e:
                err_msg = str(e)
                if self.api_key and self.api_key in err_msg:
                    err_msg = err_msg.replace(self.api_key, "***")
                if attempt < self.max_retries:
                    wait_time = initial_delay * (self.backoff_factor ** attempt)
                    logger.warning(f"Network error in Gemini embedding: {err_msg}. Retrying in {wait_time:.2f}s...")
                    time.sleep(wait_time)
                    continue
                raise LLMProviderError(f"Network error during Gemini embedding request: {err_msg}") from e

        if data is None:
            raise LLMProviderError("Failed to obtain embedding from Gemini API after retries.")

        values = data.get("embedding", {}).get("values", [])
        if not values:
            raise LLMProviderError("Empty embedding vector returned from Gemini API.")

        return self.normalize_vector(values)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts using bounded batch requests."""
        if not texts:
            return []

        if not self.api_key:
            raise LLMProviderError("Gemini API key is required for semantic embeddings.")

        model_path = self._get_model_path()
        url = f"{self.base_url}/{model_path}:batchEmbedContents"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        all_vectors: List[List[float]] = []

        # Process in safe, bounded chunks
        for i in range(0, len(texts), self.max_batch_size):
            chunk = texts[i : i + self.max_batch_size]
            requests_payload = []
            for t in chunk:
                clean_t = self.sanitize_text_for_embedding(t)
                req_obj: Dict[str, Any] = {
                    "model": model_path,
                    "content": {"parts": [{"text": clean_t if clean_t.strip() else " "}]},
                }
                if self.dimension:
                    req_obj["outputDimensionality"] = self.dimension
                requests_payload.append(req_obj)

            payload = {"requests": requests_payload}
            chunk_data = None
            initial_delay = 1.0

            for attempt in range(self.max_retries + 1):
                try:
                    with httpx.Client(timeout=self.timeout) as client:
                        response = client.post(url, headers=headers, json=payload)

                    if response.status_code == 200:
                        chunk_data = response.json()
                        break

                    error_detail = response.text
                    try:
                        err_json = response.json()
                        error_detail = err_json.get("error", {}).get("message") or response.text
                    except Exception:
                        pass

                    if self.api_key and self.api_key in error_detail:
                        error_detail = error_detail.replace(self.api_key, "***")

                    if response.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                        wait_time = initial_delay * (self.backoff_factor ** attempt)
                        time.sleep(wait_time)
                        continue

                    # If batch endpoint returns 404 or unsupported status, fall back to sequential single embed
                    logger.warning(
                        f"Batch embedding request failed with status {response.status_code}: {error_detail}. "
                        "Falling back to individual embedding calls for this chunk."
                    )
                    break

                except httpx.RequestError as e:
                    if attempt < self.max_retries:
                        time.sleep(initial_delay * (self.backoff_factor ** attempt))
                        continue
                    logger.warning(f"Batch embedding network error: {e}. Falling back to single embeds.")
                    break

            if chunk_data and "embeddings" in chunk_data:
                for item in chunk_data["embeddings"]:
                    vals = item.get("values", [])
                    all_vectors.append(self.normalize_vector(vals) if vals else [0.0] * self.dimension)
            else:
                # Sequential fallback for this chunk
                for t in chunk:
                    try:
                        all_vectors.append(self.embed_text(t))
                    except Exception as e:
                        logger.warning(f"Individual fallback embedding failed: {e}")
                        all_vectors.append([0.0] * self.dimension)

        return all_vectors
