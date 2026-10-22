"""FORGE Authentication & Secure REST Client for FRIDAY.

Provides cryptographic request signing (HMAC-SHA256), token-bucket rate limiting
(10 req/min), schema validation, and timeout management for FORGE communications.
"""

import hashlib
import hmac
import json
import threading
import time
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("integrations.forge_auth")


class ForgeRateLimitExceeded(Exception):
    """Raised when FORGE API rate limit (10 req/min) is exceeded."""


class ForgeAuthClient:
    """Secure client handling HMAC-SHA256 signing, token bucket rate limits, and schema validation."""

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        api_key: str | None = None,
        rate_limit_per_min: int = 10,
        default_timeout_sec: float = 30.0,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key or "default_friday_forge_secret_key"
        self.rate_limit_per_min = rate_limit_per_min
        self.default_timeout_sec = default_timeout_sec

        # Token bucket rate limiting
        self._tokens = float(rate_limit_per_min)
        self._capacity = float(rate_limit_per_min)
        self._last_refill = time.time()
        self._lock = threading.RLock()

    def _refill_tokens(self) -> None:
        """Refills rate limiter tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self._last_refill
        # Refill tokens proportional to elapsed minutes
        new_tokens = elapsed * (self.rate_limit_per_min / 60.0)
        self._tokens = min(self._capacity, self._tokens + new_tokens)
        self._last_refill = now

    def acquire_rate_limit(self) -> bool:
        """Consumes a single rate-limit token, returning False if exhausted."""
        with self._lock:
            self._refill_tokens()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    def generate_signed_headers(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Generates HMAC-SHA256 signature headers for request integrity and authentication."""
        timestamp = datetime.now(timezone.utc).isoformat()
        body_str = json.dumps(payload, sort_keys=True) if payload else ""
        canonical_string = f"{timestamp}\n{method.upper()}\n{path}\n{body_str}"

        signature = hmac.new(
            self.api_key.encode("utf-8"),
            canonical_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return {
            "Content-Type": "application/json",
            "X-FRIDAY-Client-Id": "FRIDAY-OS-v2.0",
            "X-FRIDAY-Timestamp": timestamp,
            "X-FRIDAY-Signature": signature,
            "Authorization": f"Bearer {self.api_key}",
        }

    def validate_build_response(self, response_data: dict[str, Any]) -> bool:
        """Validates schema for task creation (/api/v1/forge/build)."""
        required_fields = ["task_id", "status"]
        for field in required_fields:
            if field not in response_data:
                logger.warning(f"[FORGE_AUTH] Build response missing required field: {field}")
                return False
        return True

    def validate_task_status_response(self, response_data: dict[str, Any]) -> bool:
        """Validates schema for task status (/api/v1/forge/tasks/{id})."""
        required_fields = ["task_id", "status", "progress_pct", "artifacts"]
        for field in required_fields:
            if field not in response_data:
                logger.warning(f"[FORGE_AUTH] Task status response missing required field: {field}")
                return False
        return True
