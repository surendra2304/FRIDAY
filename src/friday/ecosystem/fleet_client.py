"""FRIDAY Universe Live Fleet Client.

Provides resilient, low-latency asynchronous communication with all 8 specialist
microservices in the FRIDAY Universe:
1. Inference  (Multi-Model Consensus AI Gateway)
2. Memora     (Persistent Cloud Vector Memory Fabric)
3. Stratex    (24/7 Algorithmic Trading Platform)
4. IntelX     (Macro Intelligence & Evidence Research)
5. Futuris    (Calibrated Probabilistic Forecasting)
6. Cortex     (Autonomous Web Operations & Scraper)
7. Forge      (Autonomous Software Engineering Engine)
8. Sentinel   (Zero-Trust Cybersecurity & Threat Defense)

Live probes and task receipts are evidence-labelled; reachability is not treated as
agent health, and HTTP acceptance is not treated as task completion.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from friday.core.task_envelope import ActionReceipt, TaskEnvelope, TaskResult, TaskStatus


def _classify_health_response(response: httpx.Response) -> str:
    if response.status_code in (401, 403):
        return "REACHABLE"
    if response.status_code not in (200, 201, 204):
        return "DEGRADED"
    if response.status_code == 204:
        return "REACHABLE"
    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError):
        body = None
    if isinstance(body, dict):
        for name in ("status", "health", "state"):
            value = body.get(name)
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"healthy", "ok", "online", "up", "ready"}:
                    return "ONLINE"
                if normalized in {"unhealthy", "degraded", "down", "error", "unavailable", "critical"}:
                    return "DEGRADED"
            elif value is True:
                return "ONLINE"
            elif value is False:
                return "DEGRADED"
    return "REACHABLE"


@dataclass
class AgentStatus:
    id: str
    name: str
    role: str
    icon: str
    status: str  # ONLINE, REACHABLE, DEGRADED, UNREACHABLE, or OFFLINE
    latency_ms: int
    endpoint: str
    details: str
    last_checked: str


class FleetClient:
    """Unified client for live communication with all FRIDAY Universe specialist agents."""

    def __init__(self, timeout_sec: float = 12.0, settings: Any | None = None) -> None:
        self.timeout = timeout_sec
        self._status_cache: dict[str, AgentStatus] = {}
        self._last_cache_time: float = 0.0
        self._cache_ttl: float = 4.0  # 4-second cache to prevent spamming cloud services

        # Resolve actual configured values. Never send example credentials to
        # cloud peers; an absent key stays absent and auth failures stay visible.
        if settings is None:
            from friday.core.config import get_settings
            settings = get_settings()

        def configured_url(setting_name: str, fallback: str) -> str:
            env_name = f"FRIDAY_{setting_name.upper()}"
            legacy_name = setting_name.upper()
            return (os.getenv(env_name) or os.getenv(legacy_name) or getattr(settings, setting_name, None) or fallback).rstrip("/")

        def configured_key(setting_name: str) -> str:
            return getattr(settings, setting_name, None) or ""

        self.inference_url = configured_url("inference_url", "")
        self.inference_key = configured_key("inference_api_key")
        self.memora_url = configured_url("memora_url", "")
        self.memora_key = configured_key("memora_api_key")
        self.stratex_url = configured_url("stratex_url", "")
        self.stratex_key = configured_key("stratex_api_key")
        self.intelx_url = configured_url("intelx_url", "")
        self.intelx_key = configured_key("intelx_api_key")
        self.futuris_url = configured_url("futuris_url", "")
        self.futuris_local_url = os.getenv("FRIDAY_FUTURIS_LOCAL_URL", "").rstrip("/")
        self.futuris_key = configured_key("futuris_api_key")
        self.cortex_url = configured_url("cortex_url", "")
        self.cortex_key = configured_key("cortex_api_key")
        self.forge_url = configured_url("forge_url", "")
        self.forge_key = configured_key("forge_api_key")
        self.sentinel_url = configured_url("sentinel_url", "")
        self.sentinel_key = configured_key("sentinel_api_key")
        self._shared_client: httpx.AsyncClient | None = None

    def get_shared_client(self) -> httpx.AsyncClient:
        if self._shared_client is None or self._shared_client.is_closed:
            self._shared_client = httpx.AsyncClient(timeout=30.0)
        return self._shared_client

    async def aclose(self) -> None:
        """Close and release the shared HTTP pool during owner shutdown.

        Callers must stop request/background tasks before shutdown so a late
        request cannot create a replacement pool while this one is closing.
        """
        client, self._shared_client = self._shared_client, None
        if client is not None and not client.is_closed:
            await client.aclose()

    # =========================================================================
    # 1. LIVE HEALTH & TELEMETRY PROBES
    # =========================================================================

    async def probe_inference(self, client: httpx.AsyncClient) -> AgentStatus:
        t0 = time.time()
        try:
            headers = {"Authorization": f"Bearer {self.inference_key}"} if self.inference_key else {}
            r = await client.get(f"{self.inference_url}/health", headers=headers, timeout=3.5)
            lat = int((time.time() - t0) * 1000)
            status = _classify_health_response(r)
            if status in {"ONLINE", "REACHABLE"}:
                return AgentStatus(
                    id="inference", name="Inference", role="Cloud AI Gateway", icon="⚡",
                    status=status, latency_ms=lat, endpoint=self.inference_url,
                    details=f"{status}: HTTP health response received ({lat}ms). Model completion was not checked.",
                    last_checked=datetime.now(timezone.utc).isoformat(),
                )
        except Exception as e:
            lat = int((time.time() - t0) * 1000)
            return AgentStatus(
                id="inference", name="Inference", role="Cloud AI Gateway", icon="⚡",
                status="UNREACHABLE", latency_ms=lat, endpoint=self.inference_url,
                details=f"Inference gateway error: {e}",
                last_checked=datetime.now(timezone.utc).isoformat(),
            )
        return AgentStatus(
            id="inference", name="Inference", role="Cloud AI Gateway", icon="⚡",
            status="DEGRADED", latency_ms=int((time.time() - t0) * 1000), endpoint=self.inference_url,
            details=f"Status HTTP {r.status_code}", last_checked=datetime.now(timezone.utc).isoformat(),
        )

    async def probe_memora(self, client: httpx.AsyncClient) -> AgentStatus:
        t0 = time.time()
        try:
            headers = {"X-Agent-Name": "friday"}
            if self.memora_key:
                headers["Authorization"] = f"Bearer {self.memora_key}"
            r = await client.get(f"{self.memora_url}/health", headers=headers, timeout=3.5)
            lat = int((time.time() - t0) * 1000)
            status = _classify_health_response(r)
            if status in {"ONLINE", "REACHABLE"}:
                return AgentStatus(
                    id="memora", name="Memora", role="Persistent Memory", icon="🧠",
                    status=status, latency_ms=lat, endpoint=self.memora_url,
                    details=f"{status}: HTTP health response received ({lat}ms). Memory write/read was not checked.",
                    last_checked=datetime.now(timezone.utc).isoformat(),
                )
        except Exception as e:
            lat = int((time.time() - t0) * 1000)
            return AgentStatus(
                id="memora", name="Memora", role="Persistent Memory", icon="🧠",
                status="UNREACHABLE", latency_ms=lat, endpoint=self.memora_url,
                details=f"Cloud memory probe error: {e}",
                last_checked=datetime.now(timezone.utc).isoformat(),
            )
        return AgentStatus(
            id="memora", name="Memora", role="Persistent Memory", icon="🧠",
            status="DEGRADED", latency_ms=int((time.time() - t0) * 1000), endpoint=self.memora_url,
            details=f"Health endpoint returned HTTP {r.status_code}; memory access was not verified.",
            last_checked=datetime.now(timezone.utc).isoformat(),
        )

    async def probe_stratex(self, client: httpx.AsyncClient) -> AgentStatus:
        t0 = time.time()
        try:
            headers = {}
            if self.stratex_key:
                headers = {"X-API-Key": self.stratex_key, "Authorization": f"Bearer {self.stratex_key}"}
            health_path = os.getenv("FRIDAY_STRATEX_HEALTH_PATH", "/api/status")
            r = await client.get(f"{self.stratex_url}{health_path}", headers=headers, timeout=3.5)
            lat = int((time.time() - t0) * 1000)
            status = _classify_health_response(r)
            if status in {"ONLINE", "REACHABLE"}:
                return AgentStatus(
                    id="stratex", name="Stratex", role="Algorithmic Trading", icon="📈",
                    status=status, latency_ms=lat, endpoint=self.stratex_url,
                    details=f"{status}: HTTP health response received ({lat}ms). Trading mode and order execution were not checked.",
                    last_checked=datetime.now(timezone.utc).isoformat(),
                )
        except Exception as e:
            lat = int((time.time() - t0) * 1000)
            return AgentStatus(
                id="stratex", name="Stratex", role="Algorithmic Trading", icon="📈",
                status="UNREACHABLE", latency_ms=lat, endpoint=self.stratex_url,
                details=f"Trading engine probe error: {e}",
                last_checked=datetime.now(timezone.utc).isoformat(),
            )
        return AgentStatus(
            id="stratex", name="Stratex", role="Algorithmic Trading", icon="📈",
            status="DEGRADED", latency_ms=int((time.time() - t0) * 1000), endpoint=self.stratex_url,
            details=f"Health endpoint returned HTTP {r.status_code}; trading functionality was not verified.",
            last_checked=datetime.now(timezone.utc).isoformat(),
        )

    async def probe_intelx(self, client: httpx.AsyncClient) -> AgentStatus:
        t0 = time.time()
        try:
            headers = {"Authorization": f"Bearer {self.intelx_key}"} if self.intelx_key else {}
            health_path = os.getenv("FRIDAY_INTELX_HEALTH_PATH", "/api/v1/healthz")
            r = await client.get(f"{self.intelx_url}{health_path}", headers=headers, timeout=3.5)
            lat = int((time.time() - t0) * 1000)
            status = _classify_health_response(r)
            if status in {"ONLINE", "REACHABLE"}:
                return AgentStatus(
                    id="intelx", name="IntelX", role="Macro Research", icon="🔍",
                    status=status, latency_ms=lat, endpoint=self.intelx_url,
                    details=f"{status}: HTTP health response received ({lat}ms). Source ingestion and research were not checked.",
                    last_checked=datetime.now(timezone.utc).isoformat(),
                )
        except Exception as e:
            lat = int((time.time() - t0) * 1000)
            return AgentStatus(
                id="intelx", name="IntelX", role="Macro Research", icon="🔍",
                status="UNREACHABLE", latency_ms=lat, endpoint=self.intelx_url,
                details=f"Research engine error: {e}",
                last_checked=datetime.now(timezone.utc).isoformat(),
            )
        return AgentStatus(
            id="intelx", name="IntelX", role="Macro Research", icon="🔍",
            status="DEGRADED", latency_ms=int((time.time() - t0) * 1000), endpoint=self.intelx_url,
            details=f"Health endpoint returned HTTP {r.status_code}; research functionality was not verified.",
            last_checked=datetime.now(timezone.utc).isoformat(),
        )

    async def probe_futuris(self, client: httpx.AsyncClient) -> AgentStatus:
        t0 = time.time()
        # 1. Local daemon first (:8004)
        try:
            r_loc = await client.get(f"{self.futuris_local_url}/health", timeout=0.8) if self.futuris_local_url else None
            lat_loc = int((time.time() - t0) * 1000)
            if r_loc is not None and _classify_health_response(r_loc) in {"ONLINE", "REACHABLE"}:
                local_status = _classify_health_response(r_loc)
                return AgentStatus(
                    id="futuris", name="Futuris", role="Predictive Forecaster", icon="🔮",
                    status=local_status, latency_ms=lat_loc, endpoint=self.futuris_local_url,
                    details=f"{local_status}: HTTP health response received ({lat_loc}ms). Forecasting was not checked.",
                    last_checked=datetime.now(timezone.utc).isoformat(),
                )
        except Exception:
            pass

        # 2. Cloud fallback
        try:
            headers = {"Authorization": f"Bearer {self.futuris_key}"} if self.futuris_key else {}
            health_path = os.getenv("FRIDAY_FUTURIS_HEALTH_PATH", "/health")
            r = await client.get(f"{self.futuris_url}{health_path}", headers=headers, timeout=1.5)
            lat = int((time.time() - t0) * 1000)
            status = _classify_health_response(r)
            if status in {"ONLINE", "REACHABLE"}:
                return AgentStatus(
                    id="futuris", name="Futuris", role="Predictive Forecaster", icon="🔮",
                    status=status, latency_ms=lat, endpoint=self.futuris_url,
                    details=f"{status}: HTTP health response received ({lat}ms). Forecasting was not checked.",
                    last_checked=datetime.now(timezone.utc).isoformat(),
                )
            return AgentStatus(
                id="futuris", name="Futuris", role="Predictive Forecaster", icon="🔮",
                status="UNREACHABLE", latency_ms=lat, endpoint=self.futuris_url,
                details=f"Forecasting engine returned status {r.status_code}",
                last_checked=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            lat_err = int((time.time() - t0) * 1000)
            return AgentStatus(
                id="futuris", name="Futuris", role="Predictive Forecaster", icon="🔮",
                status="UNREACHABLE", latency_ms=lat_err, endpoint=self.futuris_url,
                details=f"Forecasting engine unreachable: {e}",
                last_checked=datetime.now(timezone.utc).isoformat(),
            )

    async def probe_cortex(self, client: httpx.AsyncClient) -> AgentStatus:
        t0 = time.time()
        try:
            headers = {"X-Friday-Api-Key": self.cortex_key} if self.cortex_key else {}
            health_path = os.getenv("FRIDAY_CORTEX_HEALTH_PATH", "/health")
            r = await client.get(f"{self.cortex_url}{health_path}", headers=headers, timeout=3.5)
            lat = int((time.time() - t0) * 1000)
            status = _classify_health_response(r)
            if status in {"ONLINE", "REACHABLE"}:
                return AgentStatus(
                    id="cortex", name="Cortex", role="Web Operations", icon="🌐",
                    status=status, latency_ms=lat, endpoint=self.cortex_url,
                    details=f"{status}: HTTP health response received ({lat}ms). CRM, outreach, and worker activity were not checked.",
                    last_checked=datetime.now(timezone.utc).isoformat(),
                )
        except Exception as e:
            lat = int((time.time() - t0) * 1000)
            return AgentStatus(
                id="cortex", name="Cortex", role="Web Operations", icon="🌐",
                status="UNREACHABLE", latency_ms=lat, endpoint=self.cortex_url,
                details=f"Web operations probe error: {e}",
                last_checked=datetime.now(timezone.utc).isoformat(),
            )
        return AgentStatus(
            id="cortex", name="Cortex", role="Web Operations", icon="🌐",
            status="DEGRADED", latency_ms=int((time.time() - t0) * 1000), endpoint=self.cortex_url,
            details=f"Health summary returned HTTP {r.status_code}; Cortex workflows were not verified.",
            last_checked=datetime.now(timezone.utc).isoformat(),
        )

    async def probe_forge(self, client: httpx.AsyncClient) -> AgentStatus:
        t0 = time.time()
        try:
            headers = {"Authorization": f"Bearer {self.forge_key}"} if self.forge_key else {}
            health_path = os.getenv("FRIDAY_FORGE_HEALTH_PATH", "/health")
            r = await client.get(f"{self.forge_url}{health_path}", headers=headers, timeout=5.0)
            lat = int((time.time() - t0) * 1000)
            status = _classify_health_response(r)
            if status in {"ONLINE", "REACHABLE"}:
                return AgentStatus(
                    id="forge", name="Forge", role="Software Engineering", icon="🛠️",
                    status=status, latency_ms=lat, endpoint=self.forge_url,
                    details=f"{status}: HTTP health response received ({lat}ms). Build execution was not checked.",
                    last_checked=datetime.now(timezone.utc).isoformat(),
                )
        except Exception as e:
            lat = int((time.time() - t0) * 1000)
            return AgentStatus(
                id="forge", name="Forge", role="Software Engineering", icon="🛠️",
                status="UNREACHABLE", latency_ms=lat, endpoint=self.forge_url,
                details=f"Forge local daemon unreachable ({lat}ms): {e}",
                last_checked=datetime.now(timezone.utc).isoformat(),
            )
        return AgentStatus(
            id="forge", name="Forge", role="Software Engineering", icon="🛠️",
            status="DEGRADED", latency_ms=int((time.time() - t0) * 1000), endpoint=self.forge_url,
            details=f"Health endpoint returned HTTP {r.status_code}; build functionality was not verified.",
            last_checked=datetime.now(timezone.utc).isoformat(),
        )

    async def probe_sentinel(self, client: httpx.AsyncClient) -> AgentStatus:
        t0 = time.time()
        try:
            headers = {"X-API-Key": self.sentinel_key} if self.sentinel_key else {}
            health_path = os.getenv("FRIDAY_SENTINEL_HEALTH_PATH", "/health")
            r = await client.get(f"{self.sentinel_url}{health_path}", headers=headers, timeout=5.0)
            lat = int((time.time() - t0) * 1000)
            status = _classify_health_response(r)
            if status in {"ONLINE", "REACHABLE"}:
                return AgentStatus(
                    id="sentinel", name="Sentinel", role="Cybersecurity Shield", icon="🛡️",
                    status=status, latency_ms=lat, endpoint=self.sentinel_url,
                    details=f"{status}: HTTP health response received ({lat}ms). Audit integrity and scanning were not checked.",
                    last_checked=datetime.now(timezone.utc).isoformat(),
                )
        except Exception as e:
            lat = int((time.time() - t0) * 1000)
            return AgentStatus(
                id="sentinel", name="Sentinel", role="Cybersecurity Shield", icon="🛡️",
                status="UNREACHABLE", latency_ms=lat, endpoint=self.sentinel_url,
                details=f"Sentinel local daemon unreachable ({lat}ms): {e}",
                last_checked=datetime.now(timezone.utc).isoformat(),
            )
        return AgentStatus(
            id="sentinel", name="Sentinel", role="Cybersecurity Shield", icon="🛡️",
            status="DEGRADED", latency_ms=int((time.time() - t0) * 1000), endpoint=self.sentinel_url,
            details=f"Health endpoint returned HTTP {r.status_code}; security functionality was not verified.",
            last_checked=datetime.now(timezone.utc).isoformat(),
        )

    async def get_all_statuses(self, force_refresh: bool = False) -> list[AgentStatus]:
        """Probes all 8 specialist agents concurrently with caching."""
        now = time.time()
        if not force_refresh and self._status_cache and (now - self._last_cache_time < self._cache_ttl):
            return list(self._status_cache.values())

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            tasks = [
                self.probe_inference(client),
                self.probe_memora(client),
                self.probe_stratex(client),
                self.probe_intelx(client),
                self.probe_futuris(client),
                self.probe_cortex(client),
                self.probe_forge(client),
                self.probe_sentinel(client),
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        statuses: list[AgentStatus] = []
        for res in results:
            if isinstance(res, AgentStatus):
                statuses.append(res)
                self._status_cache[res.id] = res

        self._last_cache_time = now
        return statuses

    # =========================================================================
    # 2. LIVE SPECIALIST AGENT EXECUTION (100% REAL DATA, ZERO MOCK)
    # =========================================================================

    async def ask_inference(self, question: str) -> dict[str, Any]:
        """Queries the live Inference AI Gateway."""
        url = f"{self.inference_url}/v1/agent/assist"
        headers = {
            "X-FRIDAY-API-Key": self.inference_key,
            "Content-Type": "application/json",
        }
        payload = {
            "caller_agent": "friday",
            "task_type": "general",
            "prompt": question,
            "fast_lane": True,
            "no_cache": False,
            "max_tokens": 60,
        }
        try:
            client = self.get_shared_client()
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                answer = data.get("response", str(data))
                model_used = data.get("model_used", "auto")
                provider_used = data.get("provider_used", "inference")
                formatted_reply = (
                    f"⚡ [INFERENCE GATEWAY // FAST-LANE ACTIVE]\n"
                    f"Model: {model_used} | Provider: {provider_used}\n\n"
                    f"{answer}"
                )
                return {
                    "reply": formatted_reply,
                    "metadata": {
                        "agent_id": "inference", "agent_name": "Inference",
                        "model_used": model_used, "provider_used": provider_used,
                        # One model answered one request. Consensus is agreement
                        # between independent answers, and nothing here asked a
                        # second model, so claiming it was a fabricated result
                        # (BUG-014). The field is kept, and kept false, because
                        # callers key off it.
                        "consensus_reached": False,
                        "consensus_note": (
                            "single-model response; consensus is not measured on the fast lane"
                        ),
                    },
                }
            else:
                return {
                    "reply": f"⚡ [INFERENCE GATEWAY] Error HTTP {resp.status_code}: {resp.text}",
                    "metadata": {"agent_id": "inference", "error": resp.text},
                }
        except Exception as e:
            return {
                "reply": f"⚡ [INFERENCE GATEWAY] Direct connection error: {e}",
                "metadata": {"agent_id": "inference", "error": str(e)},
            }

    async def ask_memora(self, query: str) -> dict[str, Any]:
        """Queries the live Memora Cloud Persistent Memory Fabric (Sub-second SLA)."""
        headers = {
            "Authorization": f"Bearer {self.memora_key}",
            "X-Agent-Name": "friday",
        }
        try:
            client = self.get_shared_client()
            # Single optimized context retrieval: /v1/context bundles search, relevance ranking, and summary
            r_ctx = await client.post(
                f"{self.memora_url}/v1/context",
                json={"task_query": query, "token_budget": 1000},
                headers=headers,
                timeout=4.0,
            )

            if r_ctx.status_code != 200:
                return {"reply": f"Memora context request failed with HTTP {r_ctx.status_code}.", "metadata": {"agent_id": "memora", "error": f"HTTP {r_ctx.status_code}", "success": False}}
            ctx_data = r_ctx.json()
            bundle_id = ctx_data.get("bundle_id")
            summary = ctx_data.get("summary") or "Memora did not include a summary in its response."
            search_data = ctx_data.get("memories", [])

            recalled_lines = []
            if isinstance(search_data, list) and search_data:
                for item in search_data[:4]:
                    txt = item.get("content_text", "")
                    mtype = item.get("memory_type", "memory").upper()
                    recalled_lines.append(f"  • [{mtype}] {txt}")

            recalled_text = "\n".join(recalled_lines) if recalled_lines else "  • No specific memory match found."

            formatted_reply = (
                f"🧠 [MEMORA RESPONSE // HTTP {r_ctx.status_code}]\n"
                f"Bundle ID: {bundle_id or 'not supplied'}\n"
                f"Recalled Knowledge & Preferences:\n{recalled_text}\n\n"
                f"Memora response:\n{summary}"
            )
            return {
                "reply": formatted_reply,
                "metadata": {
                    "agent_id": "memora", "agent_name": "Memora",
                    "bundle_id": bundle_id, "recalled_memories": search_data,
                    "endpoint_response_received": True, "task_completion_verified": False,
                },
            }
        except Exception as e:
            return {
                "reply": f"🧠 [MEMORA PERSISTENT MEMORY] Error connecting to Turso Cloud: {e}",
                "metadata": {"agent_id": "memora", "error": str(e)},
            }

    async def ask_stratex(self, query: str) -> dict[str, Any]:
        """Queries the live Stratex Algorithmic Trading Platform (Sub-second SLA)."""
        headers = {"X-API-Key": self.stratex_key, "Authorization": f"Bearer {self.stratex_key}"}
        try:
            client = self.get_shared_client()
            r_health = await client.get(f"{self.stratex_url}/api/engine-health", headers=headers, timeout=3.0)
            if r_health.status_code != 200:
                return {"reply": f"Stratex engine health request failed with HTTP {r_health.status_code}.", "metadata": {"agent_id": "stratex", "error": f"HTTP {r_health.status_code}", "success": False}}
            h_data = r_health.json()

            eng_status = h_data.get("engine_status", "not reported")
            strat = h_data.get("active_strategy", "not reported")
            binance_conn = h_data.get("binance_connected")
            heartbeat = h_data.get("heartbeat_age_seconds", "not reported")
            symbols = h_data.get("symbols", [])
            symbol_count = h_data.get("symbol_count", len(symbols) if "symbols" in h_data else "not reported")
            timeframes = ", ".join(h_data.get("timeframes", [])[:3]) or "not reported"

            formatted_reply = (
                f"📈 [STRATEX ENGINE HEALTH RESPONSE]\n"
                f"Engine Status: {eng_status} (Heartbeat: {heartbeat}s) | Active Strategy: {strat}\n"
                f"Binance Connected: {'YES' if binance_conn is True else ('NO' if binance_conn is False else 'not reported')}\n\n"
                f"Market Execution Telemetry:\n"
                f"• Active Trading Pairs: {symbol_count} symbols monitored ({timeframes})\n"
                # `{'HEALTHY' if h_data.get('healthy') else 'STANDBY'}` turned an
                # absent field into STANDBY (a claim about the worker) and
                # defaulted the supervisor to ONLINE. Both now say what was sent.
                f"• Engine Worker: "
                f"{'HEALTHY' if h_data.get('healthy') is True else ('STANDBY' if h_data.get('healthy') is False else 'not reported')}"
                f" | Supervisor: {h_data.get('paper_runner_status') or 'not reported'}\n"
                f"• Risk and strategy details are shown only when returned by the endpoint. No trade was requested or verified."
            )
            return {
                "reply": formatted_reply,
                "metadata": {
                    "agent_id": "stratex", "agent_name": "Stratex",
                    "engine_status": eng_status, "strategy": strat, "symbol_count": symbol_count,
                    "endpoint_response_received": True, "task_completion_verified": False,
                },
            }
        except Exception as e:
            return {
                "reply": f"📈 [STRATEX 24/7 TRADING] Error connecting to trading platform: {e}",
                "metadata": {"agent_id": "stratex", "error": str(e)},
            }

    async def ask_intelx(self, query: str) -> dict[str, Any]:
        """Queries the live IntelX Macro Research & Evidence Engine."""
        headers = {"Authorization": f"Bearer {self.intelx_key}"}
        try:
            client = self.get_shared_client()
            r_health = await client.get(f"{self.intelx_url}/api/v1/healthz", headers=headers, timeout=8.0)
            if r_health.status_code != 200:
                return {"reply": f"IntelX health request failed with HTTP {r_health.status_code}.", "metadata": {"agent_id": "intelx", "error": f"HTTP {r_health.status_code}", "success": False}}
            h_data = r_health.json()
            ver = h_data.get("version", "not reported")
            db_st = h_data.get("database", "not reported")
            mock_mode = h_data.get("mock_mode")

            formatted_reply = (
                f"🔍 [INTELX HEALTH RESPONSE]\n"
                f"Version: {ver} | Database: {str(db_st).upper()} | Mock mode: {mock_mode if mock_mode is not None else 'not reported'}\n\n"
                "This call checked the health endpoint only. It did not submit a research query or verify news delivery."
            )
            return {
                "reply": formatted_reply,
                "metadata": {
                    "agent_id": "intelx", "agent_name": "IntelX",
                    "version": ver, "database": db_st,
                    "endpoint_response_received": True, "research_completed": False,
                },
            }
        except Exception as e:
            return {
                "reply": f"🔍 [INTELX RESEARCH] Error connecting to IntelX engine: {e}",
                "metadata": {"agent_id": "intelx", "error": str(e)},
            }

    async def ask_futuris(self, query: str) -> dict[str, Any]:
        """Queries the live Futuris Probabilistic Forecasting Engine (Local port :8004 first, cloud fallback)."""
        headers = {"X-API-Key": self.futuris_key}
        targets = [
            ("LOCAL DAEMON", f"{self.futuris_local_url}/v1/friday/calibration", 1.5),
            ("CLOUD RENDER", f"{self.futuris_url}/v1/friday/calibration", 2.5),
        ]
        client = self.get_shared_client()
        last_error = "unreachable"

        for origin, target_url, timeout_val in targets:
            try:
                r_cal = await client.get(target_url, headers=headers, timeout=timeout_val)
                if r_cal.status_code == 200:
                    cal_data = r_cal.json()
                    ece = cal_data.get("overall_ece")
                    trend = cal_data.get("trend")
                    targets_dict = cal_data.get("per_target_type_calibration", {})
                    acc = cal_data.get("recent_accuracy_summary", {})
                    brier = acc.get("brier_score")
                    samples = acc.get("resolved_samples")

                    values = []
                    if ece is not None:
                        values.append(f"Overall ECE: {ece}")
                    if trend is not None:
                        values.append(f"Trend: {trend}")
                    if brier is not None:
                        values.append(f"Brier score: {brier}")
                    if samples is not None:
                        values.append(f"Resolved samples: {samples}")
                    values.extend(f"{k} calibration: {v}" for k, v in targets_dict.items())

                    formatted_reply = (
                        f"🔮 [FUTURIS CALIBRATION RESPONSE // {origin}]\n"
                        + ("\n".join(values) if values else "No calibration metrics were included in the response.")
                        + "\nThis was a calibration query, not a forecast for the requested topic."
                    )
                    return {
                        "reply": formatted_reply,
                        "metadata": {
                            "agent_id": "futuris", "agent_name": "Futuris",
                            "overall_ece": ece, "brier_score": brier, "trend": trend,
                            "endpoint_response_received": True, "forecast_completed": False,
                        },
                    }
                else:
                    last_error = f"HTTP {r_cal.status_code}: {r_cal.text[:100]}"
            except Exception as e:
                last_error = str(e)
                continue

        return {
            "reply": f"🔮 [FUTURIS FORECASTER] Error connecting to Futuris engine: {last_error}",
            "metadata": {"agent_id": "futuris", "error": last_error},
        }

    async def ask_cortex(self, query: str) -> dict[str, Any]:
        """Queries the live Cortex Web Operations & Growth Engine."""
        headers = {"X-Friday-Api-Key": self.cortex_key}
        try:
            client = self.get_shared_client()
            r_summary = await client.get(f"{self.cortex_url}/v1/friday/health_summary", headers=headers, timeout=8.0)
            if r_summary.status_code != 200:
                return {"reply": f"Cortex health summary request failed with HTTP {r_summary.status_code}.", "metadata": {"agent_id": "cortex", "error": f"HTTP {r_summary.status_code}", "success": False}}
            data = r_summary.json()
            if not isinstance(data, dict):
                return {"reply": "Cortex returned an unexpected health-summary format.", "metadata": {"agent_id": "cortex", "error": "unexpected_response_format", "success": False}}

            formatted_reply = (
                "🌐 [CORTEX HEALTH SUMMARY RESPONSE]\n"
                + json.dumps(data, ensure_ascii=False, default=str)[:2000]
                + "\nThis was a status query; no lead, outreach, or SaaS task was performed."
            )
            return {
                "reply": formatted_reply,
                "metadata": {
                    "agent_id": "cortex", "agent_name": "Cortex",
                    "endpoint_response_received": True, "task_completion_verified": False,
                },
            }
        except Exception as e:
            return {
                "reply": f"🌐 [CORTEX WEB OPS] Error connecting to Cortex engine: {e}",
                "metadata": {"agent_id": "cortex", "error": str(e)},
            }

    async def ask_forge(self, query: str) -> dict[str, Any]:
        """Queries the live Forge Autonomous Software Engineering Engine."""
        headers = {"Authorization": f"Bearer {self.forge_key}"}
        try:
            client = self.get_shared_client()
            r_analytics, r_tasks = await asyncio.gather(
                client.get(f"{self.forge_url}/api/v1/analytics/summary", headers=headers, timeout=5.0),
                client.get(f"{self.forge_url}/api/v1/tasks", headers=headers, timeout=5.0),
                return_exceptions=True,
            )

            if not hasattr(r_analytics, "status_code") or not hasattr(r_tasks, "status_code") or r_analytics.status_code != 200 or r_tasks.status_code != 200:
                return {"reply": "Forge analytics/tasks query did not receive HTTP 200 from both endpoints.", "metadata": {"agent_id": "forge", "error": "one_or_more_status_endpoints_unavailable", "success": False}}

            ana_data = r_analytics.json()
            tasks_data = r_tasks.json()
            if not isinstance(ana_data, dict) or not isinstance(tasks_data, list):
                return {"reply": "Forge returned an unexpected analytics/tasks format.", "metadata": {"agent_id": "forge", "error": "unexpected_response_format", "success": False}}

            total = ana_data.get("total_tasks", len(tasks_data) if isinstance(tasks_data, list) else "not reported")
            completed = ana_data.get("completed_tasks", "not reported")
            active = ana_data.get("active_tasks", "not reported")
            rate = ana_data.get("success_rate_percentage", "not reported")
            avg_dur = ana_data.get("average_duration_seconds", "not reported")

            top_tasks = tasks_data[:2] if isinstance(tasks_data, list) else []
            task_summaries = []
            for t in top_tasks:
                task_summaries.append(f"• [{t.get('state', 'READY')}] {t.get('goal', 'Unnamed task')}")
            task_text = "\n".join(task_summaries) if task_summaries else "• No active task queues"

            formatted_reply = (
                f"🛠️ [FORGE STATUS RESPONSE]\n"
                f"Pipeline Success Rate: {rate}\n"
                f"Tasks Overview: Total: {total} | Completed: {completed} | Active: {active}\n"
                f"Average Task Duration: {avg_dur}\n\n"
                f"Current Task Queue:\n{task_text}"
                "\nThis was an analytics/status query; no code task was executed or verified."
            )
            return {
                "reply": formatted_reply,
                "metadata": {
                    "agent_id": "forge", "agent_name": "Forge",
                    "total_tasks": total, "completed": completed, "active": active,
                    "endpoint_response_received": True, "task_completion_verified": False,
                },
            }
        except Exception as e:
            return {
                "reply": f"🛠️ [FORGE SWE ENGINE] Error connecting to Forge local engine: {e}",
                "metadata": {"agent_id": "forge", "error": str(e)},
            }

    async def ask_sentinel(self, query: str) -> dict[str, Any]:
        """Queries the live Sentinel Zero-Trust Cybersecurity Shield."""
        headers = {"X-API-Key": self.sentinel_key, "Authorization": f"Bearer {self.sentinel_key}"}
        try:
            client = self.get_shared_client()
            r_posture, r_health = await asyncio.gather(
                client.get(f"{self.sentinel_url}/api/v1/friday/posture", headers=headers, timeout=5.0),
                client.get(f"{self.sentinel_url}/health", timeout=5.0),
                return_exceptions=True,
            )

            p_data = r_posture.json() if hasattr(r_posture, "status_code") and r_posture.status_code == 200 else {}
            h_data = r_health.json() if hasattr(r_health, "status_code") and r_health.status_code == 200 else {}

            score = p_data.get("overall_posture_score", "not reported")
            findings = p_data.get("open_findings_by_severity", {})
            domains = p_data.get("per_domain_scores", {})
            trend = p_data.get("trend")
            audit_valid = h_data.get("audit_chain_valid")

            formatted_reply = (
                f"🛡️ [SENTINEL STATUS RESPONSE]\n"
                f"Overall Posture Score: {score} | Trend: {trend if trend is not None else 'not reported'}\n"
                f"Audit Chain: {'valid' if audit_valid is True else ('invalid' if audit_valid is False else 'not reported')}\n\n"
                f"Domain Security Breakdown:\n"
                f"• Web Defense: {domains.get('web', 'not reported')} | API Security: {domains.get('api', 'not reported')}\n"
                f"• Network Surface: {domains.get('network', 'not reported')} | Cloud Infrastructure: {domains.get('cloud', 'not reported')}\n"
                f"• Open Vulnerabilities: {json.dumps(findings, ensure_ascii=False, default=str)}\n"
                "This was a status query; no security assessment was performed."
            )
            return {
                "reply": formatted_reply,
                "metadata": {
                    "agent_id": "sentinel", "agent_name": "Sentinel",
                    "posture_score": score, "audit_chain_valid": audit_valid,
                    "endpoint_response_received": True, "assessment_completed": False,
                },
            }
        except Exception as e:
            return {
                "reply": f"🛡️ [SENTINEL SHIELD] Error connecting to Sentinel cybersecurity shield: {e}",
                "metadata": {"agent_id": "sentinel", "error": str(e)},
            }

    async def get_fleet_summary(self) -> dict[str, Any]:
        """Generates a complete real-time status matrix across all 8 agents."""
        statuses = await self.get_all_statuses(force_refresh=True)
        online_count = sum(1 for s in statuses if s.status == "ONLINE")
        total_count = len(statuses)

        lines = [
            "🌐 [FRIDAY UNIVERSE // FLEET STATUS MATRIX]",
            f"Master Fleet Status: {online_count}/{total_count} AGENTS ACTIVE // OPERATOR: SURENDRA\n",
            f"{'AGENT':<12} | {'STATUS':<8} | {'PING':<8} | {'ROLE':<24}",
            "-" * 60,
        ]
        for s in statuses:
            lines.append(f"{s.icon} {s.name:<9} | {s.status:<8} | {s.latency_ms}ms{'':<3} | {s.role:<24}")

        lines.append("-" * 60)
        # This line used to be unconditional. The matrix above it said
        # "0/8 AGENTS ACTIVE" and the sentence underneath still claimed
        # "All microservices connected and synchronized with FRIDAY Central
        # Core." A status report whose summary contradicts its own table is
        # worse than no summary: the reader trusts the sentence.
        if online_count == total_count and total_count:
            lines.append("All microservices connected and synchronized with FRIDAY Central Core.")
        elif online_count == 0:
            lines.append(
                "No peer microservice answered from this machine. Nothing above was reached; the "
                "statuses are connection attempts, not confirmations."
            )
        else:
            lines.append(
                f"{online_count} of {total_count} microservices answered. Treat the UNREACHABLE rows "
                "as unverified, not as healthy."
            )

        return {
            "reply": "\n".join(lines),
            "metadata": {
                "fleet_status": "ACTIVE",
                "online_count": online_count,
                "total_count": total_count,
                "agents": [s.__dict__ for s in statuses],
            },
        }

    async def dispatch_directive(self, directive: str) -> dict[str, Any]:
        """Intelligently routes a natural language directive to the target specialist agent."""
        d = directive.lower().strip()

        if any(k in d for k in ["fleet", "all agents", "status matrix", "check all agents", "universe status"]):
            return await self.get_fleet_summary()
        elif any(k in d for k in ["trading", "trade", "stratex", "binance", "portfolio", "pnl", "cash", "crypto"]):
            return await self.ask_stratex(directive)
        elif any(k in d for k in ["security", "sentinel", "posture", "vulnerability", "threat", "audit", "cyber"]):
            return await self.ask_sentinel(directive)
        elif any(k in d for k in ["code", "forge", "software", "swe", "engineering", "tasks", "synthesize", "compile"]):
            return await self.ask_forge(directive)
        elif any(k in d for k in ["web", "cortex", "traffic", "leads", "crawler", "scraper", "growth"]):
            return await self.ask_cortex(directive)
        elif any(k in d for k in ["forecast", "predict", "futuris", "calibration", "brier", "probabilities"]):
            return await self.ask_futuris(directive)
        elif any(k in d for k in ["research", "intelx", "evidence", "contradiction", "sources", "claims"]):
            return await self.ask_intelx(directive)
        elif any(k in d for k in ["memory", "memora", "recall", "remember", "context"]):
            return await self.ask_memora(directive)
        else:
            return await self.ask_inference(directive)

    async def dispatch_task(self, envelope: TaskEnvelope) -> TaskResult:
        """Dispatches a structured TaskEnvelope to any peer agent in the FRIDAY Universe."""
        t0 = time.time()
        target = envelope.target_agent.lower().strip()
        client = self.get_shared_client()
        contract_endpoint_used = True

        try:
            if target == "inference":
                url = f"{self.inference_url}/v1/task/execute"
                headers = {"X-FRIDAY-API-Key": self.inference_key, "Content-Type": "application/json"}
                resp = await client.post(url, json=envelope.model_dump(), headers=headers, timeout=20.0)
                if resp.status_code == 404:
                    alt_url = f"{self.inference_url}/v1/agent/assist"
                    valid_task_types = {"code", "architecture", "security", "market", "debugging", "review"}
                    ttype = envelope.action if envelope.action in valid_task_types else "general"
                    alt_payload = {
                        "caller_agent": envelope.source_agent,
                        "task_type": ttype,
                        "prompt": str(envelope.payload.get("prompt", envelope.payload.get("question", str(envelope.payload)))),
                        "fast_lane": True,
                        "max_tokens": 120,
                    }
                    resp = await client.post(alt_url, json=alt_payload, headers=headers, timeout=20.0)

            elif target == "memora":
                url = f"{self.memora_url}/v1/task/execute"
                headers = {"Authorization": f"Bearer {self.memora_key}", "X-Agent-Name": envelope.source_agent, "Content-Type": "application/json"}
                resp = await client.post(url, json=envelope.model_dump(), headers=headers, timeout=10.0)
                if resp.status_code in (404, 405):
                    if envelope.action in ("store", "remember", "add"):
                        return TaskResult(
                            task_id=envelope.task_id,
                            target_agent=envelope.target_agent,
                            status=TaskStatus.BLOCKED,
                            error="Memora task endpoint is unavailable; refusing an unscoped legacy memory write.",
                            execution_time_ms=int((time.time() - t0) * 1000),
                        )
                    else:
                        contract_endpoint_used = False
                        alt_url = f"{self.memora_url}/v1/context"
                        alt_payload = {
                            "task_query": str(envelope.payload.get("query", envelope.payload.get("prompt", "context"))),
                            "token_budget": 1000,
                        }
                        resp = await client.post(alt_url, json=alt_payload, headers=headers, timeout=10.0)

            elif target == "stratex":
                url = f"{self.stratex_url}/v1/task/execute"
                headers = {"X-API-Key": self.stratex_key, "Authorization": f"Bearer {self.stratex_key}", "Content-Type": "application/json"}
                resp = await client.post(url, json=envelope.model_dump(), headers=headers, timeout=10.0)
                if resp.status_code in (404, 405):
                    contract_endpoint_used = False
                    alt_url = f"{self.stratex_url}/api/engine-health"
                    resp = await client.get(alt_url, headers=headers, timeout=10.0)

            elif target == "intelx":
                url = f"{self.intelx_url}/v1/task/execute"
                headers = {"Authorization": f"Bearer {self.intelx_key}", "Content-Type": "application/json"}
                resp = await client.post(url, json=envelope.model_dump(), headers=headers, timeout=15.0)
                if resp.status_code in (404, 405):
                    contract_endpoint_used = False
                    alt_url = f"{self.intelx_url}/api/v1/friday-universe/intelligence?agent={envelope.source_agent}&limit=5"
                    resp = await client.get(alt_url, headers=headers, timeout=15.0)

            elif target == "futuris":
                headers = {"X-API-Key": self.futuris_key, "Content-Type": "application/json"}
                try:
                    resp = await client.post(f"{self.futuris_local_url}/v1/task/execute", json=envelope.model_dump(), headers=headers, timeout=2.0)
                except Exception:
                    resp = await client.post(f"{self.futuris_url}/v1/task/execute", json=envelope.model_dump(), headers=headers, timeout=5.0)
                if resp.status_code in (404, 405):
                    contract_endpoint_used = False
                    try:
                        resp = await client.get(f"{self.futuris_local_url}/v1/friday/calibration", headers=headers, timeout=2.0)
                    except Exception:
                        resp = await client.get(f"{self.futuris_url}/v1/friday/calibration", headers=headers, timeout=5.0)

            elif target == "cortex":
                headers = {"X-Friday-Api-Key": self.cortex_key, "Content-Type": "application/json"}
                url = f"{self.cortex_url}/v1/task/execute"
                resp = await client.post(url, json=envelope.model_dump(), headers=headers, timeout=10.0)

            elif target == "forge":
                url = f"{self.forge_url}/api/v1/forge/delegate"
                headers = {"Authorization": f"Bearer {self.forge_key}", "Content-Type": "application/json"}
                resp = await client.post(url, json=envelope.model_dump(), headers=headers, timeout=15.0)

            elif target == "sentinel":
                url = f"{self.sentinel_url}/api/v1/friday/delegate"
                headers = {"X-API-Key": self.sentinel_key, "Authorization": f"Bearer {self.sentinel_key}", "Content-Type": "application/json"}
                sentinel_payload = envelope.model_dump()
                if sentinel_payload.get("capability") not in ("sentinel.security_assessment", "sentinel.reconnaissance", "sentinel.incident_investigation"):
                    sentinel_payload["capability"] = "sentinel.security_assessment"
                resp = await client.post(url, json=sentinel_payload, headers=headers, timeout=10.0)

            else:
                lat = int((time.time() - t0) * 1000)
                return TaskResult(
                    task_id=envelope.task_id,
                    target_agent=envelope.target_agent,
                    status=TaskStatus.ERROR,
                    error=f"Unknown target agent '{target}'",
                    execution_time_ms=lat,
                )

            lat = int((time.time() - t0) * 1000)
            if resp.status_code in (200, 201, 202):
                res_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"text": resp.text}
                if resp.status_code == 202:
                    pending_task_id = (
                        str(res_data.get("task_id") or envelope.task_id)
                        if isinstance(res_data, dict)
                        else envelope.task_id
                    )
                    return TaskResult(
                        task_id=pending_task_id,
                        target_agent=envelope.target_agent,
                        status=TaskStatus.PENDING,
                        result=res_data if isinstance(res_data, dict) else {"data": res_data},
                        summary=f"{target} accepted the request; completion is pending verification.",
                        execution_time_ms=lat,
                    )
                if not contract_endpoint_used:
                    return TaskResult(
                        task_id=envelope.task_id,
                        target_agent=envelope.target_agent,
                        status=TaskStatus.DEGRADED,
                        result=res_data if isinstance(res_data, dict) else {"data": res_data},
                        summary=f"A legacy status/context endpoint responded for {target}; task execution was not confirmed.",
                        error="task_completion_unverified",
                        execution_time_ms=lat,
                    )
                state = str(res_data.get("state", res_data.get("status", ""))).strip().lower() if isinstance(res_data, dict) else ""
                result_data = res_data if isinstance(res_data, dict) else {"data": res_data}
                returned_task_id = str(result_data.get("task_id") or envelope.task_id)
                if state in {"pending", "queued", "running", "waiting_approval", "awaiting_approval", "accepted"}:
                    return TaskResult(
                        task_id=returned_task_id,
                        target_agent=envelope.target_agent,
                        status=TaskStatus.PENDING,
                        result=result_data,
                        summary=f"{target} accepted the request; completion is pending verification.",
                        execution_time_ms=lat,
                    )

                raw_receipt = result_data.get("receipt")
                receipt: ActionReceipt | None = None
                if isinstance(raw_receipt, dict):
                    try:
                        receipt = ActionReceipt(**raw_receipt)
                    except Exception:
                        receipt = None

                # A status string or model answer is not a completion receipt.
                # Use the same strict verifier as the receipt-aware peer mesh.
                from friday.cognition.mesh import verify_receipt

                candidate_status = {
                    "error": TaskStatus.ERROR,
                    "failed": TaskStatus.ERROR,
                    "failure": TaskStatus.ERROR,
                    "blocked": TaskStatus.BLOCKED,
                    "cancelled": TaskStatus.CANCELLED,
                    "degraded": TaskStatus.DEGRADED,
                }.get(state, TaskStatus.SUCCESS)
                candidate = TaskResult(
                    task_id=returned_task_id,
                    target_agent=envelope.target_agent,
                    status=candidate_status,
                    result=result_data.get("result", {}) if isinstance(result_data.get("result"), dict) else {},
                    summary=str(result_data.get("summary") or result_data.get("message") or ""),
                    receipt=receipt,
                    execution_time_ms=lat,
                )
                verdict = verify_receipt(envelope, candidate)
                if verdict.ok:
                    result_status = TaskStatus.SUCCESS
                    summary = candidate.summary or f"Task '{envelope.action}' completed by {target} in {lat}ms."
                    error = None
                else:
                    result_status = TaskStatus.DEGRADED
                    summary = f"{target} responded, but task completion is unverified: {verdict.reason}."
                    error = "task_completion_unverified"

                return TaskResult(
                    task_id=returned_task_id,
                    target_agent=envelope.target_agent,
                    status=result_status,
                    result=result_data,
                    summary=summary,
                    error=error,
                    execution_time_ms=lat,
                    receipt=receipt,
                )
            else:
                return TaskResult(
                    task_id=envelope.task_id,
                    target_agent=envelope.target_agent,
                    status=TaskStatus.ERROR,
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    execution_time_ms=lat,
                )

        except Exception as e:
            lat = int((time.time() - t0) * 1000)
            return TaskResult(
                task_id=envelope.task_id,
                target_agent=envelope.target_agent,
                status=TaskStatus.ERROR,
                error=str(e),
                execution_time_ms=lat,
            )


# Global singleton instance
fleet_client = FleetClient()
