"""Specialist Dispatch Bus for FRIDAY Universe Mesh.

Orchestrates structured TaskEnvelopes to all 9 specialist agents:
- Cortex    (http://cortex:8000)
- Forge     (http://forge:8000)
- Futuris   (http://futuris:8000)
- Inference (http://inference:8000)
- IntelX    (http://intelx:8000)
- Memora    (http://memora:8000)
- Sentinel  (http://sentinel:8000)
- Stratex   (http://stratex:8000)
- VyralX    (http://vyralx:8000)

Enforces FRIDAY Core Architectural Invariants:
1. Non-Bypassable Gates: CANNOT override Stratex risk limits, Sentinel security vetoes, or Forge sandbox boundaries.
2. Decoupled Long-Term Memory: Active task checkpoints are short-lived; durable memories must be committed to Memora.
3. Desktop Native Boundary: Win32 APIs, UI automation, and desktop audio run natively on Windows 11 only.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from typing import Any

import httpx

from friday.core.exceptions import SecurityError
from friday.core.logging import get_logger
from friday.core.resilience import AsyncCircuitBreaker, CircuitBreakerOpenError
from friday.core.task_envelope import (
    ActionReceipt,
    TaskEnvelope,
    TaskPriority,
    TaskResult,
    TaskStatus,
)

logger = get_logger("agent.router")

TIMEOUT_CEILING_SECONDS = 30.0

SPECIALIST_CONFIGS: dict[str, dict[str, Any]] = {
    "cortex": {
        "default_url": "http://cortex:8000",
        "env_var": "CORTEX_URL",
        "role": "Cognitive Reasoning & Web Operations",
        "keywords": ["browse", "scrape", "scraping", "crawl", "crawler", "extract", "traffic", "leads"],
    },
    "forge": {
        "default_url": "http://forge:8000",
        "env_var": "FORGE_URL",
        "role": "Code Synthesis & Execution Sandbox",
        "keywords": ["code", "build", "compile", "sandbox", "git", "patch", "software", "devops", "test"],
    },
    "futuris": {
        "default_url": "http://futuris:8000",
        "env_var": "FUTURIS_URL",
        "role": "Predictive Modeling & Forecasting",
        "keywords": ["forecast", "predict", "probability", "brier", "likelihood", "future_trend", "odds"],
    },
    "inference": {
        "default_url": "http://inference:8000",
        "env_var": "INFERENCE_URL",
        "role": "LLM Routing & Consensus Gateway",
        "keywords": ["llm", "reason", "think", "model", "prompt", "consensus", "generate", "chat"],
    },
    "intelx": {
        "default_url": "http://intelx:8000",
        "env_var": "INTELX_URL",
        "role": "Search & Live OSINT Intelligence",
        "keywords": ["search", "research", "intel", "news", "osint", "investigate", "macro", "sources"],
    },
    "memora": {
        "default_url": "http://memora:8000",
        "env_var": "MEMORA_URL",
        "role": "Universal Episodic Memory & Vector Recall",
        "keywords": ["memory", "recall", "remember", "vector", "episodic", "store_memory", "checkpoint"],
    },
    "sentinel": {
        "default_url": "http://sentinel:8000",
        "env_var": "SENTINEL_URL",
        "role": "Security Audit & Cryptographic Watchdog",
        "keywords": ["security", "audit", "veto", "firewall", "vulnerability", "auth", "threat", "protect"],
    },
    "stratex": {
        "default_url": "http://stratex:8000",
        "env_var": "STRATEX_URL",
        "role": "24/7 Algorithmic Trading Platform",
        "keywords": ["trade", "trading", "crypto", "futures", "position", "pnl", "order", "market", "risk"],
    },
    "vyralx": {
        "default_url": "http://vyralx:8000",
        "env_var": "VYRALX_URL",
        "role": "Video Production & Governed Distribution",
        "keywords": ["video", "youtube", "render_video", "media", "upload", "thumbnail", "shorts"],
    },
}


def _is_truthy(val: Any) -> bool:
    """Check if value represents a truthy flag (bool True, 1, 'true', 'yes')."""
    if val is True:
        return True
    if isinstance(val, (str, int)):
        return str(val).strip().lower() in ("true", "1", "yes")
    return False


class SafetyGateViolationError(SecurityError):
    """Raised when an envelope attempts to bypass non-bypassable specialist security boundaries."""
    pass


class SpecialistRouter:
    """Central router dispatching TaskEnvelopes to all 9 specialist agents across friday_mesh."""

    def __init__(
        self,
        timeout_ceiling: float = TIMEOUT_CEILING_SECONDS,
        max_retries: int = 3,
        circuit_failure_threshold: int = 3,
        circuit_recovery_seconds: float = 30.0,
    ) -> None:
        self.timeout_ceiling = min(timeout_ceiling, TIMEOUT_CEILING_SECONDS)
        self.max_retries = max(1, max_retries)
        self.breakers: dict[str, AsyncCircuitBreaker] = {}
        for agent_id in SPECIALIST_CONFIGS:
            self.breakers[agent_id] = AsyncCircuitBreaker(
                service_name=agent_id,
                failure_threshold=circuit_failure_threshold,
                recovery_time_seconds=circuit_recovery_seconds,
            )

    def get_agent_url(self, agent_id: str) -> str:
        """Resolve normalized HTTP endpoint for the target specialist agent."""
        norm_id = agent_id.lower().strip()
        cfg = SPECIALIST_CONFIGS.get(norm_id)
        if not cfg:
            return f"http://{norm_id}:8000"

        env_var = cfg["env_var"]
        raw_url = os.getenv(env_var) or os.getenv(f"FRIDAY_{env_var}") or cfg["default_url"]

        # Eradicate dead Render URLs
        if "onrender.com" in raw_url:
            raw_url = cfg["default_url"]

        # Modernize Stratex legacy port 5000 -> 8000
        if "stratex:5000" in raw_url:
            raw_url = raw_url.replace(":5000", ":8000")

        return raw_url.rstrip("/")

    def validate_invariants(self, envelope: TaskEnvelope) -> None:
        """Enforce strict non-bypassable architectural safety invariants."""
        target = (envelope.target_agent or "").lower().strip()
        inputs = envelope.inputs or envelope.payload or {}

        # --- SAFETY INVARIANT 1: NON-BYPASSABLE SPECIALIST GATES ---
        # Stratex Risk Limits
        if target == "stratex":
            forbidden_stratex_keys = {
                "bypass_risk_limits",
                "override_risk",
                "disable_risk",
                "unlimited_risk",
                "force_trade_without_risk_check",
                "disable_drawdown_limit",
            }
            if any(_is_truthy(inputs.get(k)) for k in forbidden_stratex_keys):
                raise SafetyGateViolationError(
                    "Safety Invariant 1 Violation: FRIDAY Core CANNOT override Stratex risk limits."
                )

        # Sentinel Security Vetoes (Evaluated across all mesh targets)
        forbidden_sentinel_keys = {
            "skip_sentinel",
            "override_security",
            "bypass_sentinel",
            "bypass_security_veto",
            "disable_audit",
        }
        if any(_is_truthy(inputs.get(k)) for k in forbidden_sentinel_keys):
            raise SafetyGateViolationError(
                "Safety Invariant 1 Violation: FRIDAY Core CANNOT bypass Sentinel security vetoes."
            )

        # Forge Sandbox Boundaries
        if target == "forge":
            forbidden_forge_keys = {
                "escape_sandbox",
                "no_sandbox",
                "disable_sandbox",
                "disable_isolation",
                "run_root",
                "host_root",
                "host_filesystem_access",
            }
            if any(_is_truthy(inputs.get(k)) for k in forbidden_forge_keys):
                raise SafetyGateViolationError(
                    "Safety Invariant 1 Violation: FRIDAY Core CANNOT breach Forge sandbox boundaries."
                )

        # --- SAFETY INVARIANT 3: DESKTOP NATIVE BOUNDARY ---
        # Container specialists cannot execute Win32 native APIs
        if target in SPECIALIST_CONFIGS:
            desktop_win32_keys = {
                "win32_api",
                "pywinauto_action",
                "direct_win32_window",
                "native_windows_audio_hook",
            }
            if any(_is_truthy(inputs.get(k)) for k in desktop_win32_keys):
                raise SafetyGateViolationError(
                    f"Safety Invariant 3 Violation: Win32 native operations cannot be executed inside "
                    f"Linux container peer '{target}'. Win32 APIs run natively on Windows 11 host."
                )

    def resolve_target_agent(self, directive_or_capability: str) -> str:
        """Resolve appropriate specialist agent based on directive or capability match."""
        import re
        text = directive_or_capability.lower()
        for agent_id in SPECIALIST_CONFIGS:
            if re.search(rf"\b{agent_id}\b", text):
                return agent_id
        for agent_id, cfg in SPECIALIST_CONFIGS.items():
            for kw in cfg["keywords"]:
                if re.search(rf"\b{re.escape(kw)}\b", text):
                    return agent_id
        return "inference"

    async def commit_durable_memory_to_memora(self, memory_payload: dict[str, Any]) -> TaskResult:
        """Commit long-term durable memory to Memora via REST API (Safety Invariant 2)."""
        envelope = TaskEnvelope(
            target_agent="memora",
            action="store_memory",
            objective="Commit durable long-term memory to Memora cloud vector fabric",
            inputs=memory_payload,
        )
        return await self.dispatch_envelope(envelope)

    async def dispatch_envelope(
        self,
        envelope: TaskEnvelope,
        custom_endpoint: str | None = None,
    ) -> TaskResult:
        """Dispatch a TaskEnvelope across the mesh with circuit breakers, timeouts, and backoff."""
        start_time = time.monotonic()
        target = (envelope.target_agent or "inference").lower().strip()

        # Enforce non-bypassable invariants before network dispatch
        try:
            self.validate_invariants(envelope)
        except SafetyGateViolationError as s_err:
            logger.warning("Rejected task dispatch: %s", s_err)
            return TaskResult(
                task_id=envelope.task_id,
                target_agent=target,
                status=TaskStatus.BLOCKED,
                error=str(s_err),
                summary=f"Task blocked by safety gate: {s_err}",
                execution_time_ms=int((time.monotonic() - start_time) * 1000),
                receipt=ActionReceipt(
                    requested_action=envelope.action or envelope.objective,
                    target=target,
                    authorization_decision="REJECTED",
                    failure_reason=str(s_err),
                ),
            )

        breaker = self.breakers.get(target)
        if breaker and not await breaker.can_execute():
            err_msg = f"Circuit breaker for specialist '{target}' is OPEN. Call rejected."
            logger.warning(err_msg)
            return TaskResult(
                task_id=envelope.task_id,
                target_agent=target,
                status=TaskStatus.DEGRADED,
                error=err_msg,
                summary=f"Degraded: specialist '{target}' temporarily unavailable (circuit OPEN).",
                execution_time_ms=int((time.monotonic() - start_time) * 1000),
            )

        base_url = custom_endpoint or self.get_agent_url(target)
        endpoint = f"{base_url}/v1/tasks" if not custom_endpoint else custom_endpoint
        headers = {
            "Content-Type": "application/json",
            "X-Source-Agent": "friday",
            "X-Target-Agent": target,
            "X-Trace-Id": envelope.trace_id,
            "X-Request-Id": envelope.request_id or "",
        }

        payload = envelope.model_dump()
        last_exception: Exception | None = None

        # Execute HTTP dispatch with bounded retries and exponential backoff
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_ceiling) as client:
                    resp = await client.post(endpoint, json=payload, headers=headers)
                    resp.raise_for_status()

                    data = resp.json()
                    if breaker:
                        await breaker.record_success()

                    exec_ms = int((time.monotonic() - start_time) * 1000)
                    result_data = data.get("result", data)
                    return TaskResult(
                        task_id=envelope.task_id,
                        target_agent=target,
                        status=TaskStatus.SUCCESS,
                        result=result_data if isinstance(result_data, dict) else {"data": result_data},
                        summary=data.get("summary", f"Successfully completed by {target}"),
                        execution_time_ms=exec_ms,
                        receipt=ActionReceipt(
                            requested_action=envelope.action or envelope.objective,
                            target=target,
                            authorization_decision="AUTHORIZED",
                            result=result_data if isinstance(result_data, dict) else {},
                        ),
                    )

            except httpx.HTTPStatusError as h_err:
                last_exception = h_err
                status_code = h_err.response.status_code
                if status_code in (400, 401, 403, 422):
                    # Client errors are not retried
                    break
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as net_err:
                last_exception = net_err

            # Backoff before retry
            if attempt < self.max_retries:
                delay = min(2.0, 0.2 * (2 ** (attempt - 1))) * (0.5 + random.random() * 0.5)
                await asyncio.sleep(delay)

        # Record breaker failure on exhaustion
        if breaker:
            await breaker.record_failure(last_exception)

        exec_ms = int((time.monotonic() - start_time) * 1000)
        err_detail = f"{type(last_exception).__name__}: {last_exception}" if last_exception else "Unknown failure"
        logger.error("Dispatch to specialist '%s' failed after %d attempts: %s", target, self.max_retries, err_detail)

        return TaskResult(
            task_id=envelope.task_id,
            target_agent=target,
            status=TaskStatus.DEGRADED,
            error=err_detail,
            summary=f"Degraded: specialist '{target}' failed to respond. Handled cleanly.",
            execution_time_ms=exec_ms,
            receipt=ActionReceipt(
                requested_action=envelope.action or envelope.objective,
                target=target,
                authorization_decision="AUTHORIZED",
                failure_reason=err_detail,
            ),
        )


# Global singleton instance
specialist_router = SpecialistRouter()
