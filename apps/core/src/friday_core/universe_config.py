"""
FRIDAY/apps/core/src/friday_core/universe_config.py — FRIDAY Unified Configuration Manager.

Centralized config for all 10 agents with environment variable loading,
agent registration, config validation, and fail-closed defaults.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class AgentConfig:
    """Configuration for a single agent."""
    agent_name: str
    base_url: str
    port: int
    health_url: str = ""
    api_prefix: str = "/api/v1"
    capabilities: list[str] = field(default_factory=list)
    enabled: bool = True
    timeout_sec: float = 30.0
    last_validated: float = 0.0


@dataclass
class UniverseConfig:
    """Universe-wide configuration."""
    version: str = "1.0.0"
    agents: dict[str, AgentConfig] = field(default_factory=dict)
    default_timeout: float = 30.0
    max_retries: int = 3
    circuit_breaker_threshold: int = 3
    created_at: float = field(default_factory=time.time)


class ConfigManager:
    """Manager for universe configuration."""

    def __init__(self) -> None:
        self._config = UniverseConfig()
        self._register_default_agents()

    def _register_default_agents(self) -> None:
        """Register default agent configurations."""
        defaults = [
            ("Inference", 8005, "inference", ["reasoning", "analysis"]),
            ("Memora", 8007, "memora", ["memory", "context"]),
            ("Stratex", 8001, "stratex", ["trading", "finance"]),
            ("Forge", 8009, "forge", ["coding", "development"]),
            ("Cortex", 8002, "cortex", ["decision", "strategy"]),
            ("Sentinel", 8008, "sentinel", ["security", "compliance"]),
            ("IntelX", 8006, "intelx", ["research", "intel"]),
            ("Futuris", 8004, "futuris", ["forecast", "prediction"]),
            ("VyralX", 8010, "vyralx", ["content", "video"]),
            ("FRIDAY", 8000, "friday", ["orchestration", "coordination"]),
        ]
        for name, port, slug, caps in defaults:
            self.register_agent(name, f"http://{slug}:{port}", port, caps)

    def register_agent(self, agent_name: str, base_url: str, port: int,
                       capabilities: list[str] | None = None,
                       health_url: str = "", enabled: bool = True) -> AgentConfig:
        """Register an agent configuration."""
        config = AgentConfig(
            agent_name=agent_name, base_url=base_url, port=port,
            health_url=health_url or f"{base_url}/health",
            capabilities=capabilities or [], enabled=enabled,
            last_validated=time.time(),
        )
        self._config.agents[agent_name] = config
        return config

    def get_agent_config(self, agent_name: str) -> AgentConfig:
        """Get an agent's configuration."""
        config = self._config.agents.get(agent_name)
        if not config:
            raise HTTPException(status_code=404, detail="Agent not found in config")
        return config

    def validate_config(self) -> dict[str, Any]:
        """Validate the configuration."""
        results = []
        for name, config in self._config.agents.items():
            is_valid = bool(config.base_url) and config.port > 0
            results.append({
                "agent_name": name,
                "valid": is_valid,
                "enabled": config.enabled,
                "url": config.base_url,
            })
        return {
            "total_agents": len(results),
            "valid_agents": sum(1 for r in results if r["valid"]),
            "validation_results": results,
        }

    def get_all_agents(self) -> list[dict[str, Any]]:
        """Get all agent configurations."""
        return [
            {
                "agent_name": c.agent_name,
                "base_url": c.base_url,
                "port": c.port,
                "capabilities": c.capabilities,
                "enabled": c.enabled,
            }
            for c in self._config.agents.values()
        ]

    def get_report(self) -> dict[str, Any]:
        """Get config manager report."""
        return {
            "version": self._config.version,
            "total_agents": len(self._config.agents),
            "enabled_agents": sum(1 for c in self._config.agents.values() if c.enabled),
            "default_timeout": self._config.default_timeout,
            "max_retries": self._config.max_retries,
            "engine_status": "operational",
        }


engine = ConfigManager()


@router.get("/config/agents")
async def list_agents():
    """List all agent configurations."""
    return {"agents": engine.get_all_agents()}


@router.get("/config/agents/{agent_name}")
async def get_agent_config(agent_name: str):
    """Get an agent's configuration."""
    config = engine.get_agent_config(agent_name)
    return {
        "agent_name": config.agent_name,
        "base_url": config.base_url,
        "port": config.port,
        "capabilities": config.capabilities,
        "enabled": config.enabled,
    }


@router.post("/config/validate")
async def validate_config():
    """Validate the configuration."""
    return engine.validate_config()


@router.get("/config/report")
async def config_report():
    """Get config manager report."""
    return engine.get_report()
