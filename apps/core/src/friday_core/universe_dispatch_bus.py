"""
FRIDAY/apps/core/src/friday_core/universe_dispatch_bus.py — FRIDAY Universe Dispatch Bus.

Unified task dispatch to all 9 specialist agents with circuit breakers,
retry logic, timeout enforcement, and receipt-verified delivery via real HTTP.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class TaskEnvelope:
    """A task envelope for dispatch."""
    task_id: str
    agent: str
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 100
    timeout_sec: float = 30.0
    created_at: float = field(default_factory=time.time)
    retry_count: int = 0
    max_retries: int = 3


@dataclass
class TaskReceipt:
    """A receipt for a completed task."""
    task_id: str
    agent: str
    status: str  # completed, failed, timeout, error
    result: str = ""
    latency_ms: float = 0.0
    completed_at: float = 0.0
    error: str = ""


@dataclass
class AgentDispatchConfig:
    """Dispatch configuration for an agent."""
    agent_name: str
    base_url: str
    health_url: str = ""
    timeout_sec: float = 30.0
    max_retries: int = 3
    circuit_open: bool = False
    consecutive_failures: int = 0
    last_success: float = 0.0


class UniverseDispatchBus:
    """Unified dispatch bus for all specialist agents with real HTTP delivery."""

    def __init__(self) -> None:
        self._configs: dict[str, AgentDispatchConfig] = {}
        self._tasks: dict[str, TaskEnvelope] = {}
        self._receipts: dict[str, TaskReceipt] = {}
        self._circuit_threshold: int = 3
        self._register_default_agents()

    def resolve_agent_by_capability(self, capability: str) -> str | None:
        """Resolve which agent owns a capability through the central registry."""
        try:
            from mesh.registry import AgentRegistry
            reg = AgentRegistry()
            manifests = reg.discover_by_capability(capability)
            if manifests:
                return manifests[0].name
        except Exception:
            pass
        return None

    def resolve_agent_by_intent(self, intent: str) -> str | None:
        """Resolve which agent handles an intent through the central registry."""
        try:
            from mesh.registry import AgentRegistry
            reg = AgentRegistry()
            manifests = reg.discover_by_intent(intent)
            if manifests:
                return manifests[0].name
        except Exception:
            pass
        return None

    def _register_default_agents(self) -> None:
        """Register default agent dispatch configurations."""
        agents = [
            ("Inference", "http://127.0.0.1:8005", "http://127.0.0.1:8005/health"),
            ("Memora", "http://127.0.0.1:8007", "http://127.0.0.1:8007/health"),
            ("Stratex", "http://127.0.0.1:8001", "http://127.0.0.1:8001/health"),
            ("Forge", "http://127.0.0.1:8009", "http://127.0.0.1:8009/health"),
            ("Cortex", "http://127.0.0.1:8002", "http://127.0.0.1:8002/health"),
            ("Sentinel", "http://127.0.0.1:8008", "http://127.0.0.1:8008/health"),
            ("IntelX", "http://127.0.0.1:8006", "http://127.0.0.1:8006/health"),
            ("Futuris", "http://127.0.0.1:8004", "http://127.0.0.1:8004/health"),
            ("VyralX", "http://127.0.0.1:8010", "http://127.0.0.1:8010/health"),
        ]
        for name, base, health in agents:
            self.register_agent(name, base, health)

    def register_agent(self, agent_name: str, base_url: str,
                       health_url: str = "", timeout_sec: float = 30.0,
                       max_retries: int = 3) -> AgentDispatchConfig:
        """Register an agent for dispatch."""
        config = AgentDispatchConfig(
            agent_name=agent_name, base_url=base_url,
            health_url=health_url, timeout_sec=timeout_sec, max_retries=max_retries,
        )
        self._configs[agent_name] = config
        return config

    def _build_action_url(self, config: AgentDispatchConfig, action: str) -> str:
        """Build the full URL for an agent action."""
        return f"{config.base_url.rstrip('/')}/agent/{config.agent_name.lower()}/{action}"

    def _record_success(self, config: AgentDispatchConfig, latency_ms: float) -> None:
        """Record a successful dispatch."""
        config.last_success = time.time()
        config.consecutive_failures = 0
        config.circuit_open = False

    def _record_failure(self, config: AgentDispatchConfig) -> None:
        """Record a failed dispatch and check circuit breaker."""
        config.consecutive_failures += 1
        if config.consecutive_failures >= self._circuit_threshold:
            config.circuit_open = True

    async def _dispatch_http(self, envelope: TaskEnvelope, config: AgentDispatchConfig) -> TaskReceipt:
        """Send real HTTP request to the agent with retry logic."""
        url = self._build_action_url(config, envelope.action)
        timeout = envelope.timeout_sec
        last_error = ""

        for attempt in range(envelope.max_retries + 1):
            envelope.retry_count = attempt
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(url, json=envelope.payload)
                    if resp.status_code == 200:
                        result = resp.json()
                        return TaskReceipt(
                            task_id=envelope.task_id,
                            agent=envelope.agent,
                            status="completed",
                            result=str(result.get("result", result.get("detail", result))),
                            latency_ms=(time.time() - envelope.created_at) * 1000,
                            completed_at=time.time(),
                        )
                    elif resp.status_code == 404:
                        last_error = f"Action '{envelope.action}' not found on {envelope.agent}"
                        break  # Don't retry 404s
                    else:
                        last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except httpx.TimeoutException:
                last_error = f"Timeout after {timeout}s"
            except httpx.ConnectError:
                last_error = f"Connection refused - agent not running"
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"

            if attempt < envelope.max_retries:
                await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff

        return TaskReceipt(
            task_id=envelope.task_id,
            agent=envelope.agent,
            status="failed",
            result="",
            latency_ms=(time.time() - envelope.created_at) * 1000,
            completed_at=time.time(),
            error=last_error,
        )

    async def dispatch_async(self, agent: str, action: str, payload: dict[str, Any],
                              priority: int = 100, timeout_sec: float = 0.0) -> TaskReceipt:
        """Dispatch a task to an agent via real HTTP with retry logic."""
        config = self._configs.get(agent)
        if not config:
            raise HTTPException(status_code=404, detail=f"Agent {agent} not registered")
        if config.circuit_open:
            raise HTTPException(status_code=503, detail=f"Circuit open for {agent}")

        task_id = f"disp_{uuid.uuid4().hex[:12]}"
        envelope = TaskEnvelope(
            task_id=task_id, agent=agent, action=action, payload=payload,
            priority=priority,
            timeout_sec=timeout_sec or config.timeout_sec,
            max_retries=config.max_retries,
        )
        self._tasks[task_id] = envelope

        receipt = await self._dispatch_http(envelope, config)
        self._receipts[task_id] = receipt

        if receipt.status == "completed":
            self._record_success(config, receipt.latency_ms)
        else:
            self._record_failure(config)

        return receipt

    def dispatch(self, agent: str, action: str, payload: dict[str, Any],
                 priority: int = 100, timeout_sec: float = 0.0) -> TaskReceipt:
        """Dispatch a task to an agent (synchronous wrapper)."""
        config = self._configs.get(agent)
        if not config:
            raise HTTPException(status_code=404, detail=f"Agent {agent} not registered")
        if config.circuit_open:
            raise HTTPException(status_code=503, detail=f"Circuit open for {agent}")

        task_id = f"disp_{uuid.uuid4().hex[:12]}"
        envelope = TaskEnvelope(
            task_id=task_id, agent=agent, action=action, payload=payload,
            priority=priority,
            timeout_sec=timeout_sec or config.timeout_sec,
            max_retries=config.max_retries,
        )
        self._tasks[task_id] = envelope

        start = time.time()
        # Use real HTTP with retry logic
        url = self._build_action_url(config, action)
        timeout = envelope.timeout_sec
        last_error = ""

        for attempt in range(envelope.max_retries + 1):
            envelope.retry_count = attempt
            try:
                resp = httpx.post(url, json=envelope.payload, timeout=timeout)
                if resp.status_code == 200:
                    result = resp.json()
                    receipt = TaskReceipt(
                        task_id=task_id, agent=agent, status="completed",
                        result=str(result.get("result", result.get("detail", result))),
                        latency_ms=(time.time() - start) * 1000,
                        completed_at=time.time(),
                    )
                    self._receipts[task_id] = receipt
                    self._record_success(config, receipt.latency_ms)
                    return receipt
                elif resp.status_code == 404:
                    last_error = f"Action '{action}' not found on {agent}"
                    break
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"

            if attempt < envelope.max_retries:
                time.sleep(0.5 * (attempt + 1))

        receipt = TaskReceipt(
            task_id=task_id, agent=agent, status="failed",
            latency_ms=(time.time() - start) * 1000,
            completed_at=time.time(),
            error=last_error,
        )
        self._receipts[task_id] = receipt
        self._record_failure(config)
        return receipt

    def dispatch_batch(self, tasks: list[dict[str, Any]]) -> list[TaskReceipt]:
        """Dispatch multiple tasks."""
        receipts = []
        for task in tasks:
            receipt = self.dispatch(
                task["agent"], task["action"], task.get("payload", {}),
                task.get("priority", 100), task.get("timeout_sec", 0),
            )
            receipts.append(receipt)
        return receipts

    def check_circuit(self, agent: str) -> bool:
        """Check if circuit is open for an agent."""
        config = self._configs.get(agent)
        if not config:
            return True
        if config.consecutive_failures >= self._circuit_threshold:
            config.circuit_open = True
        return config.circuit_open

    def reset_circuit(self, agent: str) -> bool:
        """Reset circuit for an agent."""
        config = self._configs.get(agent)
        if not config:
            return False
        config.circuit_open = False
        config.consecutive_failures = 0
        return True

    def get_receipt(self, task_id: str) -> dict[str, Any]:
        """Get a task receipt."""
        receipt = self._receipts.get(task_id)
        if not receipt:
            raise HTTPException(status_code=404, detail="Receipt not found")
        return {
            "task_id": receipt.task_id,
            "agent": receipt.agent,
            "status": receipt.status,
            "result": receipt.result,
            "latency_ms": receipt.latency_ms,
            "completed_at": receipt.completed_at,
            "error": receipt.error,
        }

    def get_agent_status(self, agent: str) -> dict[str, Any]:
        """Get dispatch status for an agent."""
        config = self._configs.get(agent)
        if not config:
            raise HTTPException(status_code=404, detail="Agent not found")
        return {
            "agent_name": config.agent_name,
            "base_url": config.base_url,
            "circuit_open": config.circuit_open,
            "consecutive_failures": config.consecutive_failures,
            "last_success": config.last_success,
        }

    def get_all_agent_status(self) -> list[dict[str, Any]]:
        """Get status of all registered agents."""
        return [
            {
                "agent_name": c.agent_name,
                "circuit_open": c.circuit_open,
                "consecutive_failures": c.consecutive_failures,
                "last_success": c.last_success > 0,
            }
            for c in self._configs.values()
        ]

    def get_report(self) -> dict[str, Any]:
        """Get dispatch bus report."""
        open_circuits = sum(1 for c in self._configs.values() if c.circuit_open)
        completed = sum(1 for r in self._receipts.values() if r.status == "completed")
        failed = sum(1 for r in self._receipts.values() if r.status == "failed")
        total = len(self._receipts)
        success_rate = (completed / total * 100) if total > 0 else 100
        return {
            "total_agents": len(self._configs),
            "circuit_open": open_circuits,
            "total_dispatches": total,
            "completed": completed,
            "failed": failed,
            "success_rate_pct": round(success_rate, 1),
            "engine_status": "operational" if open_circuits == 0 else "degraded",
        }


engine = UniverseDispatchBus()


@router.post("/dispatch/send")
async def dispatch_task(agent: str, action: str, payload: dict[str, Any],
                         priority: int = 100, timeout_sec: float = 0.0):
    """Dispatch a task to a specialist agent via real HTTP."""
    receipt = await engine.dispatch_async(agent, action, payload, priority, timeout_sec)
    return {
        "task_id": receipt.task_id,
        "agent": receipt.agent,
        "status": receipt.status,
        "latency_ms": receipt.latency_ms,
        "result": receipt.result,
        "error": receipt.error,
    }


@router.post("/dispatch/batch")
async def dispatch_batch(tasks: list[dict[str, Any]]):
    """Dispatch multiple tasks in batch."""
    receipts = []
    for task in tasks:
        receipt = await engine.dispatch_async(
            task["agent"], task["action"], task.get("payload", {}),
            task.get("priority", 100), task.get("timeout_sec", 0),
        )
        receipts.append(receipt)
    return {
        "receipts": [
            {"task_id": r.task_id, "agent": r.agent, "status": r.status,
             "result": r.result, "error": r.error}
            for r in receipts
        ],
        "total": len(receipts),
    }


@router.get("/dispatch/receipts/{task_id}")
async def get_receipt(task_id: str):
    """Get a task receipt."""
    return engine.get_receipt(task_id)


@router.get("/dispatch/agents")
async def list_agent_status():
    """List all agent dispatch status."""
    return {"agents": engine.get_all_agent_status()}


@router.get("/dispatch/agents/{agent_name}")
async def get_agent_status(agent_name: str):
    """Get dispatch status for a specific agent."""
    return engine.get_agent_status(agent_name)


@router.post("/dispatch/agents/{agent_name}/reset")
async def reset_circuit(agent_name: str):
    """Reset circuit for an agent."""
    if not engine.reset_circuit(agent_name):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"agent_name": agent_name, "circuit_reset": True}


@router.get("/dispatch/report")
async def dispatch_report():
    """Get dispatch bus report."""
    return engine.get_report()
