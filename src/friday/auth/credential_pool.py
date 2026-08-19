# -*- coding: utf-8 -*-
"""Friday Gemini Credential Pool

This module provides a thread-safe `GeminiCredentialPool` that manages a primary Gemini API key and up to four fallback keys.
It offers automatic failover, health monitoring, cooldown handling, and retry bookkeeping.

The implementation deliberately avoids logging or exposing raw API keys.
"""

import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Sequence


@dataclass
class Credential:
    """Container for a single Gemini API credential and its health state."""
    api_key: str
    is_primary: bool = False
    failure_count: int = 0
    last_failed_at: Optional[datetime] = None
    cooldown_until: Optional[datetime] = None

    def is_healthy(self, max_failures: int, cooldown_seconds: int) -> bool:
        """Return True if the credential can be used.

        A credential is considered unhealthy if it has exceeded ``max_failures`` or is within a cooldown period.
        """
        now = datetime.utcnow()
        if self.cooldown_until and now < self.cooldown_until:
            return False
        if self.failure_count >= max_failures:
            return False
        return True


class GeminiCredentialPool:
    """Thread-safe pool managing the primary and fallback Gemini API keys.

    The pool reads environment variables (or Settings) at initialization:

    - ``FRIDAY_GEMINI_API_KEY`` – primary credential
    - ``FRIDAY_GEMINI_FALLBACK_API_KEY_1`` … ``_4`` – optional fallbacks

    It provides ``get_active_key`` for callers and ``report_failure``/``reset_key`` for health tracking.
    """

    _instance_lock = threading.Lock()
    _instance: Optional["GeminiCredentialPool"] = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._instance_lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, max_failures: int = 1, cooldown_seconds: int = 60, keys: Optional[Sequence[str]] = None) -> None:
        if getattr(self, "_initialized", False) and keys is None:
            return
        self.lock = threading.Lock()
        self.max_failures = max_failures
        self.cooldown_seconds = cooldown_seconds
        self.credentials: List[Credential] = []
        if keys is not None:
            self.load_keys(keys)
        else:
            self._load_credentials()
        self._initialized = True

    def load_keys(self, keys: Sequence[str]) -> None:
        """Load explicit keys into the pool."""
        with self.lock:
            self.credentials = []
            for i, key in enumerate(keys):
                if key and str(key).strip():
                    self.credentials.append(Credential(api_key=str(key).strip(), is_primary=(i == 0)))

    def _load_credentials(self) -> None:
        primary = os.getenv("FRIDAY_GEMINI_API_KEY")
        fallbacks = [
            os.getenv(f"FRIDAY_GEMINI_FALLBACK_API_KEY_{i}") for i in range(1, 5)
        ]
        self.credentials = []
        if primary and primary.strip():
            self.credentials.append(Credential(api_key=primary.strip(), is_primary=True))
        for key in fallbacks:
            if key and key.strip():
                self.credentials.append(Credential(api_key=key.strip(), is_primary=False))

    def reload(self) -> None:
        """Reload credentials from current environment variables."""
        with self.lock:
            self._load_credentials()

    def get_active_key(self) -> str:
        """Return the first healthy credential's API key.

        Preference order: primary first, then fallbacks in the order they were loaded.
        Raises ``RuntimeError`` if no healthy credential is available.
        """
        with self.lock:
            for cred in self.credentials:
                if cred.is_healthy(self.max_failures, self.cooldown_seconds):
                    return cred.api_key
            raise RuntimeError("No healthy Gemini API key available for request")

    def report_failure(self, key: str) -> None:
        """Record a failure for the credential identified by ``key``.

        Increments ``failure_count`` and puts the credential into a cooldown period.
        """
        with self.lock:
            cred = self._find_by_key(key)
            if not cred:
                return
            cred.failure_count += 1
            cred.last_failed_at = datetime.utcnow()
            cred.cooldown_until = datetime.utcnow() + timedelta(seconds=self.cooldown_seconds)

    def reset_key(self, key: str) -> None:
        """Reset the health state of a credential after a successful request."""
        with self.lock:
            cred = self._find_by_key(key)
            if not cred:
                return
            cred.failure_count = 0
            cred.last_failed_at = None
            cred.cooldown_until = None

    def reset_all(self) -> None:
        """Reset the health state of all credentials in the pool."""
        with self.lock:
            for cred in self.credentials:
                cred.failure_count = 0
                cred.last_failed_at = None
                cred.cooldown_until = None

    def _find_by_key(self, key: str) -> Optional[Credential]:
        for cred in self.credentials:
            if cred.api_key == key:
                return cred
        return None


# Export a module‑level singleton for convenient import
credential_pool = GeminiCredentialPool()

__all__ = ["Credential", "GeminiCredentialPool", "credential_pool"]

