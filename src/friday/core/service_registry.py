"""Canonical Service Registry and Configuration for FRIDAY Universe.

Standardizes service parameters, startup health validation, mock universe guardrails,
and fail-closed production readiness.
"""

from __future__ import annotations

import os
import time
import json
from urllib.parse import urlparse
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import httpx

from friday.core.logging import get_logger

logger = get_logger("core.service_registry")


class ServiceHealth(str, Enum):
    ONLINE = "ONLINE"
    REACHABLE = "REACHABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    STANDBY = "STANDBY"


@dataclass
class ServiceConfig:
    """Canonical configuration for an individual FRIDAY Universe microservice."""

    name: str
    url: str
    api_key: str = ""
    enabled: bool = True
    required: bool = False
    health_path: str = "/health"
    timeout_sec: float = 3.0
    auth_header_name: str = "Authorization"
    auth_header_format: str = "Bearer {key}"
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            if self.auth_header_name.lower() == "x-api-key":
                headers["X-API-Key"] = self.api_key
            elif self.auth_header_name.lower() == "x-friday-api-key":
                headers["X-Friday-Api-Key"] = self.api_key
            else:
                headers[self.auth_header_name] = self.auth_header_format.format(key=self.api_key)
        return headers


class ServiceRegistry:
    """Canonical registry and lifecycle validator for all 8 peer agents in the FRIDAY Universe."""

    def __init__(self, env: str | None = None) -> None:
        self.env = env or os.getenv("FRIDAY_ENV", "development").lower()
        self._enforce_mock_policy()
        self.services: dict[str, ServiceConfig] = self._load_standard_services()

    def _enforce_mock_policy(self) -> None:
        """Validate mock policy rule: MOCK_UNIVERSE_ENABLED=true is rejected outside test mode."""
        mock_enabled = os.getenv("MOCK_UNIVERSE_ENABLED", "false").lower() in ("true", "1", "yes")
        if mock_enabled and self.env != "test":
            raise RuntimeError(
                f"Configuration Error: MOCK_UNIVERSE_ENABLED=true is strictly rejected outside test mode. "
                f"Current FRIDAY_ENV is '{self.env}'."
            )

    def _load_standard_services(self) -> dict[str, ServiceConfig]:
        """Load standard service configurations using standardized environment variables."""
        # 1. Inference / ASTRA
        inference_url = (os.getenv("FRIDAY_INFERENCE_URL") or os.getenv("INFERENCE_URL") or "https://inference-h7bn.onrender.com").rstrip("/")
        inference_key = os.getenv("FRIDAY_INFERENCE_API_KEY") or os.getenv("INFERENCE_API_KEY", "")

        # 2. Memora
        memora_url = (os.getenv("FRIDAY_MEMORA_URL") or os.getenv("MEMORA_URL") or "https://memora-cavc.onrender.com").rstrip("/")
        memora_key = os.getenv("FRIDAY_MEMORA_API_KEY") or os.getenv("MEMORA_API_KEY", "")

        # 3. Stratex
        stratex_url = (os.getenv("FRIDAY_STRATEX_URL") or os.getenv("STRATEX_URL") or "https://stratex-8wj1.onrender.com").rstrip("/")
        stratex_key = os.getenv("FRIDAY_STRATEX_API_KEY") or os.getenv("STRATEX_API_KEY", "")

        # 4. IntelX
        intelx_url = (os.getenv("FRIDAY_INTELX_URL") or os.getenv("INTELX_URL") or "https://intelx-mygl.onrender.com").rstrip("/")
        intelx_key = os.getenv("FRIDAY_INTELX_API_KEY") or os.getenv("INTELX_API_KEY", "")

        # 5. Futuris
        futuris_url = os.getenv("FUTURIS_URL", "https://futuris-th6f.onrender.com").rstrip("/")
        futuris_key = os.getenv("FRIDAY_FUTURIS_API_KEY") or os.getenv("FUTURIS_API_KEY", "")

        # 6. Cortex
        cortex_url = (os.getenv("FRIDAY_CORTEX_URL") or os.getenv("CORTEX_URL") or "https://cortex-0m7c.onrender.com").rstrip("/")
        cortex_key = os.getenv("FRIDAY_CORTEX_API_KEY") or os.getenv("CORTEX_API_KEY", "")

        # 7. Forge (Local :8001)
        forge_url = (os.getenv("FRIDAY_FORGE_URL") or os.getenv("FORGE_URL") or "https://forge-e9kl.onrender.com").rstrip("/")
        forge_key = os.getenv("FRIDAY_FORGE_API_KEY") or os.getenv("FORGE_API_KEY", "")

        # 8. Sentinel (Local :8003)
        sentinel_url = (os.getenv("FRIDAY_SENTINEL_URL") or os.getenv("SENTINEL_URL") or "https://sentinel-a861.onrender.com").rstrip("/")
        sentinel_key = os.getenv("FRIDAY_SENTINEL_API_KEY") or os.getenv("SENTINEL_API_KEY", "")

        is_prod = self.env == "production"

        return {
            "inference": ServiceConfig(
                name="inference",
                url=inference_url,
                api_key=inference_key,
                enabled=True,
                required=is_prod,
                health_path=os.getenv("FRIDAY_INFERENCE_HEALTH_PATH", "/health"),
                timeout_sec=4.0,
            ),
            "memora": ServiceConfig(
                name="memora",
                url=memora_url,
                api_key=memora_key,
                enabled=True,
                required=is_prod,
                health_path=os.getenv("FRIDAY_MEMORA_HEALTH_PATH", "/health"),
                timeout_sec=4.0,
            ),
            "stratex": ServiceConfig(
                name="stratex",
                url=stratex_url,
                api_key=stratex_key,
                enabled=True,
                required=False,
                health_path=os.getenv("FRIDAY_STRATEX_HEALTH_PATH", "/api/status"),
                timeout_sec=4.0,
            ),
            "intelx": ServiceConfig(
                name="intelx",
                url=intelx_url,
                api_key=intelx_key,
                enabled=True,
                required=False,
                health_path=os.getenv("FRIDAY_INTELX_HEALTH_PATH", "/api/v1/healthz"),
                timeout_sec=4.0,
            ),
            "futuris": ServiceConfig(
                name="futuris",
                url=futuris_url,
                api_key=futuris_key,
                enabled=True,
                required=False,
                health_path="/health",
                timeout_sec=5.0,
            ),
            "cortex": ServiceConfig(
                name="cortex",
                url=cortex_url,
                api_key=cortex_key,
                enabled=True,
                required=False,
                health_path=os.getenv("FRIDAY_CORTEX_HEALTH_PATH", "/health"),
                timeout_sec=4.0,
                auth_header_name="X-Friday-Api-Key",
                auth_header_format="{key}",
            ),
            "forge": ServiceConfig(
                name="forge",
                url=forge_url,
                api_key=forge_key,
                enabled=True,
                required=False,
                health_path="/health",
                timeout_sec=2.0,
            ),
            "sentinel": ServiceConfig(
                name="sentinel",
                url=sentinel_url,
                api_key=sentinel_key,
                enabled=True,
                required=False,
                health_path=os.getenv("FRIDAY_SENTINEL_HEALTH_PATH", "/health"),
                timeout_sec=2.0,
                auth_header_name="X-API-Key",
                auth_header_format="{key}",
            ),
        }

    def get(self, name: str) -> ServiceConfig | None:
        """Retrieve a service configuration by name."""
        return self.services.get(name.lower())

    async def probe_service(self, name: str, client: httpx.AsyncClient | None = None) -> tuple[ServiceHealth, int, str]:
        """Probe an individual service and return (status, latency_ms, details)."""
        svc = self.get(name)
        if not svc or not svc.enabled:
            return ServiceHealth.STANDBY, 0, f"Service '{name}' is not enabled"

        close_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=svc.timeout_sec)
            close_client = True

        t0 = time.time()
        url = f"{svc.url}{svc.health_path}"
        try:
            r = await client.get(url, headers=svc.get_headers(), timeout=svc.timeout_sec)
            lat = int((time.time() - t0) * 1000)
            if r.status_code in (401, 403):
                return ServiceHealth.REACHABLE, lat, f"Reachable; health endpoint requires authentication (HTTP {r.status_code})"
            if r.status_code not in (200, 201, 204):
                return ServiceHealth.DEGRADED, lat, f"Returned HTTP {r.status_code}"
            if r.status_code == 204:
                return ServiceHealth.REACHABLE, lat, "Reachable; endpoint returned no health payload"
            if urlparse(svc.url).hostname in {"localhost", "127.0.0.1", "::1"} and self.env != "production":
                return ServiceHealth.REACHABLE, lat, "Local test endpoint reachable; no explicit health state"
            try:
                body = r.json()
            except (ValueError, json.JSONDecodeError):
                body = None
            if isinstance(body, dict):
                for field_name in ("status", "health", "state"):
                    value = body.get(field_name)
                    if isinstance(value, str):
                        normalized = value.strip().lower()
                        if normalized in {"healthy", "ok", "online", "up", "ready"}:
                            return ServiceHealth.ONLINE, lat, f"Healthy response ({lat}ms)"
                        if normalized in {"unhealthy", "degraded", "down", "error", "unavailable", "critical"}:
                            return ServiceHealth.DEGRADED, lat, f"Service reports {normalized} ({lat}ms)"
                    elif value is True:
                        return ServiceHealth.ONLINE, lat, f"Healthy response ({lat}ms)"
                    elif value is False:
                        return ServiceHealth.DEGRADED, lat, f"Service reports unhealthy ({lat}ms)"
            return ServiceHealth.REACHABLE, lat, "Reachable; response contained no explicit health state"
        except Exception as e:
            lat = int((time.time() - t0) * 1000)
            return ServiceHealth.UNAVAILABLE, lat, f"Connection failed: {e}"
        finally:
            if close_client:
                await client.aclose()

    async def validate_startup(self) -> dict[str, tuple[ServiceHealth, int, str]]:
        """Validate startup health across enabled services.
        
        In production, raises RuntimeError if any required service is unavailable.
        """
        results: dict[str, tuple[ServiceHealth, int, str]] = {}
        async with httpx.AsyncClient() as client:
            for name, svc in self.services.items():
                if svc.enabled:
                    status, lat, details = await self.probe_service(name, client)
                    results[name] = (status, lat, details)
                    if self.env == "production" and svc.required and status == ServiceHealth.UNAVAILABLE:
                        raise RuntimeError(
                            f"Production Startup Failure: Required service '{name}' at {svc.url} is UNAVAILABLE: {details}"
                        )
                    logger.info(f"[ServiceRegistry] {name.upper():10} -> {status.value:12} ({lat}ms): {details}")
        return results


# Global singleton instance
service_registry = ServiceRegistry()
