# -*- coding: utf-8 -*-
"""Friday Gemini Credential Pool

This module provides a thread-safe `GeminiCredentialPool` that manages a primary Gemini API key and up to four fallback keys.
It offers automatic failover, health monitoring, persistent health state, cooldown handling, and retry bookkeeping.

The implementation deliberately avoids logging or exposing raw API keys.
"""

import enum
import json
import os
from pathlib import Path
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence


class FailureCategory(str, enum.Enum):
    """Categorized failure types for quota, network, auth, and model errors."""
    HEALTHY = "healthy"
    RATE_LIMIT = "rate_limit_exceeded"
    QUOTA_EXHAUSTED = "quota_exceeded"
    AUTH_FAILED = "authentication_failed"
    MODEL_NOT_FOUND = "model_not_found"
    SERVICE_ERROR = "service_error"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown_error"


# Cooldown durations per failure category
COOLDOWN_DURATIONS: Dict[FailureCategory, float] = {
    FailureCategory.RATE_LIMIT: 30.0,         # Short rate-limit cooldown
    FailureCategory.QUOTA_EXHAUSTED: 3600.0,   # Quota exhausted: 1 hour (or until daily reset)
    FailureCategory.AUTH_FAILED: 86400.0,      # Invalid key: 24h cooldown
    FailureCategory.MODEL_NOT_FOUND: 3600.0,   # Bad model: 1 hour
    FailureCategory.SERVICE_ERROR: 60.0,       # 500/503: 1 min
    FailureCategory.NETWORK_ERROR: 30.0,       # Timeout/network: 30s
    FailureCategory.UNKNOWN: 60.0,
}


@dataclass
class Credential:
    """Container for a single Gemini API credential and its health state."""
    api_key: str
    project_label: str = "PRIMARY"
    is_primary: bool = False
    failure_count: int = 0
    last_failed_at: Optional[datetime] = None
    cooldown_until: Optional[datetime] = None
    last_failure_category: FailureCategory = FailureCategory.HEALTHY
    last_success_at: Optional[datetime] = None

    def is_healthy(self, max_failures: int, default_cooldown: int = 60) -> bool:
        """Return True if the credential can be used."""
        now = datetime.utcnow()
        if self.cooldown_until and now < self.cooldown_until:
            return False
        if self.failure_count >= max_failures:
            # If cooldown expired, allow retry
            if self.cooldown_until and now >= self.cooldown_until:
                return True
            return False
        return True

    def to_safe_dict(self) -> Dict[str, Any]:
        """Return safe state dictionary containing no secret keys."""
        now = datetime.utcnow()
        is_in_cooldown = bool(self.cooldown_until and now < self.cooldown_until)
        return {
            "project_label": self.project_label,
            "is_primary": self.is_primary,
            "is_healthy": not is_in_cooldown and (self.failure_count == 0 or (self.cooldown_until and now >= self.cooldown_until)),
            "status": "COOLDOWN" if is_in_cooldown else ("HEALTHY" if self.failure_count == 0 else "DEGRADED"),
            "failure_category": self.last_failure_category.value,
            "failure_count": self.failure_count,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
            "last_failed_at": self.last_failed_at.isoformat() if self.last_failed_at else None,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
        }


class GeminiCredentialPool:
    """Thread-safe pool managing primary and fallback Gemini API keys.
    
    Persists health across restarts and tracks session-level active key.
    """

    _instance_lock = threading.Lock()
    _instance: Optional["GeminiCredentialPool"] = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._instance_lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        max_failures: int = 1,
        cooldown_seconds: int = 60,
        keys: Optional[Sequence[str]] = None,
        state_file: Optional[Path] = None,
    ) -> None:
        if getattr(self, "_initialized", False) and keys is None:
            return
        self.lock = threading.Lock()
        self.max_failures = max_failures
        self.cooldown_seconds = cooldown_seconds
        self.state_file = state_file or Path("data/gemini_pool_state.json")
        self.credentials: List[Credential] = []
        self._session_active_key: Optional[str] = None
        self._preflight_done: bool = False

        if keys is not None:
            self.load_keys(keys)
        else:
            self._load_credentials()
            self._load_persisted_state()
        self._initialized = True

    def load_keys(self, keys: Sequence[str]) -> None:
        """Load explicit keys into the pool."""
        with self.lock:
            self.credentials = []
            labels = ["PRIMARY"] + [f"FALLBACK {i}" for i in range(1, 5)]
            for i, key in enumerate(keys):
                if key and str(key).strip():
                    label = labels[i] if i < len(labels) else f"CRED_{i}"
                    self.credentials.append(
                        Credential(api_key=str(key).strip(), project_label=label, is_primary=(i == 0))
                    )
            self._session_active_key = None

    def _load_credentials(self) -> None:
        primary = os.getenv("FRIDAY_GEMINI_API_KEY")
        fallbacks = [
            os.getenv(f"FRIDAY_GEMINI_FALLBACK_API_KEY_{i}") for i in range(1, 5)
        ]
        if not primary and not any(fallbacks):
            try:
                from dotenv import dotenv_values
                from friday.core.config import resolve_env_file
                env_p = resolve_env_file()
                if env_p and env_p.is_file():
                    vals = dotenv_values(dotenv_path=env_p)
                    primary = vals.get("FRIDAY_GEMINI_API_KEY") or vals.get("GEMINI_API_KEY")
                    fallbacks = [
                        vals.get(f"FRIDAY_GEMINI_FALLBACK_API_KEY_{i}") or vals.get(f"GEMINI_FALLBACK_API_KEY_{i}")
                        for i in range(1, 5)
                    ]
            except Exception:
                pass

        self.credentials = []
        if primary and primary.strip():
            self.credentials.append(
                Credential(api_key=primary.strip(), project_label="PRIMARY", is_primary=True)
            )
        for i, key in enumerate(fallbacks, 1):
            if key and key.strip():
                self.credentials.append(
                    Credential(api_key=key.strip(), project_label=f"FALLBACK {i}", is_primary=False)
                )

    def _load_persisted_state(self) -> None:
        """Load persistent health metadata (without keys) from disk."""
        if not self.state_file or not self.state_file.is_file():
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            now = datetime.utcnow()
            for label, meta in data.items():
                cred = self._find_by_label(label)
                if cred:
                    if meta.get("cooldown_until"):
                        try:
                            cooldown = datetime.fromisoformat(meta["cooldown_until"])
                            if cooldown > now:
                                cred.cooldown_until = cooldown
                                cred.failure_count = meta.get("failure_count", 1)
                                cat_str = meta.get("failure_category", "unknown_error")
                                try:
                                    cred.last_failure_category = FailureCategory(cat_str)
                                except Exception:
                                    pass
                        except Exception:
                            pass
        except Exception:
            pass

    def _save_persisted_state(self) -> None:
        """Save non-sensitive health metadata to disk."""
        if not self.state_file:
            return
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            for cred in self.credentials:
                data[cred.project_label] = cred.to_safe_dict()
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def reload(self) -> None:
        """Reload credentials from current environment variables."""
        with self.lock:
            self._load_credentials()
            self._load_persisted_state()

    def get_active_key(self) -> str:
        """Return the active healthy credential's API key.
        
        Preserves session-level stickiness if the current session key is still healthy.
        """
        with self.lock:
            # 1. If primary is healthy, always prioritize primary
            if self.credentials and self.credentials[0].is_healthy(self.max_failures, self.cooldown_seconds):
                self._session_active_key = self.credentials[0].api_key
                return self.credentials[0].api_key

            # 2. If we have a session active fallback key and it's healthy, stay on it
            if self._session_active_key:
                current_cred = self._find_by_key(self._session_active_key)
                if current_cred and current_cred.is_healthy(self.max_failures, self.cooldown_seconds):
                    return current_cred.api_key

            # 3. Find the first healthy credential in priority order
            for cred in self.credentials:
                if cred.is_healthy(self.max_failures, self.cooldown_seconds):
                    self._session_active_key = cred.api_key
                    return cred.api_key

            raise RuntimeError("No healthy Gemini API key available for request")

    def get_active_label(self) -> str:
        """Return the safe project label for the active key."""
        try:
            key = self.get_active_key()
            with self.lock:
                cred = self._find_by_key(key)
                return cred.project_label if cred else "UNKNOWN"
        except Exception:
            return "NONE AVAILABLE"

    def preflight_check(self, model: str = "gemini-3.6-flash", force_probe: bool = False) -> Dict[str, Any]:
        """Perform a one-time quota-conscious startup preflight check.
        
        Checks persisted health first. Only performs a live probe if no healthy
        credential has known status.
        """
        with self.lock:
            if self._preflight_done and not force_probe:
                active_lbl = self.get_active_label()
                return {
                    "status": "cached",
                    "active_project": active_lbl,
                    "pool_size": len(self.credentials),
                }

            # If primary is known healthy, select it without burning a probe
            primary = self._find_by_label("PRIMARY")
            if primary and primary.is_healthy(self.max_failures, self.cooldown_seconds):
                self._session_active_key = primary.api_key
                self._preflight_done = True
                return {
                    "status": "ready",
                    "active_project": "PRIMARY",
                    "pool_size": len(self.credentials),
                }

            # If primary is in cooldown, find first healthy fallback
            for cred in self.credentials:
                if cred.is_healthy(self.max_failures, self.cooldown_seconds):
                    self._session_active_key = cred.api_key
                    self._preflight_done = True
                    return {
                        "status": "fallback_selected",
                        "active_project": cred.project_label,
                        "pool_size": len(self.credentials),
                    }

            self._preflight_done = True
            return {
                "status": "exhausted",
                "active_project": "NONE",
                "pool_size": len(self.credentials),
            }

    @staticmethod
    def classify_error(error: Exception) -> FailureCategory:
        """Classify an exception into a FailureCategory for intelligent cooldown."""
        err_str = str(error).lower()
        if "401" in err_str or "api_key_invalid" in err_str or "invalid api key" in err_str or "api key not valid" in err_str:
            return FailureCategory.AUTH_FAILED
        if "404" in err_str or "not_found" in err_str or ("model" in err_str and "no longer available" in err_str):
            return FailureCategory.MODEL_NOT_FOUND
        if "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str:
            if (
                "daily" in err_str
                or "quota exceeded" in err_str
                or "generate_content_free_tier" in err_str
                or "limit:" in err_str
                or "resource_exhausted" in err_str
                or "free_tier" in err_str
            ):
                return FailureCategory.QUOTA_EXHAUSTED
            return FailureCategory.RATE_LIMIT
        if "500" in err_str or "503" in err_str or "504" in err_str or "unavailable" in err_str:
            return FailureCategory.SERVICE_ERROR
        if "connect" in err_str or "timeout" in err_str or "network" in err_str or "connection reset" in err_str:
            return FailureCategory.NETWORK_ERROR
        return FailureCategory.UNKNOWN

    def report_failure(self, key: str, error: Optional[Exception] = None) -> None:
        """Record a failure for the credential, applying category-specific cooldown."""
        with self.lock:
            cred = self._find_by_key(key)
            if not cred:
                return
            category = self.classify_error(error) if error else FailureCategory.RATE_LIMIT
            cooldown_dur = COOLDOWN_DURATIONS.get(category, float(self.cooldown_seconds))

            # If Google API provided a specific retry delay in the error response, parse and respect it
            if error:
                err_str = str(error)
                import re
                m = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", err_str, re.IGNORECASE)
                if not m:
                    m = re.search(r"['\"]retryDelay['\"]:\s*['\"]([0-9]+)s['\"]", err_str, re.IGNORECASE)
                if m:
                    try:
                        extracted_delay = float(m.group(1))
                        if extracted_delay > 0:
                            # Add a small 2-second buffer
                            cooldown_dur = max(cooldown_dur if category != FailureCategory.QUOTA_EXHAUSTED else 0.0, extracted_delay + 2.0)
                    except Exception:
                        pass

            cred.failure_count += 1
            cred.last_failed_at = datetime.utcnow()
            cred.last_failure_category = category
            cred.cooldown_until = datetime.utcnow() + timedelta(seconds=cooldown_dur)

            # Clear session active key if it was the one that failed
            if self._session_active_key == key:
                self._session_active_key = None

            self._save_persisted_state()

    def reset_key(self, key: str) -> None:
        """Reset the health state of a credential after a successful request."""
        with self.lock:
            cred = self._find_by_key(key)
            if not cred:
                return
            cred.failure_count = 0
            cred.last_failed_at = None
            cred.cooldown_until = None
            cred.last_failure_category = FailureCategory.HEALTHY
            cred.last_success_at = datetime.utcnow()
            self._save_persisted_state()

    def reset_all(self) -> None:
        """Reset the health state of all credentials in the pool."""
        with self.lock:
            for cred in self.credentials:
                cred.failure_count = 0
                cred.last_failed_at = None
                cred.cooldown_until = None
                cred.last_failure_category = FailureCategory.HEALTHY
            self._session_active_key = None
            self._save_persisted_state()

    def get_diagnostics(self) -> List[Dict[str, Any]]:
        """Return non-sensitive status report for all credentials in pool."""
        with self.lock:
            return [cred.to_safe_dict() for cred in self.credentials]

    def _find_by_key(self, key: str) -> Optional[Credential]:
        for cred in self.credentials:
            if cred.api_key == key:
                return cred
        return None

    def _find_by_label(self, label: str) -> Optional[Credential]:
        for cred in self.credentials:
            if cred.project_label.upper() == label.upper():
                return cred
        return None


# Export a module-level singleton for convenient import
credential_pool = GeminiCredentialPool()

__all__ = ["Credential", "FailureCategory", "GeminiCredentialPool", "credential_pool", "COOLDOWN_DURATIONS"]


