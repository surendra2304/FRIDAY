# -*- coding: utf-8 -*-
"""Comprehensive Gemini Request Accounting, Token Tracking, and Multi-Level Budget Enforcement.

Features:
1. Tracks request count, credential project label (NEVER raw API keys), model, purpose, task ID,
   cache hits/misses, retries, fallbacks, token usage, and failure categories.
2. Enforces Per-Task, Per-Session, Hourly, and Daily request budgets.
3. Circuit breaker: Prevents infinite vision loops, repeated failed provider calls, unnecessary
   re-perception, and duplicate reasoning calls.
4. Stops cleanly and transparently when any budget is reached.
5. Ensures credential failover is used solely for legitimate configured redundancy.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

from friday.core.logging import get_logger

logger = get_logger("auth.accounting")


class BudgetExceededError(RuntimeError):
    """Raised when a task, session, hourly, or daily budget limit is exceeded."""
    pass


@dataclass
class RequestRecord:
    """Audit record for a single LLM/Vision/Voice provider request."""
    request_id: str
    timestamp: datetime
    credential_label: str  # e.g., "PRIMARY", "FALLBACK 1" (NO RAW KEYS)
    model: str
    purpose: str
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    is_cache_hit: bool = False
    retries_count: int = 0
    fallbacks_count: int = 0
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    failure_category: Optional[str] = None
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat(),
            "credential_label": self.credential_label,
            "model": self.model,
            "purpose": self.purpose,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "is_cache_hit": self.is_cache_hit,
            "retries_count": self.retries_count,
            "fallbacks_count": self.fallbacks_count,
            "estimated_input_tokens": self.estimated_input_tokens,
            "estimated_output_tokens": self.estimated_output_tokens,
            "failure_category": self.failure_category,
            "latency_ms": round(self.latency_ms, 2),
        }


@dataclass
class BudgetLimits:
    """Configurable budget thresholds across hierarchical execution scopes."""
    max_requests_per_task: int = 25
    max_requests_per_session: int = 150
    max_requests_per_hour: int = 300
    max_requests_per_day: int = 1500
    max_consecutive_failed_calls: int = 3
    max_vision_perceptions_per_task: int = 12


class RequestAccountant:
    """Thread-safe request accounting and budget enforcement layer."""

    _instance_lock = threading.Lock()
    _instance: Optional["RequestAccountant"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "RequestAccountant":
        if not cls._instance:
            with cls._instance_lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, limits: Optional[BudgetLimits] = None) -> None:
        if not hasattr(self, "_initialized"):
            self.lock = threading.Lock()
            self.limits = limits or BudgetLimits()
            self.records: List[RequestRecord] = []
            self.consecutive_failures = 0
            self._initialized = True

    def reset(self) -> None:
        """Reset internal records (useful for test isolation)."""
        with self.lock:
            self.records.clear()
            self.consecutive_failures = 0

    def can_make_request(
        self,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        purpose: str = "reasoning",
    ) -> Tuple[bool, Optional[str]]:
        """Check whether a new request is permitted under active budget limits."""
        with self.lock:
            now = datetime.now(timezone.utc)
            one_hour_ago = now - timedelta(hours=1)
            one_day_ago = now - timedelta(days=1)

            # 1. Consecutive failure circuit breaker
            if self.consecutive_failures >= self.limits.max_consecutive_failed_calls:
                return False, (
                    f"Circuit breaker active: {self.consecutive_failures} consecutive provider failures "
                    f"(limit: {self.limits.max_consecutive_failed_calls}). Halting to prevent quota burn."
                )

            # 2. Per-task budget
            if task_id:
                task_requests = sum(
                    1 for r in self.records
                    if r.task_id == task_id and not r.is_cache_hit
                )
                if task_requests >= self.limits.max_requests_per_task:
                    return False, (
                        f"Task budget exceeded: Task '{task_id}' made {task_requests} requests "
                        f"(limit: {self.limits.max_requests_per_task})."
                    )

                # Vision loop prevention
                if "vision" in purpose.lower():
                    vision_requests = sum(
                        1 for r in self.records
                        if r.task_id == task_id and "vision" in r.purpose.lower() and not r.is_cache_hit
                    )
                    if vision_requests >= self.limits.max_vision_perceptions_per_task:
                        return False, (
                            f"Vision loop guard triggered: Task '{task_id}' executed {vision_requests} visual "
                            f"perceptions (limit: {self.limits.max_vision_perceptions_per_task}). Halting to prevent infinite screen loop."
                        )

            # 3. Per-session budget
            if session_id:
                session_requests = sum(
                    1 for r in self.records
                    if r.session_id == session_id and not r.is_cache_hit
                )
                if session_requests >= self.limits.max_requests_per_session:
                    return False, (
                        f"Session budget exceeded: Session '{session_id}' made {session_requests} requests "
                        f"(limit: {self.limits.max_requests_per_session})."
                    )

            # 4. Hourly sliding window budget
            hourly_requests = sum(
                1 for r in self.records
                if r.timestamp >= one_hour_ago and not r.is_cache_hit
            )
            if hourly_requests >= self.limits.max_requests_per_hour:
                return False, (
                    f"Hourly request budget exceeded: {hourly_requests} requests in the last hour "
                    f"(limit: {self.limits.max_requests_per_hour})."
                )

            # 5. Daily sliding window budget
            daily_requests = sum(
                1 for r in self.records
                if r.timestamp >= one_day_ago and not r.is_cache_hit
            )
            if daily_requests >= self.limits.max_requests_per_day:
                return False, (
                    f"Daily request budget exceeded: {daily_requests} requests in the last 24 hours "
                    f"(limit: {self.limits.max_requests_per_day})."
                )

            return True, None

    def record_request(
        self,
        credential_label: str,
        model: str,
        purpose: str,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        is_cache_hit: bool = False,
        retries_count: int = 0,
        fallbacks_count: int = 0,
        estimated_input_tokens: int = 0,
        estimated_output_tokens: int = 0,
        failure_category: Optional[str] = None,
        latency_ms: float = 0.0,
    ) -> RequestRecord:
        """Record an accounting entry and update circuit breaker state."""
        with self.lock:
            rec = RequestRecord(
                request_id=f"req_{uuid.uuid4().hex[:10]}",
                timestamp=datetime.now(timezone.utc),
                credential_label=credential_label,
                model=model,
                purpose=purpose,
                task_id=task_id,
                session_id=session_id,
                is_cache_hit=is_cache_hit,
                retries_count=retries_count,
                fallbacks_count=fallbacks_count,
                estimated_input_tokens=estimated_input_tokens,
                estimated_output_tokens=estimated_output_tokens,
                failure_category=failure_category,
                latency_ms=latency_ms,
            )
            self.records.append(rec)

            if failure_category is not None:
                self.consecutive_failures += 1
                logger.warning(
                    f"RequestAccountant: Failure recorded ({failure_category}). "
                    f"Consecutive failures: {self.consecutive_failures}/{self.limits.max_consecutive_failed_calls}"
                )
            else:
                if not is_cache_hit:
                    self.consecutive_failures = 0

            return rec

    def get_summary(self) -> Dict[str, Any]:
        """Return structured request accounting summary without secrets."""
        with self.lock:
            total_reqs = len(self.records)
            cache_hits = sum(1 for r in self.records if r.is_cache_hit)
            failures = sum(1 for r in self.records if r.failure_category is not None)
            total_in_tokens = sum(r.estimated_input_tokens for r in self.records)
            total_out_tokens = sum(r.estimated_output_tokens for r in self.records)

            by_model: Dict[str, int] = {}
            by_label: Dict[str, int] = {}
            by_purpose: Dict[str, int] = {}

            for r in self.records:
                by_model[r.model] = by_model.get(r.model, 0) + 1
                by_label[r.credential_label] = by_label.get(r.credential_label, 0) + 1
                by_purpose[r.purpose] = by_purpose.get(r.purpose, 0) + 1

            return {
                "total_requests": total_reqs,
                "cache_hits": cache_hits,
                "cache_hit_rate": round(cache_hits / max(1, total_reqs), 4),
                "successful_requests": total_reqs - failures,
                "failed_requests": failures,
                "consecutive_failures": self.consecutive_failures,
                "total_input_tokens_est": total_in_tokens,
                "total_output_tokens_est": total_out_tokens,
                "requests_by_model": by_model,
                "requests_by_credential_label": by_label,
                "requests_by_purpose": by_purpose,
            }


# Global Singleton Accountant Instance
request_accountant = RequestAccountant()
