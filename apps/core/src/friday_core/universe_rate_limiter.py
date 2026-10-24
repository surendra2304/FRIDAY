"""
FRIDAY/apps/core/src/friday_core/universe_rate_limiter.py — FRIDAY Universe Rate Limiter.

Cross-agent rate limiting, quota management, throttling strategies,
and usage tracking.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class RateLimitConfig:
    """Rate limit configuration."""
    agent: str
    limit_type: str = "requests"  # requests, tokens, compute, bandwidth
    max_value: float = 1000.0
    window_sec: float = 60.0
    strategy: str = "token_bucket"  # fixed_window, sliding_window, token_bucket, leaky_bucket


@dataclass
class UsageRecord:
    """A usage record."""
    agent: str
    limit_type: str
    used: float = 0.0
    remaining: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class QuotaReport:
    """Quota usage report."""
    report_id: str
    agent: str
    total_requests: int = 0
    total_tokens: float = 0.0
    total_compute: float = 0.0
    violations: int = 0
    report_time: float = field(default_factory=time.time)


class UniverseRateLimiter:
    """Engine for cross-agent rate limiting."""

    def __init__(self) -> None:
        self._configs: dict[str, RateLimitConfig] = {}
        self._usage: list[UsageRecord] = []
        self._violations: list[dict] = []

    def configure_limit(self, agent: str, limit_type: str = "requests",
                        max_value: float = 1000.0, window_sec: float = 60.0,
                        strategy: str = "token_bucket") -> RateLimitConfig:
        """Configure a rate limit."""
        config_id = f"{agent}_{limit_type}"
        config = RateLimitConfig(
            agent=agent, limit_type=limit_type, max_value=max_value,
            window_sec=window_sec, strategy=strategy,
        )
        self._configs[config_id] = config
        return config

    def check_limit(self, agent: str, limit_type: str = "requests",
                    amount: float = 1.0) -> UsageRecord:
        """Check if a request is allowed."""
        config_id = f"{agent}_{limit_type}"
        config = self._configs.get(config_id)
        if not config:
            return UsageRecord(agent=agent, limit_type=limit_type, used=amount, remaining=config.max_value if config else amount)

        # Simple fixed window check
        now = time.time()
        window_start = now - (now % config.window_sec)
        recent_usage = sum(
            u.used for u in self._usage
            if u.agent == agent and u.limit_type == limit_type
            and u.timestamp >= window_start
        )

        remaining = max(0.0, config.max_value - recent_usage - amount)
        record = UsageRecord(
            agent=agent, limit_type=limit_type,
            used=recent_usage + amount, remaining=remaining,
        )
        self._usage.append(record)

        if remaining < 0:
            self._violations.append({
                "agent": agent, "limit_type": limit_type,
                "time": now, "overage": abs(remaining),
            })
            raise HTTPException(status_code=429, detail=f"Rate limit exceeded for {agent}")

        return record

    def get_quota_report(self, agent: str) -> QuotaReport:
        """Get quota usage report."""
        report_id = f"q_{uuid.uuid4().hex[:12]}"
        report = QuotaReport(report_id=report_id, agent=agent)

        agent_usage = [u for u in self._usage if u.agent == agent]
        report.total_requests = sum(1 for u in agent_usage if u.limit_type == "requests")
        report.total_tokens = sum(u.used for u in agent_usage if u.limit_type == "tokens")
        report.total_compute = sum(u.used for u in agent_usage if u.limit_type == "compute")
        report.violations = sum(1 for v in self._violations if v["agent"] == agent)

        return report

    def get_configs(self) -> list[dict[str, Any]]:
        """Get rate limit configurations."""
        return [
            {"agent": c.agent, "limit_type": c.limit_type,
             "max_value": c.max_value, "window_sec": c.window_sec,
             "strategy": c.strategy}
            for c in self._configs.values()
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_configs": len(self._configs),
            "total_usage_records": len(self._usage),
            "total_violations": len(self._violations),
            "engine_status": "operational",
        }


engine = UniverseRateLimiter()


@router.post("/ratelimit/configure")
async def configure_limit(agent: str, limit_type: str = "requests",
                          max_value: float = 1000.0, window_sec: float = 60.0,
                          strategy: str = "token_bucket"):
    """Configure a rate limit."""
    config = engine.configure_limit(agent, limit_type, max_value, window_sec, strategy)
    return {"agent": agent, "limit_type": limit_type, "max_value": config.max_value}


@router.post("/ratelimit/check")
async def check_limit(agent: str, limit_type: str = "requests", amount: float = 1.0):
    """Check if a request is allowed."""
    record = engine.check_limit(agent, limit_type, amount)
    return {"agent": agent, "used": record.used, "remaining": record.remaining}


@router.get("/ratelimit/quota/{agent}")
async def get_quota_report(agent: str):
    """Get quota usage report."""
    report = engine.get_quota_report(agent)
    return {
        "agent": report.agent,
        "total_requests": report.total_requests,
        "total_tokens": report.total_tokens,
        "violations": report.violations,
    }


@router.get("/ratelimit/configs")
async def get_configs():
    """Get rate limit configurations."""
    return {"configs": engine.get_configs()}


@router.get("/ratelimit/report")
async def ratelimit_report():
    """Get rate limiter report."""
    return engine.get_report()
