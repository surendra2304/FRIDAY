"""Shared HTTP client for the Nexus website & growth engine.

Both Nexus skills (``skills/nexus_operator.py`` and ``skills/nexus_manager.py``)
used to answer from hardcoded telemetry while their docstrings claimed to query
Nexus. This client is the one place that actually talks to the service, so a
transport change (endpoint, auth, timeout) cannot make one skill honest and the
other fabricated.

Contract: :meth:`NexusCommandClient.command` never raises. It returns a dict
with ``ok``, ``http_status``, ``error``, ``payload`` and ``url``, so callers can
say *why* they have no reading instead of inventing one.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("integrations.nexus_client")


class NexusCommandClient:
    """POSTs ``{"command": ...}`` to ``{base_url}/v1/friday/command``."""

    def __init__(self, base_url: str = "http://localhost:8002", timeout_sec: float = 4.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self._lock = threading.RLock()
        self._last_result: dict[str, Any] = {"ok": None, "command": None, "url": None}
        # A shared last-result slot lets callers inspect the latest request, but
        # a per-thread slot prevents another concurrent skill invocation from
        # turning this call's failure into a different call's apparent success.
        self._thread_state = threading.local()

    @property
    def command_url(self) -> str:
        return f"{self.base_url}/v1/friday/command"

    def last_result(self) -> dict[str, Any]:
        """The outcome of the most recent command (ok, http_status, error, url)."""
        thread_result = getattr(self._thread_state, "last_result", None)
        if isinstance(thread_result, dict):
            return dict(thread_result)
        with self._lock:
            return dict(self._last_result)

    def _remember(self, result: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._last_result = result
        self._thread_state.last_result = result
        return result

    def mark_invalid_response(self, error: str) -> dict[str, Any]:
        """Marks the current command unusable after application-level validation."""
        result = self.last_result()
        result["ok"] = False
        result["error"] = error
        with self._lock:
            self._last_result = result
        self._thread_state.last_result = result
        return dict(result)

    def command(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Issues one command. Never raises; the caller decides what to say."""
        url = self.command_url
        result: dict[str, Any] = {
            "ok": False,
            "command": name,
            "url": url,
            "http_status": None,
            "error": None,
            "payload": {},
        }
        # The requested command is authoritative; caller-supplied payload data
        # must never be able to replace it.
        body = {**(payload or {}), "command": name}
        try:
            request = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                result["http_status"] = getattr(response, "status", None) or response.getcode()
                raw = response.read().decode("utf-8", errors="replace")
            result["ok"] = 200 <= int(result["http_status"] or 0) < 300
            if raw.strip():
                try:
                    parsed = json.loads(raw)
                    result["payload"] = parsed if isinstance(parsed, dict) else {"data": parsed}
                except ValueError:
                    # A 2xx with an unreadable body is not valid telemetry. If
                    # this remained `ok`, list readers could misreport a broken
                    # response as "there are none".
                    result["ok"] = False
                    result["error"] = "Invalid JSON response"
            if not result["ok"] and result["error"] is None:
                result["error"] = f"HTTP {result['http_status']}"
        except urllib.error.HTTPError as e:
            result["http_status"] = e.code
            result["error"] = f"HTTP {e.code}"
        except Exception as e:  # no answer at all
            result["error"] = f"{type(e).__name__}: {e}"
        return self._remember(result)

    def unavailable(self) -> dict[str, Any]:
        """A uniform 'Nexus did not answer' payload built from the last command."""
        last = self.last_result()
        return {
            "available": False,
            "status": "UNREACHABLE",
            "error": last.get("error") or "no response",
            "endpoint": last.get("url") or self.command_url,
            "sample_data": False,
        }

    def answered_a_failure(self) -> bool:
        """True when the last command reported a failure (so lists are not 'empty')."""
        return self.last_result().get("ok") is False
