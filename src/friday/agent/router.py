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
import json
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from friday.agent.execution_trace import (
    ExecutionTraceCheckpoint,
    ExecutionTraceStore,
    trace_store,
)
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
        "canonical_mesh_url": "http://10.0.0.120:8009",
        "env_var": "CORTEX_URL",
        "role": "Cognitive Reasoning & Web Operations",
        "keywords": ["browse", "scrape", "scraping", "crawl", "crawler", "extract", "traffic", "leads"],
    },
    "forge": {
        "default_url": "http://forge:8000",
        "canonical_mesh_url": "http://10.0.0.121:8006",
        "env_var": "FORGE_URL",
        "role": "Code Synthesis & Execution Sandbox",
        "keywords": ["code", "build", "compile", "sandbox", "git", "patch", "software", "devops", "test"],
    },
    "futuris": {
        "default_url": "http://futuris:8000",
        "canonical_mesh_url": "http://10.0.0.121:8004",
        "env_var": "FUTURIS_URL",
        "role": "Predictive Modeling & Forecasting",
        "keywords": ["forecast", "predict", "probability", "brier", "likelihood", "future_trend", "odds"],
    },
    "inference": {
        "default_url": "http://inference:8000",
        "canonical_mesh_url": "http://10.0.0.121:8001",
        "env_var": "INFERENCE_URL",
        "role": "LLM Routing & Consensus Gateway",
        "keywords": ["llm", "reason", "think", "model", "prompt", "consensus", "generate", "chat"],
    },
    "intelx": {
        "default_url": "http://intelx:8000",
        "canonical_mesh_url": "http://10.0.0.121:8005",
        "env_var": "INTELX_URL",
        "role": "Search & Live OSINT Intelligence",
        "keywords": ["search", "research", "intel", "news", "osint", "investigate", "macro", "sources"],
    },
    "memora": {
        "default_url": "http://memora:8000",
        "canonical_mesh_url": "http://10.0.0.121:8002",
        "env_var": "MEMORA_URL",
        "role": "Universal Episodic Memory & Vector Recall",
        "keywords": ["memory", "recall", "remember", "vector", "episodic", "store_memory", "checkpoint"],
    },
    "sentinel": {
        "default_url": "http://sentinel:8000",
        "canonical_mesh_url": "http://10.0.0.120:8008",
        "env_var": "SENTINEL_URL",
        "role": "Security Audit & Cryptographic Watchdog",
        "keywords": ["security", "audit", "veto", "firewall", "vulnerability", "auth", "threat", "protect"],
    },
    "stratex": {
        "default_url": "http://stratex:8000",
        "canonical_mesh_url": "http://10.0.0.121:8003",
        "env_var": "STRATEX_URL",
        "role": "24/7 Algorithmic Trading Platform",
        "keywords": ["trade", "trading", "crypto", "futures", "position", "pnl", "order", "market", "risk"],
    },
    "vyralx": {
        "default_url": "http://vyralx:8000",
        "canonical_mesh_url": "http://10.0.0.120:8010",
        "env_var": "VYRALX_URL",
        "role": "Autonomous Video Production & Governed Distribution",
        "keywords": [
            "video",
            "youtube",
            "render_video",
            "media",
            "upload",
            "thumbnail",
            "shorts",
            "script",
            "voiceover",
            "pexels",
            "render",
            "vyralx",
        ],
    },
}


def _is_truthy(val: Any) -> bool:
    """Check if value represents a truthy flag (bool True, 1, 'true', 'yes')."""
    if val is True:
        return True
    if isinstance(val, (str, int)):
        return str(val).strip().lower() in ("true", "1", "yes")
    return False


def compute_backoff_jitter(
    attempt: int,
    base_seconds: float = 0.25,
    cap_seconds: float = 4.0,
    strategy: str = "full",
    prev_delay: float = 0.25,
) -> float:
    """Compute exponential backoff delay with dynamic jitter per AWS architecture guidelines.
    
    Strategies:
    - full: random.uniform(0.0, min(cap, base * 2 ** (attempt - 1)))
    - equal: half deterministic + half jitter
    - decorrelated: random.uniform(base, prev_delay * 3.0)
    """
    attempt = max(1, attempt)
    exp_delay = min(cap_seconds, base_seconds * (2 ** (attempt - 1)))

    if strategy == "equal":
        half = exp_delay / 2.0
        return half + random.uniform(0.0, half)
    elif strategy == "decorrelated":
        return min(cap_seconds, random.uniform(base_seconds, prev_delay * 3.0))
    else:
        # Default: Full Jitter
        return random.uniform(0.0, exp_delay)


def parse_retry_after(response: Optional[httpx.Response], default: float = 1.0) -> float:
    """Extract and parse Retry-After header if present on HTTP 429 / 503."""
    if not response or "retry-after" not in response.headers:
        return default
    raw = response.headers["retry-after"].strip()
    try:
        val = float(raw)
        return max(0.1, min(val, 10.0))
    except ValueError:
        return default


class SafetyGateViolationError(SecurityError):
    """Raised when an envelope attempts to bypass non-bypassable specialist security boundaries."""
    pass


@dataclass(frozen=True)
class ConsensusVote:
    """Individual vote and response telemetry from an agent during consensus routing."""
    agent: str
    decision: str
    confidence: float
    response_summary: str
    latency_ms: int
    status: TaskStatus
    raw_result: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass(frozen=True)
class ConsensusResult:
    """Aggregated result of multi-agent consensus routing."""
    task_id: str
    trace_id: str
    action: str
    consensus_reached: bool
    consensus_status: str  # "ACHIEVED", "DIVERGENT", "PARTIAL_QUORUM", "FAILED"
    winning_decision: Optional[str]
    agreement_ratio: float
    quorum_count: int
    total_participants: int
    votes: list[ConsensusVote]
    synthesized_output: dict[str, Any]
    execution_time_ms: int
    divergence_breakdown: dict[str, int] = field(default_factory=dict)
    trace_checkpoint: Optional[ExecutionTraceCheckpoint] = None


class SpecialistRouter:
    """Central router dispatching TaskEnvelopes to all 9 specialist agents across friday_mesh."""

    def __init__(
        self,
        timeout_ceiling: float = TIMEOUT_CEILING_SECONDS,
        max_retries: int = 3,
        circuit_failure_threshold: int = 3,
        circuit_recovery_seconds: float = 30.0,
        trace_storage: Optional[ExecutionTraceStore] = None,
        jitter_strategy: str = "full",
    ) -> None:
        self.timeout_ceiling = min(timeout_ceiling, TIMEOUT_CEILING_SECONDS)
        self.max_retries = max(1, max_retries)
        self.jitter_strategy = jitter_strategy
        self.trace_store = trace_storage or trace_store
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
        env_val = (os.getenv(env_var) or os.getenv(f"FRIDAY_{env_var}") or "").strip()
        is_prod = (os.getenv("ENVIRONMENT") or os.getenv("FRIDAY_ENV") or "").lower() == "production"

        if env_val:
            raw_url = env_val
        elif is_prod and "canonical_mesh_url" in cfg:
            raw_url = cfg["canonical_mesh_url"]
        else:
            raw_url = cfg["default_url"]

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

        # VyralX Approval-Governed Publishing Boundaries
        if target == "vyralx":
            forbidden_vyralx_keys = {
                "bypass_approval",
                "direct_upload",
                "skip_human_approval",
                "auto_publish",
                "force_publish_without_review",
                "publish_now",
            }
            if any(_is_truthy(inputs.get(k)) for k in forbidden_vyralx_keys):
                raise SafetyGateViolationError(
                    "Safety Invariant 1 Violation: FRIDAY Core CANNOT bypass VyralX human approval governance for video publishing."
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
        """Dispatch a TaskEnvelope across the mesh with circuit breakers, timeouts, and backoff with dynamic jitter."""
        start_time = time.monotonic()
        target = (envelope.target_agent or "inference").lower().strip()
        action_name = envelope.action or envelope.objective or "task_dispatch"
        payload_summary = str(envelope.inputs or envelope.payload or {})[:500]

        # Enforce non-bypassable invariants before network dispatch
        try:
            self.validate_invariants(envelope)
        except SafetyGateViolationError as s_err:
            logger.warning("Rejected task dispatch: %s", s_err)
            exec_ms = int((time.monotonic() - start_time) * 1000)
            receipt = ActionReceipt(
                requested_action=action_name,
                target=target,
                authorization_decision="REJECTED",
                failure_reason=str(s_err),
            )
            # Persist blocked execution checkpoint
            if self.trace_store:
                self.trace_store.record_checkpoint(
                    ExecutionTraceCheckpoint(
                        trace_id=envelope.trace_id,
                        task_id=envelope.task_id,
                        target_agent=target,
                        action=action_name,
                        status=TaskStatus.BLOCKED.value,
                        consensus_status="NONE",
                        participating_agents=[target],
                        agreement_ratio=0.0,
                        latency_ms=exec_ms,
                        retry_count=0,
                        payload_summary=payload_summary,
                        result_summary="Blocked by safety invariant gate",
                        error=str(s_err),
                        receipt_json=json.dumps(receipt.model_dump()),
                    )
                )
            return TaskResult(
                task_id=envelope.task_id,
                target_agent=target,
                status=TaskStatus.BLOCKED,
                error=str(s_err),
                summary=f"Task blocked by safety gate: {s_err}",
                execution_time_ms=exec_ms,
                receipt=receipt,
            )

        breaker = self.breakers.get(target)
        if breaker and not await breaker.can_execute():
            err_msg = f"Circuit breaker for specialist '{target}' is OPEN. Call rejected."
            logger.warning(err_msg)
            exec_ms = int((time.monotonic() - start_time) * 1000)
            if self.trace_store:
                self.trace_store.record_checkpoint(
                    ExecutionTraceCheckpoint(
                        trace_id=envelope.trace_id,
                        task_id=envelope.task_id,
                        target_agent=target,
                        action=action_name,
                        status=TaskStatus.DEGRADED.value,
                        consensus_status="NONE",
                        participating_agents=[target],
                        agreement_ratio=0.0,
                        latency_ms=exec_ms,
                        retry_count=0,
                        payload_summary=payload_summary,
                        result_summary="Circuit breaker OPEN",
                        error=err_msg,
                    )
                )
            return TaskResult(
                task_id=envelope.task_id,
                target_agent=target,
                status=TaskStatus.DEGRADED,
                error=err_msg,
                summary=f"Degraded: specialist '{target}' temporarily unavailable (circuit OPEN).",
                execution_time_ms=exec_ms,
            )

        base_url = custom_endpoint or self.get_agent_url(target)
        if custom_endpoint:
            endpoint = custom_endpoint
        elif target == "vyralx":
            endpoint = f"{base_url}/api/v1/tasks"
        elif target == "forge":
            endpoint = f"{base_url}/api/v1/forge/delegate"
        elif target == "sentinel":
            endpoint = f"{base_url}/api/v1/friday/delegate"
        else:
            endpoint = f"{base_url}/v1/tasks"

        headers = {
            "Content-Type": "application/json",
            "X-Source-Agent": "friday",
            "X-Target-Agent": target,
            "X-Trace-Id": envelope.trace_id,
            "X-Request-Id": envelope.request_id or "",
        }
        if target == "vyralx":
            vyralx_key = os.getenv("FRIDAY_VYRALX_API_KEY") or os.getenv("VYRALX_API_KEY", "")
            if vyralx_key:
                headers["X-API-Key"] = vyralx_key
                headers["Authorization"] = f"Bearer {vyralx_key}"

        payload = envelope.model_dump()
        last_exception: Exception | None = None
        retries_used = 0
        last_delay = 0.25

        # Execute HTTP dispatch with bounded retries and exponential backoff with dynamic jitter
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
                    res_status = TaskStatus.PENDING if resp.status_code == 202 else TaskStatus.SUCCESS
                    summary = data.get("summary", f"Successfully completed by {target}")
                    receipt = ActionReceipt(
                        requested_action=action_name,
                        target=target,
                        authorization_decision="AUTHORIZED",
                        result=result_data if isinstance(result_data, dict) else {},
                    )

                    # Persist trace checkpoint
                    if self.trace_store:
                        self.trace_store.record_checkpoint(
                            ExecutionTraceCheckpoint(
                                trace_id=envelope.trace_id,
                                task_id=envelope.task_id,
                                target_agent=target,
                                action=action_name,
                                status=res_status.value,
                                consensus_status="NONE",
                                participating_agents=[target],
                                agreement_ratio=1.0,
                                latency_ms=exec_ms,
                                retry_count=retries_used,
                                payload_summary=payload_summary,
                                result_summary=str(summary)[:500],
                                receipt_json=json.dumps(receipt.model_dump()),
                            )
                        )

                    return TaskResult(
                        task_id=envelope.task_id,
                        target_agent=target,
                        status=res_status,
                        result=result_data if isinstance(result_data, dict) else {"data": result_data},
                        summary=summary,
                        execution_time_ms=exec_ms,
                        receipt=receipt,
                    )

            except httpx.HTTPStatusError as h_err:
                last_exception = h_err
                status_code = h_err.response.status_code
                if status_code == 429:
                    # Rate-limited: check Retry-After header
                    retry_after = parse_retry_after(h_err.response, default=1.0)
                    delay = retry_after + compute_backoff_jitter(
                        attempt,
                        strategy=self.jitter_strategy,
                        prev_delay=last_delay,
                    )
                elif status_code in (400, 401, 403, 422):
                    # Client errors are not retried
                    break
                else:
                    delay = compute_backoff_jitter(
                        attempt,
                        strategy=self.jitter_strategy,
                        prev_delay=last_delay,
                    )
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as net_err:
                last_exception = net_err
                delay = compute_backoff_jitter(
                    attempt,
                    strategy=self.jitter_strategy,
                    prev_delay=last_delay,
                )

            # Backoff before retry with jitter
            if attempt < self.max_retries:
                retries_used += 1
                last_delay = delay
                await asyncio.sleep(delay)

        # Record breaker failure on exhaustion
        if breaker:
            await breaker.record_failure(last_exception)

        exec_ms = int((time.monotonic() - start_time) * 1000)
        err_detail = f"{type(last_exception).__name__}: {last_exception}" if last_exception else "Unknown failure"
        logger.error("Dispatch to specialist '%s' failed after %d attempts: %s", target, self.max_retries, err_detail)

        receipt = ActionReceipt(
            requested_action=action_name,
            target=target,
            authorization_decision="AUTHORIZED",
            failure_reason=err_detail,
        )

        if self.trace_store:
            self.trace_store.record_checkpoint(
                ExecutionTraceCheckpoint(
                    trace_id=envelope.trace_id,
                    task_id=envelope.task_id,
                    target_agent=target,
                    action=action_name,
                    status=TaskStatus.DEGRADED.value,
                    consensus_status="NONE",
                    participating_agents=[target],
                    agreement_ratio=0.0,
                    latency_ms=exec_ms,
                    retry_count=retries_used,
                    payload_summary=payload_summary,
                    result_summary=f"Degraded: {err_detail}",
                    error=err_detail,
                    receipt_json=json.dumps(receipt.model_dump()),
                )
            )

        return TaskResult(
            task_id=envelope.task_id,
            target_agent=target,
            status=TaskStatus.DEGRADED,
            error=err_detail,
            summary=f"Degraded: specialist '{target}' failed to respond. Handled cleanly.",
            execution_time_ms=exec_ms,
            receipt=receipt,
        )

    async def dispatch_consensus(
        self,
        envelope: TaskEnvelope,
        agents: Optional[list[str]] = None,
        quorum_threshold: float = 0.5,
        min_quorum: int = 2,
        strategy: str = "majority",
    ) -> ConsensusResult:
        """Route task across multiple specialist agents concurrently and evaluate consensus agreement.
        
        Args:
            envelope: TaskEnvelope to dispatch.
            agents: List of specialist agent identifiers (defaults to ['inference', 'cortex', 'futuris']).
            quorum_threshold: Minimum agreement ratio for consensus (e.g. 0.5 for majority, 1.0 for unanimous).
            min_quorum: Minimum number of successful responding agents required to form a quorum.
            strategy: 'majority', 'unanimous', or 'weighted'.
        """
        start_time = time.monotonic()
        target_panel = [a.lower().strip() for a in (agents or ["inference", "cortex", "futuris"])]
        action_name = envelope.action or envelope.objective or "consensus_evaluation"
        payload_summary = str(envelope.inputs or envelope.payload or {})[:500]

        # 1. Pre-flight Safety Gate: Check all targets for invariant violations
        for agent_id in target_panel:
            test_envelope = envelope.model_copy(update={"target_agent": agent_id})
            try:
                self.validate_invariants(test_envelope)
            except SafetyGateViolationError as s_err:
                exec_ms = int((time.monotonic() - start_time) * 1000)
                logger.warning("Consensus dispatch blocked by invariant check on %s: %s", agent_id, s_err)
                cp = None
                if self.trace_store:
                    cp = self.trace_store.record_checkpoint(
                        ExecutionTraceCheckpoint(
                            trace_id=envelope.trace_id,
                            task_id=envelope.task_id,
                            target_agent="consensus",
                            action=action_name,
                            status=TaskStatus.BLOCKED.value,
                            consensus_status="FAILED",
                            participating_agents=target_panel,
                            agreement_ratio=0.0,
                            latency_ms=exec_ms,
                            payload_summary=payload_summary,
                            error=str(s_err),
                        )
                    )
                return ConsensusResult(
                    task_id=envelope.task_id,
                    trace_id=envelope.trace_id,
                    action=action_name,
                    consensus_reached=False,
                    consensus_status="FAILED",
                    winning_decision=None,
                    agreement_ratio=0.0,
                    quorum_count=0,
                    total_participants=len(target_panel),
                    votes=[],
                    synthesized_output={"error": f"Consensus blocked on agent '{agent_id}': {s_err}"},
                    execution_time_ms=exec_ms,
                    trace_checkpoint=cp,
                )

        # 2. Concurrently dispatch to all panel agents
        async def _dispatch_single(agent_id: str) -> ConsensusVote:
            v_start = time.monotonic()
            child_env = envelope.model_copy(update={"target_agent": agent_id})
            try:
                res = await self.dispatch_envelope(child_env)
                latency = int((time.monotonic() - v_start) * 1000)
                raw = res.result or {}
                # Extract decision from result
                decision = str(
                    raw.get("decision")
                    or raw.get("choice")
                    or raw.get("answer")
                    or raw.get("recommendation")
                    or raw.get("status")
                    or res.summary
                ).strip()
                confidence = float(raw.get("confidence", 1.0))
                return ConsensusVote(
                    agent=agent_id,
                    decision=decision,
                    confidence=confidence,
                    response_summary=res.summary,
                    latency_ms=latency,
                    status=res.status,
                    raw_result=raw,
                    error=res.error,
                )
            except Exception as exc:
                latency = int((time.monotonic() - v_start) * 1000)
                return ConsensusVote(
                    agent=agent_id,
                    decision="ERROR",
                    confidence=0.0,
                    response_summary=f"Dispatch error: {exc}",
                    latency_ms=latency,
                    status=TaskStatus.ERROR,
                    error=str(exc),
                )

        votes: list[ConsensusVote] = await asyncio.gather(
            *[_dispatch_single(agent_id) for agent_id in target_panel]
        )

        exec_ms = int((time.monotonic() - start_time) * 1000)

        # 3. Filter valid quorum responses (non-error, non-degraded)
        valid_votes = [
            v for v in votes
            if v.status in (TaskStatus.SUCCESS, TaskStatus.PENDING) and v.decision not in ("ERROR", "")
        ]
        quorum_count = len(valid_votes)

        # 4. Tally decisions and calculate consensus
        divergence_breakdown: dict[str, int] = {}
        for v in valid_votes:
            key = v.decision.lower().strip()
            divergence_breakdown[key] = divergence_breakdown.get(key, 0) + 1

        winning_decision: Optional[str] = None
        highest_vote_count = 0
        agreement_ratio = 0.0
        consensus_reached = False
        consensus_status = "FAILED"

        if quorum_count < min_quorum:
            consensus_status = "PARTIAL_QUORUM" if quorum_count > 0 else "FAILED"
            agreement_ratio = 0.0
        else:
            for dec, count in divergence_breakdown.items():
                if count > highest_vote_count:
                    highest_vote_count = count
                    winning_decision = dec

            agreement_ratio = highest_vote_count / quorum_count if quorum_count > 0 else 0.0

            if strategy == "unanimous":
                threshold = 1.0
            else:
                threshold = quorum_threshold

            if agreement_ratio >= threshold:
                consensus_reached = True
                consensus_status = "ACHIEVED"
            else:
                consensus_reached = False
                consensus_status = "DIVERGENT"

        synthesized_output = {
            "consensus_status": consensus_status,
            "consensus_reached": consensus_reached,
            "winning_decision": winning_decision,
            "agreement_ratio": round(agreement_ratio, 3),
            "quorum_count": quorum_count,
            "total_participants": len(target_panel),
            "divergence_breakdown": divergence_breakdown,
            "strategy": strategy,
            "votes": [
                {
                    "agent": v.agent,
                    "decision": v.decision,
                    "confidence": v.confidence,
                    "latency_ms": v.latency_ms,
                    "status": v.status.value,
                }
                for v in votes
            ],
        }

        # 5. Checkpoint persistence
        cp = None
        if self.trace_store:
            overall_status = TaskStatus.SUCCESS.value if consensus_reached else TaskStatus.DEGRADED.value
            cp = self.trace_store.record_checkpoint(
                ExecutionTraceCheckpoint(
                    trace_id=envelope.trace_id,
                    task_id=envelope.task_id,
                    target_agent="consensus",
                    action=action_name,
                    status=overall_status,
                    consensus_status=consensus_status,
                    participating_agents=target_panel,
                    agreement_ratio=agreement_ratio,
                    latency_ms=exec_ms,
                    payload_summary=payload_summary,
                    result_summary=f"Consensus {consensus_status}: winning decision '{winning_decision}' ({highest_vote_count}/{quorum_count})",
                    receipt_json=json.dumps(synthesized_output),
                )
            )

        return ConsensusResult(
            task_id=envelope.task_id,
            trace_id=envelope.trace_id,
            action=action_name,
            consensus_reached=consensus_reached,
            consensus_status=consensus_status,
            winning_decision=winning_decision,
            agreement_ratio=agreement_ratio,
            quorum_count=quorum_count,
            total_participants=len(target_panel),
            votes=votes,
            synthesized_output=synthesized_output,
            execution_time_ms=exec_ms,
            divergence_breakdown=divergence_breakdown,
            trace_checkpoint=cp,
        )


# Global singleton instance
specialist_router = SpecialistRouter()
