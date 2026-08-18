"""Google Gemini Cloud Embedding Provider using HTTPX."""

import time
from typing import List, Optional
import httpx
from friday.core.exceptions import LLMProviderError
from friday.core.logging import get_logger
from friday.memory.embeddings.base import BaseEmbeddingProvider

logger = get_logger("memory.embeddings.gemini")


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
    ):
        super().__init__(model=model, dimension=dimension)
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    @property
    def provider_name(self) -> str:
        return "gemini"

    def embed_text(self, text: str) -> List[float]:
        """Generate embedding for a single text chunk."""
        if not self.api_key:
            raise LLMProviderError("Gemini API key is required for semantic embeddings.")

        if not text.strip():
            return [0.0] * self.dimension

        model_name = self.model
        if not model_name.startswith("models/"):
            model_path = f"models/{model_name}"
        else:
            model_path = model_name

        url = f"{self.base_url}/{model_path}:embedContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }
        payload = {
            "model": model_path,
            "content": {
                "parts": [{"text": text}],
            },
        }

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
                    time.sleep(wait_time)
                    continue

                raise LLMProviderError(f"Gemini embedding request failed [{response.status_code}]: {error_detail}")

            except httpx.RequestError as e:
                err_msg = str(e)
                if self.api_key and self.api_key in err_msg:
                    err_msg = err_msg.replace(self.api_key, "***")
                if attempt < self.max_retries:
                    wait_time = initial_delay * (self.backoff_factor ** attempt)
                    time.sleep(wait_time)
                    continue
                raise LLMProviderError(f"Network error during Gemini embedding request: {err_msg}") from e

        if data is None:
            raise LLMProviderError("Failed to obtain embedding from Gemini API after retries.")

        values = data.get("embedding", {}).get("values", [])
        if not values:
            raise LLMProviderError("Empty embedding vector returned from Gemini API.")

        return values

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        return [self.embed_text(t) for t in texts]
