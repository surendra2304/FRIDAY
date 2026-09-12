"""Canonical Service Registry and Configuration for FRIDAY Universe.

Standardizes service parameters, startup health validation, mock universe guardrails,
and fail-closed production readiness.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import httpx

from friday.core.logging import get_logger

logger = get_logger("core.service_registry")


class ServiceHealth(str, Enum):
    ONLINE = "ONLINE"
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
        inference_url = os.getenv("INFERENCE_URL", "https://inference-3i2b.onrender.com").rstrip("/")
        inference_key = os.getenv("INFERENCE_API_KEY", "inference_api")

        # 2. Memora
        memora_url = os.getenv("MEMORA_URL", "https://memora-9zr9.onrender.com").rstrip("/")
        memora_key = os.getenv("MEMORA_API_KEY", "memora_api")

        # 3. Stratex
        stratex_url = os.getenv("STRATEX_URL", "https://stratex-ucjz.onrender.com").rstrip("/")
        stratex_key = os.getenv("STRATEX_API_KEY", "stratex_api")

        # 4. IntelX
        intelx_url = os.getenv("INTELX_URL", "https://intelx-3cz1.onrender.com").rstrip("/")
        intelx_key = os.getenv("INTELX_API_KEY", "intelx_api")

        # 5. Futuris
        futuris_url = os.getenv("FUTURIS_URL", "https://futuris-x4f4.onrender.com").rstrip("/")
        futuris_key = os.getenv("FUTURIS_API_KEY", "friday_secret_key_default")

        # 6. Cortex
        cortex_url = os.getenv("CORTEX_URL", "https://cortex-qifr.onrender.com").rstrip("/")
        cortex_key = os.getenv("CORTEX_API_KEY", "friday_api")

        # 7. Forge (Local :8001)
        forge_url = os.getenv("FORGE_URL", "http://127.0.0.1:8001").rstrip("/")
        forge_key = os.getenv("FORGE_API_KEY", "forge_api")

        # 8. Sentinel (Local :8003)
        sentinel_url = os.getenv("SENTINEL_URL", "http://127.0.0.1:8003").rstrip("/")
        sentinel_key = os.getenv("SENTINEL_API_KEY", "sentinel_api")

        is_prod = self.env == "production"

        return {
            "inference": ServiceConfig(
                name="inference",
                url=inference_url,
                api_key=inference_key,
                enabled=True,
                required=is_prod,
                health_path="/health",
                timeout_sec=4.0,
            ),
            "memora": ServiceConfig(
                name="memora",
                url=memora_url,
                api_key=memora_key,
                enabled=True,
                required=is_prod,
                health_path="/health",
                timeout_sec=4.0,
            ),
            "stratex": ServiceConfig(
                name="stratex",
                url=stratex_url,
                api_key=stratex_key,
                enabled=True,
                required=False,
                health_path="/api/engine-health",
                timeout_sec=4.0,
            ),
            "intelx": ServiceConfig(
                name="intelx",
                url=intelx_url,
                api_key=intelx_key,
                enabled=True,
                required=False,
                health_path="/health",
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
                health_path="/v1/health/liveness",
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
                health_path="/api/v1/health",
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
            if r.status_code in (200, 201, 204):
                return ServiceHealth.ONLINE, lat, f"Online ({lat}ms)"
            elif r.status_code == 503:
                return ServiceHealth.DEGRADED, lat, f"Degraded status {r.status_code}"
            else:
                return ServiceHealth.DEGRADED, lat, f"Returned HTTP {r.status_code}"
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
