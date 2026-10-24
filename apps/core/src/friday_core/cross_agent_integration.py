"""
FRIDAY/apps/core/src/friday_core/cross_agent_integration.py — FRIDAY Cross-Agent Integration Layer.

Specialist-to-specialist peer calls, integration routing, and
cross-agent workflow coordination.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class PeerCallConfig:
    """Configuration for a peer-to-peer agent call."""
    caller: str
    callee: str
    endpoint: str = ""
    description: str = ""
    enabled: bool = True
    last_called: float = 0.0
    success_count: int = 0
    failure_count: int = 0


@dataclass
class PeerCall:
    """A peer-to-peer agent call record."""
    call_id: str
    caller: str
    callee: str
    endpoint: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    result: str = ""
    latency_ms: float = 0.0
    created_at: float = field(default_factory=time.time)


@dataclass
class IntegrationRule:
    """A rule for cross-agent integration."""
    rule_id: str
    name: str
    trigger_agent: str
    target_agent: str
    condition: str = ""
    action: str = "call"
    enabled: bool = True


class CrossAgentIntegration:
    """Layer for specialist-to-specialist peer calls."""

    def __init__(self) -> None:
        self._calls: dict[str, PeerCall] = {}
        self._configs: dict[str, PeerCallConfig] = {}
        self._rules: dict[str, IntegrationRule] = {}
        self._register_default_integrations()

    def _register_default_integrations(self) -> None:
        """Register default peer call configurations."""
        integrations = [
            # Forge -> Sentinel: submit code diff for security audit
            ("Forge", "Sentinel", "/api/v1/sentinel/security/audit",
             "Code diff security audit before deployment"),
            # VyralX -> Inference: call for scriptwriting and scene planning
            ("VyralX", "Inference", "/api/v1/inference/reasoning/tasks",
             "Scriptwriting and scene planning"),
            # VyralX -> Sentinel: submit render metadata for pre-publish verification
            ("VyralX", "Sentinel", "/api/v1/sentinel/security/audit",
             "Pre-publish policy verification"),
            # IntelX -> Memora: publish verified research briefs to memory
            ("IntelX", "Memora", "/api/v1/memora/memories",
             "Publish verified research briefs"),
            # Futuris -> IntelX: consume threat intel for risk forecasting
            ("Futuris", "IntelX", "/api/v1/intelex/research",
             "Consume threat intel for risk forecasting"),
            # Stratex -> Futuris: request market forecasts for strategy decisions
            ("Stratex", "Futuris", "/api/v1/futuris/forecasts",
             "Market forecast for trading strategy"),
            # Cortex -> Memora: retrieve context for decision analysis
            ("Cortex", "Memora", "/api/v1/memora/memories",
             "Retrieve context for decision analysis"),
            # Sentinel -> IntelX: query threat intel for IoC validation
            ("Sentinel", "IntelX", "/api/v1/intelex/correlation",
             "Query threat intel for IoC validation"),
        ]
        for caller, callee, endpoint, desc in integrations:
            config_key = f"{caller}_to_{callee}"
            self._configs[config_key] = PeerCallConfig(
                caller=caller, callee=callee, endpoint=endpoint, description=desc,
            )

    def call_peer(self, caller: str, callee: str, payload: dict[str, Any]) -> PeerCall:
        """Make a peer-to-peer call from one agent to another."""
        config_key = f"{caller}_to_{callee}"
        config = self._configs.get(config_key)
        if not config:
            raise HTTPException(status_code=404, detail=f"No integration configured for {caller} -> {callee}")
        if not config.enabled:
            raise HTTPException(status_code=403, detail=f"Integration {config_key} is disabled")

        call_id = f"peer_{uuid.uuid4().hex[:12]}"
        call = PeerCall(
            call_id=call_id, caller=caller, callee=callee,
            endpoint=config.endpoint, payload=payload,
        )

        start = time.time()
        # Simulate call (actual HTTP call would go here)
        call.status = "completed"
        call.result = f"Peer call from {caller} to {callee} completed"
        call.latency_ms = (time.time() - start) * 1000

        config.last_called = time.time()
        config.success_count += 1
        self._calls[call_id] = call
        return call

    def create_rule(self, name: str, trigger_agent: str, target_agent: str,
                    condition: str = "", action: str = "call") -> str:
        """Create an integration rule."""
        rule_id = f"rule_{uuid.uuid4().hex[:12]}"
        rule = IntegrationRule(
            rule_id=rule_id, name=name, trigger_agent=trigger_agent,
            target_agent=target_agent, condition=condition, action=action,
        )
        self._rules[rule_id] = rule
        return rule_id

    def enable_rule(self, rule_id: str) -> bool:
        """Enable an integration rule."""
        rule = self._rules.get(rule_id)
        if not rule:
            return False
        rule.enabled = True
        return True

    def disable_rule(self, rule_id: str) -> bool:
        """Disable an integration rule."""
        rule = self._rules.get(rule_id)
        if not rule:
            return False
        rule.enabled = False
        return True

    def get_calls(self, caller: str | None = None) -> list[dict[str, Any]]:
        """Get peer calls."""
        calls = list(self._calls.values())
        if caller:
            calls = [c for c in calls if c.caller == caller]
        return [
            {
                "call_id": c.call_id, "caller": c.caller, "callee": c.callee,
                "status": c.status, "latency_ms": c.latency_ms,
            }
            for c in calls[-50:]
        ]

    def get_integrations(self) -> list[dict[str, Any]]:
        """Get all configured integrations."""
        return [
            {
                "caller": c.caller, "callee": c.callee,
                "endpoint": c.endpoint, "description": c.description,
                "enabled": c.enabled, "last_called": c.last_called > 0,
                "success_count": c.success_count,
            }
            for c in self._configs.values()
        ]

    def get_rules(self) -> list[dict[str, Any]]:
        """Get all integration rules."""
        return [
            {
                "rule_id": r.rule_id, "name": r.name,
                "trigger_agent": r.trigger_agent, "target_agent": r.target_agent,
                "condition": r.condition, "enabled": r.enabled,
            }
            for r in self._rules.values()
        ]

    def get_report(self) -> dict[str, Any]:
        """Get integration report."""
        return {
            "total_integrations": len(self._configs),
            "enabled_integrations": sum(1 for c in self._configs.values() if c.enabled),
            "total_calls": len(self._calls),
            "total_rules": len(self._rules),
            "engine_status": "operational",
        }


engine = CrossAgentIntegration()


@router.post("/integration/call")
async def call_peer(caller: str, callee: str, payload: dict[str, Any]):
    """Make a peer-to-peer call between agents."""
    call = engine.call_peer(caller, callee, payload)
    return {
        "call_id": call.call_id,
        "caller": call.caller,
        "callee": call.callee,
        "status": call.status,
        "latency_ms": call.latency_ms,
    }


@router.get("/integration/list")
async def list_integrations():
    """List all configured integrations."""
    return {"integrations": engine.get_integrations()}


@router.get("/integration/calls")
async def get_calls(caller: str | None = None):
    """Get peer call history."""
    return {"calls": engine.get_calls(caller)}


@router.post("/integration/rules")
async def create_rule(name: str, trigger_agent: str, target_agent: str,
                      condition: str = "", action: str = "call"):
    """Create an integration rule."""
    rule_id = engine.create_rule(name, trigger_agent, target_agent, condition, action)
    return {"rule_id": rule_id, "status": "created"}


@router.get("/integration/rules")
async def list_rules():
    """List all integration rules."""
    return {"rules": engine.get_rules()}


@router.post("/integration/rules/{rule_id}/disable")
async def disable_rule(rule_id: str):
    """Disable an integration rule."""
    if not engine.disable_rule(rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"rule_id": rule_id, "enabled": False}


@router.post("/integration/rules/{rule_id}/enable")
async def enable_rule(rule_id: str):
    """Enable an integration rule."""
    if not engine.enable_rule(rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"rule_id": rule_id, "enabled": True}


@router.get("/integration/report")
async def integration_report():
    """Get integration report."""
    return engine.get_report()
