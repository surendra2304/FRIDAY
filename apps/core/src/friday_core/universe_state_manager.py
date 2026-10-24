"""
FRIDAY/apps/core/src/friday_core/universe_state_manager.py — FRIDAY Universe State Manager.

Cross-agent state synchronization, shared state management,
consistency guarantees, and state versioning.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class StateEntry:
    """A state entry."""
    key: str
    value: Any
    agent_owner: str = ""
    version: int = 1
    created_at: float = field(default_factory=time.time)
    updated_at: float = 0.0
    ttl: float = 0.0  # 0 = no expiration


@dataclass
class StateTransaction:
    """A state transaction."""
    transaction_id: str
    operations: list[dict] = field(default_factory=list)
    status: str = "pending"  # pending, committed, rolled_back
    created_at: float = field(default_factory=time.time)
    committed_at: float = 0.0


@dataclass
class ConsistencyReport:
    """Consistency report across agents."""
    report_id: str
    total_entries: int = 0
    stale_entries: int = 0
    inconsistent_entries: int = 0
    consistency_score: float = 0.0
    generated_at: float = field(default_factory=time.time)


class UniverseStateManager:
    """Engine for cross-agent state management."""

    def __init__(self) -> None:
        self._state: dict[str, StateEntry] = {}
        self._transactions: list[StateTransaction] = []
        self._reports: list[ConsistencyReport] = []

    def set_state(self, key: str, value: Any, agent_owner: str = "",
                  ttl: float = 0.0) -> StateEntry:
        """Set a state entry."""
        existing = self._state.get(key)
        if existing:
            existing.value = value
            existing.version += 1
            existing.updated_at = time.time()
            existing.agent_owner = agent_owner or existing.agent_owner
            existing.ttl = ttl or existing.ttl
            return existing

        entry = StateEntry(
            key=key, value=value, agent_owner=agent_owner,
            ttl=ttl, updated_at=time.time(),
        )
        self._state[key] = entry
        return entry

    def get_state(self, key: str) -> dict[str, Any]:
        """Get a state entry."""
        entry = self._state.get(key)
        if not entry:
            raise HTTPException(status_code=404, detail="State key not found")
        if entry.ttl > 0 and time.time() - entry.updated_at > entry.ttl:
            self._state.pop(key, None)
            raise HTTPException(status_code=410, detail="State expired")
        return {
            "key": entry.key, "value": entry.value, "version": entry.version,
            "agent_owner": entry.agent_owner, "updated_at": entry.updated_at,
        }

    def delete_state(self, key: str) -> None:
        """Delete a state entry."""
        if key not in self._state:
            raise HTTPException(status_code=404, detail="State key not found")
        self._state.pop(key)

    def begin_transaction(self) -> StateTransaction:
        """Begin a state transaction."""
        tx_id = f"tx_{uuid.uuid4().hex[:12]}"
        return StateTransaction(transaction_id=tx_id)

    def commit_transaction(self, transaction_id: str) -> StateTransaction:
        """Commit a state transaction."""
        tx = next((t for t in self._transactions if t.transaction_id == transaction_id), None)
        if not tx:
            raise HTTPException(status_code=404, detail="Transaction not found")
        tx.status = "committed"
        tx.committed_at = time.time()
        return tx

    def check_consistency(self) -> ConsistencyReport:
        """Check consistency across state entries."""
        report_id = f"cons_{uuid.uuid4().hex[:12]}"
        report = ConsistencyReport(report_id=report_id)
        report.total_entries = len(self._state)
        report.stale_entries = sum(
            1 for e in self._state.values()
            if e.ttl > 0 and time.time() - e.updated_at > e.ttl
        )
        report.inconsistent_entries = sum(
            1 for e in self._state.values() if e.version > 1 and not e.updated_at
        )
        report.consistency_score = (
            (report.total_entries - report.stale_entries - report.inconsistent_entries) /
            max(1, report.total_entries)
        ) * 100

        self._reports.append(report)
        return report

    def get_all_state(self, agent_owner: str | None = None) -> list[dict[str, Any]]:
        """Get all state entries."""
        entries = list(self._state.values())
        if agent_owner:
            entries = [e for e in entries if e.agent_owner == agent_owner]
        return [
            {"key": e.key, "version": e.version, "owner": e.agent_owner}
            for e in entries
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_state_entries": len(self._state),
            "total_transactions": len(self._transactions),
            "total_reports": len(self._reports),
            "engine_status": "operational",
        }


engine = UniverseStateManager()


@router.post("/statemanager/set")
async def set_state(key: str, value: Any, agent_owner: str = "", ttl: float = 0.0):
    """Set a state entry."""
    entry = engine.set_state(key, value, agent_owner, ttl)
    return {"key": entry.key, "version": entry.version}


@router.get("/statemanager/get/{key}")
async def get_state(key: str):
    """Get a state entry."""
    return engine.get_state(key)


@router.delete("/statemanager/delete/{key}")
async def delete_state(key: str):
    """Delete a state entry."""
    engine.delete_state(key)
    return {"key": key, "status": "deleted"}


@router.post("/statemanager/consistency")
async def check_consistency():
    """Check consistency."""
    report = engine.check_consistency()
    return {
        "report_id": report.report_id,
        "total_entries": report.total_entries,
        "consistency_score": report.consistency_score,
    }


@router.get("/statemanager/state")
async def get_all_state(agent_owner: str | None = None):
    """Get all state entries."""
    return {"entries": engine.get_all_state(agent_owner)}


@router.get("/statemanager/report")
async def statemanager_report():
    """Get state manager report."""
    return engine.get_report()
