"""
FRIDAY/apps/core/src/friday_core/universe_auth.py — FRIDAY Universe Authentication.

Unified authentication, API key management, capability-based
authorization, and cross-agent identity verification.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException, Depends

router = APIRouter()


@dataclass
class AgentIdentity:
    """An agent's identity in the universe."""
    agent_name: str
    api_key: str
    capabilities: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_active: float = 0.0
    token_count: int = 0
    revoked: bool = False


@dataclass
class Capability:
    """A capability that can be granted to an agent."""
    name: str
    description: str = ""
    scope: str = "universe"  # agent, universe, global
    requires_auth: bool = True


@dataclass
class AuthToken:
    """An authentication token."""
    token_id: str
    agent_name: str
    capabilities: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    revoked: bool = False


class UniverseAuth:
    """Unified authentication and authorization for the universe."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentIdentity] = {}
        self._tokens: dict[str, AuthToken] = {}
        self._capabilities: dict[str, Capability] = {}
        self._register_default_capabilities()

    def _register_default_capabilities(self) -> None:
        """Register default capabilities."""
        caps = [
            ("reasoning", "AI reasoning and analysis"),
            ("memory", "Memory store and retrieve"),
            ("trading", "Trading and financial operations"),
            ("coding", "Code generation and review"),
            ("decision", "Decision analysis and recommendations"),
            ("security", "Security monitoring and audit"),
            ("research", "Research and OSINT"),
            ("forecast", "Predictive forecasting"),
            ("content", "Content creation and analysis"),
            ("orchestration", "Task orchestration and coordination"),
        ]
        for name, desc in caps:
            self._capabilities[name] = Capability(name=name, description=desc)

    def register_agent(self, agent_name: str, capabilities: list[str] | None = None) -> AgentIdentity:
        """Register an agent with an API key."""
        api_key = secrets.token_hex(32)
        agent = AgentIdentity(
            agent_name=agent_name,
            api_key=api_key,
            capabilities=capabilities or [],
            last_active=time.time(),
        )
        self._agents[agent_name] = agent
        return agent

    def verify_key(self, agent_name: str, api_key: str) -> bool:
        """Verify an agent's API key."""
        agent = self._agents.get(agent_name)
        if not agent or agent.revoked:
            return False
        if not hmac.compare_digest(agent.api_key, api_key):
            return False
        agent.last_active = time.time()
        return True

    def verify_capability(self, agent_name: str, capability: str) -> bool:
        """Verify if an agent has a capability."""
        agent = self._agents.get(agent_name)
        if not agent:
            return False
        return capability in agent.capabilities

    def issue_token(self, agent_name: str, capabilities: list[str] | None = None,
                    ttl_hours: float = 24.0) -> AuthToken:
        """Issue an authentication token for an agent."""
        agent = self._agents.get(agent_name)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        token_id = f"tok_{uuid.uuid4().hex[:16]}"
        token = AuthToken(
            token_id=token_id,
            agent_name=agent_name,
            capabilities=capabilities or agent.capabilities,
            expires_at=time.time() + ttl_hours * 3600,
        )
        self._tokens[token_id] = token
        agent.token_count += 1
        return token

    def verify_token(self, token_id: str) -> bool:
        """Verify a token."""
        token = self._tokens.get(token_id)
        if not token or token.revoked:
            return False
        if token.expires_at > 0 and token.expires_at < time.time():
            return False
        return True

    def revoke_token(self, token_id: str) -> bool:
        """Revoke a token."""
        token = self._tokens.get(token_id)
        if not token:
            return False
        token.revoked = True
        return True

    def revoke_agent(self, agent_name: str) -> bool:
        """Revoke an agent's access."""
        agent = self._agents.get(agent_name)
        if not agent:
            return False
        agent.revoked = True
        return True

    def list_agents(self) -> list[dict[str, Any]]:
        """List all registered agents."""
        return [
            {
                "agent_name": a.agent_name,
                "capabilities": a.capabilities,
                "created_at": a.created_at,
                "last_active": a.last_active,
                "revoked": a.revoked,
            }
            for a in self._agents.values()
        ]

    def list_capabilities(self) -> list[dict[str, Any]]:
        """List all available capabilities."""
        return [
            {"name": c.name, "description": c.description, "scope": c.scope}
            for c in self._capabilities.values()
        ]

    def get_report(self) -> dict[str, Any]:
        """Get authentication report."""
        return {
            "total_agents": len(self._agents),
            "active_agents": sum(1 for a in self._agents.values() if not a.revoked),
            "total_tokens": len(self._tokens),
            "active_tokens": sum(1 for t in self._tokens.values() if not t.revoked),
            "total_capabilities": len(self._capabilities),
            "engine_status": "operational",
        }


engine = UniverseAuth()

# Register default agents
for agent, caps in [
    ("FRIDAY", ["orchestration", "reasoning", "memory"]),
    ("Inference", ["reasoning"]),
    ("Memora", ["memory"]),
    ("Stratex", ["trading"]),
    ("Forge", ["coding"]),
    ("Cortex", ["decision"]),
    ("Sentinel", ["security"]),
    ("IntelX", ["research"]),
    ("Futuris", ["forecast"]),
    ("VyralX", ["content"]),
]:
    engine.register_agent(agent, caps)


@router.post("/auth/register")
async def register_agent(agent_name: str, capabilities: list[str] | None = None):
    """Register an agent."""
    agent = engine.register_agent(agent_name, capabilities)
    return {
        "agent_name": agent.agent_name,
        "api_key": agent.api_key,
        "capabilities": agent.capabilities,
        "status": "registered",
    }


@router.post("/auth/verify")
async def verify_key(agent_name: str, api_key: str):
    """Verify an agent's API key."""
    valid = engine.verify_key(agent_name, api_key)
    return {"agent_name": agent_name, "valid": valid}


@router.post("/auth/token")
async def issue_token(agent_name: str, capabilities: list[str] | None = None,
                      ttl_hours: float = 24.0):
    """Issue an authentication token."""
    token = engine.issue_token(agent_name, capabilities, ttl_hours)
    return {
        "token_id": token.token_id,
        "agent_name": token.agent_name,
        "capabilities": token.capabilities,
        "expires_at": token.expires_at,
    }


@router.post("/auth/token/{token_id}/revoke")
async def revoke_token(token_id: str):
    """Revoke a token."""
    if not engine.revoke_token(token_id):
        raise HTTPException(status_code=404, detail="Token not found")
    return {"token_id": token_id, "revoked": True}


@router.get("/auth/agents")
async def list_agents():
    """List all agents."""
    return {"agents": engine.list_agents()}


@router.get("/auth/capabilities")
async def list_capabilities():
    """List all capabilities."""
    return {"capabilities": engine.list_capabilities()}


@router.get("/auth/report")
async def auth_report():
    """Get authentication report."""
    return engine.get_report()
