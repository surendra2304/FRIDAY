"""
FRIDAY/apps/core/src/friday_core/universe_audit_trail.py — FRIDAY Universe Audit Trail.

Cross-agent audit logging, immutable event recording, compliance evidence,
and audit trail search and export.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class AuditEntry:
    """An audit trail entry."""
    entry_id: str
    timestamp: float
    agent: str
    action: str
    resource: str = ""
    status: str = "success"  # success, failure, warning
    detail: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class AuditSearch:
    """An audit trail search."""
    search_id: str
    criteria: dict = field(default_factory=dict)
    results: list[dict] = field(default_factory=list)
    total_matches: int = 0
    latency_ms: float = 0.0


@dataclass
class ComplianceEvidence:
    """Compliance evidence from audit trail."""
    evidence_id: str
    framework: str = ""  # SOC2, ISO27001, GDPR, HIPAA
    description: str = ""
    entries: list[str] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)


class UniverseAuditTrail:
    """Engine for cross-agent audit trail management."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []
        self._searches: list[AuditSearch] = []
        self._evidence: list[ComplianceEvidence] = []

    def log(self, agent: str, action: str, resource: str = "",
            status: str = "success", detail: str = "",
            metadata: dict | None = None) -> AuditEntry:
        """Log an audit entry."""
        entry_id = f"aud_{uuid.uuid4().hex[:12]}"
        entry = AuditEntry(
            entry_id=entry_id, timestamp=time.time(), agent=agent,
            action=action, resource=resource, status=status,
            detail=detail, metadata=metadata or {},
        )
        self._entries.append(entry)
        return entry

    def search(self, agent: str | None = None, action: str | None = None,
               status: str | None = None, limit: int = 100) -> AuditSearch:
        """Search audit trail."""
        search_id = f"srch_{uuid.uuid4().hex[:12]}"
        search = AuditSearch(search_id=search_id)
        start = time.time()

        results = self._entries
        if agent:
            results = [e for e in results if e.agent == agent]
        if action:
            results = [e for e in results if action in e.action]
        if status:
            results = [e for e in results if e.status == status]

        search.total_matches = len(results)
        search.results = [
            {"entry_id": e.entry_id, "agent": e.agent, "action": e.action,
             "resource": e.resource, "status": e.status, "timestamp": e.timestamp}
            for e in results[-limit:]
        ]
        search.latency_ms = (time.time() - start) * 1000
        self._searches.append(search)
        return search

    def generate_evidence(self, framework: str, description: str) -> ComplianceEvidence:
        """Generate compliance evidence."""
        evidence_id = f"evd_{uuid.uuid4().hex[:12]}"
        evidence = ComplianceEvidence(
            evidence_id=evidence_id, framework=framework,
            description=description,
        )
        evidence.entries = [
            e.entry_id for e in self._entries
            if e.status == "success" and e.timestamp > time.time() - 86400 * 30
        ]
        self._evidence.append(evidence)
        return evidence

    def get_entries(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get audit entries."""
        return [
            {"agent": e.agent, "action": e.action, "resource": e.resource,
             "status": e.status, "timestamp": e.timestamp, "detail": e.detail[:80]}
            for e in self._entries[-limit:]
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_entries": len(self._entries),
            "total_searches": len(self._searches),
            "total_evidence": len(self._evidence),
            "success_rate": round(
                sum(1 for e in self._entries if e.status == "success") / max(1, len(self._entries)), 2
            ) if self._entries else 0,
            "engine_status": "operational",
        }


engine = UniverseAuditTrail()


@router.post("/audit/log")
async def log(agent: str, action: str, resource: str = "", status: str = "success",
              detail: str = "", metadata: dict | None = None):
    """Log an audit entry."""
    entry = engine.log(agent, action, resource, status, detail, metadata)
    return {"entry_id": entry.entry_id, "agent": agent, "action": action}


@router.post("/audit/search")
async def search(agent: str | None = None, action: str | None = None,
                 status: str | None = None, limit: int = 100):
    """Search audit trail."""
    search = engine.search(agent, action, status, limit)
    return {
        "search_id": search.search_id,
        "total_matches": search.total_matches,
        "results": search.results[:10],
    }


@router.post("/audit/evidence")
async def generate_evidence(framework: str, description: str):
    """Generate compliance evidence."""
    evidence = engine.generate_evidence(framework, description)
    return {
        "evidence_id": evidence.evidence_id,
        "framework": evidence.framework,
        "entry_count": len(evidence.entries),
    }


@router.get("/audit/entries")
async def get_entries(limit: int = 50):
    """Get audit entries."""
    return {"entries": engine.get_entries(limit)}


@router.get("/audit/report")
async def audit_report():
    """Get audit trail report."""
    return engine.get_report()
