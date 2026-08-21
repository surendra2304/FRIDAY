# -*- coding: utf-8 -*-
"""Global unified repository-wide Secret Scrubber.

Identifies, redacts, and masks all configured credentials, system credentials,
and common secret patterns (Google/Gemini keys, OpenAI keys, JWTs, cloud keys,
database connection strings, cookies, private keys) before logging, storage,
exception creation, or serialization.
"""

import os
import re
import sys
import threading
from typing import Any, Dict, List, Optional, Set


# Comprehensive regex patterns for common credential formats
SECRET_REGEX_PATTERNS = [
    # Google API / Gemini keys
    re.compile(r"\bAIza[A-Za-z0-9_-]{18,40}\b"),
    # OpenAI API keys (including sk-proj-, sk-org-, etc.)
    re.compile(r"\bsk-[a-zA-Z0-9_-]{20,}\b"),
    # Bearer tokens
    re.compile(r"\bBearer\s+[a-zA-Z0-9_\-\.]{20,}\b", re.IGNORECASE),
    # JSON Web Tokens (JWT)
    re.compile(r"\bey[A-Za-z0-9_-]{10,}\.ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    # AWS Access Key ID
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # AWS Secret Access Key
    re.compile(r"aws_(?:secret_)?access_key\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?", re.IGNORECASE),
    # PEM Private Keys
    re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[A-Za-z0-9+/=\s\n]+-----END [A-Z ]+ PRIVATE KEY-----"),
    # Database connection strings with inline credentials (e.g. postgresql://user:pass@host/db)
    re.compile(r"\b[a-zA-Z0-9]+://[^:\s]+:[^@\s]+@[^\s]+\b"),
    # HTTP Authorization / Proxy-Authorization headers
    re.compile(r"(Authorization|Proxy-Authorization|Auth)\s*[:=]\s*['\"]?([A-Za-z0-9\-_=\.\s\[\]]+)['\"]?", re.IGNORECASE),
    # HTTP Cookie headers
    re.compile(r"(Cookie)\s*[:=]\s*['\"]?([A-Za-z0-9\-_=\.\s;\[\]]+)['\"]?", re.IGNORECASE),
    # Key-value secret/password patterns (e.g. password=my_pass)
    re.compile(r"(password|passwd|pwd|passphrase)\s*[:=]\s*['\"]?([^'\"\s\n\[]+)['\"]?", re.IGNORECASE),
]


class SecretScrubber:
    """Thread-safe scrubber managing dynamic credential registration and text redaction."""

    def __init__(self) -> None:
        self._exact_secrets: Set[str] = set()
        self._lock = threading.Lock()
        self._registered_env_keys = False

    def register_secret(self, secret: Optional[str]) -> None:
        """Register an exact sensitive credential string to be masked."""
        if not secret or not isinstance(secret, str):
            return
        cleaned = secret.strip()
        # Avoid registering short trivial strings
        if len(cleaned) > 5:
            with self._lock:
                self._exact_secrets.add(cleaned)

    def register_from_settings(self, settings: Any) -> None:
        """Register all credentials present in the active Settings object."""
        if not settings:
            return
        for attr in dir(settings):
            if "api_key" in attr or "secret" in attr or "password" in attr:
                try:
                    val = getattr(settings, attr)
                    if isinstance(val, str):
                        self.register_secret(val)
                except Exception:
                    pass

    def register_from_environment(self) -> None:
        """Scan and register all API keys and credential strings from the environment."""
        with self._lock:
            if self._registered_env_keys:
                return
            self._registered_env_keys = True

        for k, v in os.environ.items():
            k_lower = k.lower()
            if any(term in k_lower for term in ("key", "secret", "password", "token", "auth", "credential")):
                self.register_secret(v)

    def redact(self, text: Any) -> Any:
        """Redact any registered secrets or matching credential patterns from input."""
        if not isinstance(text, str):
            return text

        # 1. Register environment variables lazily if not done
        if not self._registered_env_keys:
            self.register_from_environment()

        sanitized = text

        # 2. Mask exact matched registered credentials
        # Sort by length descending to prevent sub-string masking issues
        with self._lock:
            sorted_secrets = sorted(self._exact_secrets, key=len, reverse=True)

        for secret in sorted_secrets:
            if secret in sanitized:
                sanitized = sanitized.replace(secret, "[REDACTED]")

        # 3. Mask generic credential format patterns
        for pattern in SECRET_REGEX_PATTERNS:
            try:
                # If pattern has capturing groups, replace with generic redacted text or label
                if "password" in pattern.pattern:
                    sanitized = pattern.sub(r"\1: [REDACTED_PASSWORD]", sanitized)
                elif "Bearer" in pattern.pattern:
                    sanitized = pattern.sub("Bearer [REDACTED_TOKEN]", sanitized)
                elif "aws_" in pattern.pattern or "Authorization" in pattern.pattern or "Cookie" in pattern.pattern:
                    # Do not overwrite already redacted tokens inside authorization headers
                    if "[REDACTED_" not in sanitized:
                        sanitized = pattern.sub(r"\1: [REDACTED_SECRET]", sanitized)
                else:
                    sanitized = pattern.sub("[REDACTED_SECRET]", sanitized)
            except Exception:
                pass

        return sanitized


# Global singleton instance
global_scrubber = SecretScrubber()


def redact_secrets(text: Any) -> Any:
    """Globally accessible function to scrub sensitive credentials and patterns from text."""
    return global_scrubber.redact(text)


def recursive_sanitize(data: Any) -> Any:
    """Recursively scrub all secrets, credentials, base64 images, and binary data from any Python object."""
    import json
    if isinstance(data, dict):
        cleaned_dict = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if k_lower.startswith("authorization_") or k_lower in ("authorizer", "authorization_decisions"):
                cleaned_dict[k] = recursive_sanitize(v)
            elif any(term == k_lower for term in ("key", "secret", "password", "token", "auth", "credential", "private_key", "cookie", "api_key", "access_token")) or any(term in k_lower for term in ("api_key", "secret", "password", "private_key", "client_secret", "auth_token", "token")):
                cleaned_dict[k] = "[REDACTED_SECRET]"
            else:
                cleaned_dict[k] = recursive_sanitize(v)
        return cleaned_dict
    elif isinstance(data, (list, tuple, set)):
        cleaned_list = [recursive_sanitize(item) for item in data]
        if isinstance(data, tuple):
            return tuple(cleaned_list)
        if isinstance(data, set):
            return set(cleaned_list)
        return cleaned_list
    elif isinstance(data, bytes):
        try:
            decoded = data.decode("utf-8")
            return recursive_sanitize(decoded).encode("utf-8")
        except UnicodeDecodeError:
            return b"[REDACTED_BINARY]"
    elif isinstance(data, str):
        if "data:image/" in data or "base64" in data.lower():
            if any(p in data for p in ("data:image/", "base64,")):
                return "[REDACTED_IMAGE]"
            if len(data) > 100 and " " not in data:
                return "[REDACTED_BINARY]"
        
        if (data.startswith("{") and data.endswith("}")) or (data.startswith("[") and data.endswith("]")):
            try:
                parsed = json.loads(data)
                scrubbed = recursive_sanitize(parsed)
                return json.dumps(scrubbed)
            except Exception:
                pass
        
        return redact_secrets(data)
    else:
        return data
