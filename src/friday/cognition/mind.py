"""A mind for every agent: a self-model, a ledger of what it has actually done,
and a shared memory it can be asked about.

The nine agents in this repository each had a prompt and a tool list. Neither is
a mind. A mind is three things:

1. **A self-model.** What am I, what am I for, what am I carrying, and what do I
   know I am not good at — the last of these derived from evidence, not modesty.
2. **A capability ledger.** Every attempt an agent makes is recorded against the
   capability it exercised, with its outcome. From that, "can you do this?" has an
   answer with a number behind it instead of a shrug or a boast. The estimate is
   the posterior mean of a Beta(1, 1): two observations is not proof, and the
   arithmetic says so.
3. **Shared recall.** Every recorded outcome also becomes an episode in
   :mod:`friday.cognition.memory_bridge`, so what one agent learns, all of them
   can be told. :class:`MindRegistry` is the switchboard: it can point a question
   at whichever agent has the strongest evidence for that capability.

Deliberate limits, so nothing here overclaims:

* confidence is evidence about *past attempts by this agent*, not a prediction,
  and it is reported as a posterior mean with its sample count attached;
* an agent with no record of a capability gets ``no_evidence``, not "yes";
* the ledger is written to disk under ``data/minds/`` so it survives a restart,
  and a corrupt file is discarded loudly rather than silently believed.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from friday.core.logging import get_logger
from friday.cognition.memory_bridge import Episode, Recall, SharedMemory, get_shared_memory

logger = get_logger("cognition.mind")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_dir() -> Path:
    override = os.getenv("FRIDAY_MIND_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path("data/minds")


@dataclass
class CapabilityRecord:
    """One capability, and the record of this agent exercising it."""

    name: str
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    last_outcome: str = ""
    last_detail: str = ""
    first_at: str = field(default_factory=_now_iso)
    last_at: str = field(default_factory=_now_iso)

    @property
    def confidence(self) -> float:
        """Posterior mean of Beta(1, 1) updated by the record.

        Honest about small samples by construction: 1 success out of 1 gives 0.67,
        not 1.0, because one observation is not certainty.
        """
        return (self.successes + 1) / (self.attempts + 2)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "attempts": self.attempts,
            "successes": self.successes,
            "failures": self.failures,
            "consecutive_failures": self.consecutive_failures,
            "confidence": round(self.confidence, 3),
            "last_outcome": self.last_outcome,
            "last_detail": self.last_detail[:300],
            "first_at": self.first_at,
            "last_at": self.last_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityRecord:
        record = cls(name=str(data.get("name", "")))
        record.attempts = int(data.get("attempts", 0) or 0)
        record.successes = int(data.get("successes", 0) or 0)
        record.failures = int(data.get("failures", 0) or 0)
        record.consecutive_failures = int(data.get("consecutive_failures", 0) or 0)
        record.last_outcome = str(data.get("last_outcome", ""))
        record.last_detail = str(data.get("last_detail", ""))
        record.first_at = str(data.get("first_at", _now_iso()))
        record.last_at = str(data.get("last_at", _now_iso()))
        return record


class CapabilityLedger:
    """What this agent has done, per capability, with the arithmetic kept."""

    def __init__(self, records: dict[str, CapabilityRecord] | None = None) -> None:
        self.records: dict[str, CapabilityRecord] = records or {}

    def observe(
        self,
        capability: str,
        success: bool,
        *,
        outcome: str = "",
        detail: str = "",
        at: str | None = None,
    ) -> CapabilityRecord:
        name = capability.strip() or "unspecified"
        record = self.records.get(name)
        if record is None:
            record = CapabilityRecord(name=name)
            self.records[name] = record
        record.attempts += 1
        if success:
            record.successes += 1
            record.consecutive_failures = 0
        else:
            record.failures += 1
            record.consecutive_failures += 1
        record.last_outcome = outcome or ("SUCCESS" if success else "FAILED")
        record.last_detail = detail
        record.last_at = at or _now_iso()
        return record

    def get(self, capability: str) -> CapabilityRecord | None:
        return self.records.get(capability)

    def confidence(self, capability: str) -> float | None:
        record = self.records.get(capability)
        return None if record is None else record.confidence

    def known(self) -> list[str]:
        return sorted(self.records)

    def best(self, capabilities: list[str] | tuple[str, ...] | None = None) -> str | None:
        """The capability this agent has the strongest evidence for."""
        candidates = [
            record
            for name, record in self.records.items()
            if (capabilities is None or name in capabilities) and record.attempts > 0
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda record: (record.confidence, record.attempts)).name

    def weakest(self, *, min_attempts: int = 1) -> list[CapabilityRecord]:
        struggling = [
            record
            for record in self.records.values()
            if record.attempts >= min_attempts and record.failures > 0
        ]
        struggling.sort(key=lambda record: (record.confidence, -record.attempts))
        return struggling

    def as_dict(self) -> dict[str, Any]:
        return {name: record.as_dict() for name, record in sorted(self.records.items())}


@dataclass
class SelfModel:
    """What this agent knows about itself, evidence included."""

    agent_id: str
    role: str
    purpose: str
    tools: list[str]
    capabilities: list[str]
    reliable: list[str]
    struggling: list[str]
    untested: list[str]
    reflection: str
    samples: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "purpose": self.purpose,
            "tools": self.tools,
            "capabilities": self.capabilities,
            "reliable": self.reliable,
            "struggling": self.struggling,
            "untested": self.untested,
            "reflection": self.reflection,
            "samples": self.samples,
        }


class Mind:
    """An agent's self-model, ledger and recall, in one object."""

    def __init__(
        self,
        agent_id: str,
        role: str,
        *,
        purpose: str = "",
        tools: list[str] | None = None,
        memory: SharedMemory | None = None,
        mesh: Any | None = None,
        ledger: CapabilityLedger | None = None,
        directory: str | Path | None = None,
        persist: bool = True,
    ) -> None:
        self.agent_id = agent_id
        self.role = role
        self.purpose = purpose or role
        self.tools = sorted(tools or [])
        self.memory = memory or get_shared_memory()
        self.mesh = mesh
        self.ledger = ledger or CapabilityLedger()
        self.directory = Path(directory) if directory is not None else _default_dir()
        self.persist = persist
        self._lock = threading.RLock()
        if persist:
            self._load()

    # -- construction ------------------------------------------------------

    @classmethod
    def from_agent(cls, agent: Any, **kwargs: Any) -> Mind:
        """Build the mind of a live agent, reading what it actually has."""
        tools: list[str] = []
        registry = getattr(agent, "tool_registry", None)
        if registry is not None:
            try:
                tools = [tool.name for tool in registry.list_tools()]
            except Exception:
                tools = []
        allowed = list(getattr(agent, "allowed_tools", []) or [])
        if allowed:
            tools = [name for name in tools if name in set(allowed)] or allowed
        return cls(
            agent_id=str(getattr(agent, "agent_id", "agent")),
            role=str(getattr(agent, "role", "specialist")),
            purpose=str(getattr(agent, "instructions", "") or getattr(agent, "role", "")),
            tools=tools,
            **kwargs,
        )

    # -- persistence -------------------------------------------------------

    @property
    def path(self) -> Path:
        return self.directory / f"{self.agent_id}.json"

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("mind file %s could not be read (%s); starting fresh", self.path, exc)
            return
        for name, data in (payload.get("ledger") or {}).items():
            if isinstance(data, dict):
                data.setdefault("name", name)
                self.ledger.records[name] = CapabilityRecord.from_dict(data)

    def save(self) -> None:
        if not self.persist:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            payload = {
                "agent_id": self.agent_id,
                "role": self.role,
                "saved_at": _now_iso(),
                "ledger": self.ledger.as_dict(),
            }
            temp = self.path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            temp.replace(self.path)
        except OSError as exc:
            logger.warning("mind of %s could not be saved: %s", self.agent_id, exc)

    # -- learning ----------------------------------------------------------

    def observe(
        self,
        capability: str,
        success: bool,
        *,
        detail: str = "",
        outcome: str = "",
        kind: str = "task",
        summary: str = "",
        evidence: dict[str, Any] | None = None,
        remember: bool = True,
    ) -> CapabilityRecord:
        """Record one attempt, in the ledger and in shared memory."""
        with self._lock:
            record = self.ledger.observe(capability, success, outcome=outcome, detail=detail)
            if self.persist:
                self.save()
        if remember:
            self.memory.record(
                summary or f"{self.agent_id} exercised {capability}",
                agent=self.agent_id,
                role=self.role,
                kind=kind,
                outcome=outcome or record.last_outcome,
                success=success,
                detail=detail,
                capability=capability,
                tags=[capability, self.role],
                evidence=evidence or {},
            )
        return record

    def finish(self, goal: str, *, success: bool, capability: str = "", output: str = "", tool_calls: list[str] | None = None) -> CapabilityRecord:
        """Record the outcome of a whole task."""
        chosen = capability or (tool_calls[0] if tool_calls else "") or f"{self.role}.task"
        return self.observe(
            chosen,
            success,
            detail=output[:1000],
            outcome="SUCCESS" if success else "FAILED",
            kind="task",
            summary=f"{self.agent_id} {'completed' if success else 'failed'}: {goal[:160]}",
            evidence={"goal": goal[:300], "tool_calls": tool_calls or []},
        )

    # -- knowing -----------------------------------------------------------

    def can(self, capability: str) -> dict[str, Any]:
        """Answer "can you do this?" from evidence, with the evidence attached."""
        record = self.ledger.get(capability)
        if record is None or record.attempts == 0:
            return {
                "answer": "no_evidence",
                "why": f"{self.agent_id} has no recorded attempt at {capability}, so the honest "
                "answer is that it is unknown — not yes and not no",
                "samples": 0,
                "confidence": None,
            }
        if record.successes == 0:
            return {
                "answer": "evidence_against",
                "why": f"{record.failures} recorded attempt(s) at {capability}, none successful",
                "samples": record.attempts,
                "confidence": round(record.confidence, 3),
            }
        if record.consecutive_failures >= 2:
            return {
                "answer": "evidence_against",
                "why": (
                    f"{record.successes}/{record.attempts} succeeded, but the last "
                    f"{record.consecutive_failures} attempts failed: recent evidence is poor"
                ),
                "samples": record.attempts,
                "confidence": round(record.confidence, 3),
            }
        return {
            "answer": "evidence_supports",
            "why": f"{record.successes}/{record.attempts} recorded attempts succeeded",
            "samples": record.attempts,
            "confidence": round(record.confidence, 3),
        }

    def recall(self, query: str, *, limit: int = 5) -> list[Recall]:
        """Ask shared memory. Everything every other agent recorded is visible here."""
        return self.memory.recall(query, limit=limit)

    def self_model(self) -> SelfModel:
        reliable = sorted(
            (record for record in self.ledger.records.values() if record.confidence >= 0.6 and record.successes),
            key=lambda record: record.confidence,
            reverse=True,
        )
        struggling = [record for record in self.ledger.weakest() if record.confidence < 0.5]
        tested = {record.name for record in self.ledger.records.values() if record.attempts}
        untested = sorted(set(self.tools) - tested)
        return SelfModel(
            agent_id=self.agent_id,
            role=self.role,
            purpose=self.purpose,
            tools=self.tools,
            capabilities=self.ledger.known(),
            reliable=[record.name for record in reliable],
            struggling=[record.name for record in struggling],
            untested=untested,
            reflection=self.reflect(),
            samples=sum(record.attempts for record in self.ledger.records.values()),
        )

    def reflect(self) -> str:
        """A short first-person account of the record. No rounding up."""
        samples = sum(record.attempts for record in self.ledger.records.values())
        if not samples:
            return (
                f"I am {self.agent_id} ({self.role}). I have no recorded attempts yet, so I cannot "
                "tell you what I am good at — only what I am equipped for."
            )
        reliable = self.ledger.best()
        lines = [
            f"I am {self.agent_id} ({self.role}). I have {samples} recorded attempt(s)."
        ]
        if reliable:
            record = self.ledger.records[reliable]
            lines.append(
                f"Best evidence: {reliable} — {record.successes}/{record.attempts} succeeded."
            )
        struggling = self.ledger.weakest()
        if struggling:
            worst = struggling[0]
            lines.append(
                f"Weakest: {worst.name} — {worst.successes}/{worst.attempts} succeeded"
                + (
                    f", last failure: {worst.last_detail[:120]}"
                    if worst.last_detail
                    else ""
                )
                + "."
            )
        return " ".join(lines)

    # -- cooperating -------------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "purpose": self.purpose,
            "tools": self.tools,
            "samples": sum(record.attempts for record in self.ledger.records.values()),
            "ledger": self.ledger.as_dict(),
            "reflection": self.reflect(),
        }

    def status(self) -> dict[str, Any]:
        return {
            **self.as_dict(),
            "mind_file": str(self.path) if self.persist else None,
            "memory_episodes": len(self.memory.all(agent=self.agent_id)),
        }


class MindRegistry:
    """Every agent's mind, in one place, so they can find each other."""

    def __init__(self, memory: SharedMemory | None = None, mesh: Any | None = None) -> None:
        self.memory = memory or get_shared_memory()
        self.mesh = mesh
        self._minds: dict[str, Mind] = {}
        self._lock = threading.RLock()

    def register(self, mind: Mind) -> Mind:
        with self._lock:
            if mind.memory is not self.memory:
                mind.memory = self.memory
            if mind.mesh is None:
                mind.mesh = self.mesh
            self._minds[mind.agent_id] = mind
        return mind

    def attach(self, agent: Any) -> Mind:
        """Give a live agent a mind, or return the one it already has.

        Identity is the agent id, not the Python object: two handles on the same
        agent must share one ledger, or its history forks.
        """
        existing = getattr(agent, "mind", None)
        if isinstance(existing, Mind):
            return self.register(existing)
        agent_id = str(getattr(agent, "agent_id", ""))
        known = self._minds.get(agent_id)
        if known is not None:
            try:
                agent.mind = known
            except Exception:
                logger.debug("agent %s did not accept a mind attribute", agent)
            return known
        mind = Mind.from_agent(agent, memory=self.memory, mesh=self.mesh)
        try:
            agent.mind = mind
        except Exception:  # a frozen agent must not break registration
            logger.debug("agent %s did not accept a mind attribute", agent)
        return self.register(mind)

    def for_agent(self, agent_id: str) -> Mind | None:
        with self._lock:
            return self._minds.get(agent_id)

    def all(self) -> list[Mind]:
        with self._lock:
            return list(self._minds.values())

    def who_can(self, capability: str) -> list[dict[str, Any]]:
        """Which agents have evidence for a capability, best first."""
        ranked: list[dict[str, Any]] = []
        for mind in self.all():
            verdict = mind.can(capability)
            if verdict["answer"] == "no_evidence":
                continue
            ranked.append({"agent_id": mind.agent_id, "role": mind.role, **verdict})
        ranked.sort(key=lambda item: (item["answer"] == "evidence_supports", item["confidence"] or 0), reverse=True)
        return ranked

    def consult(self, capability: str) -> dict[str, Any]:
        """Pick the agent best placed to do something, and say why."""
        ranked = self.who_can(capability)
        if not ranked:
            return {
                "capability": capability,
                "chosen": None,
                "why": (
                    "no agent on this host has evidence for that capability; the honest next step "
                    "is to try it and record what happens"
                ),
                "candidates": [],
            }
        supported = [item for item in ranked if item["answer"] == "evidence_supports"]
        if not supported:
            return {
                "capability": capability,
                "chosen": None,
                "why": (
                    "no agent on this host has succeeded at that before; the records are "
                    "evidence against, not for — trying it and recording the outcome is the "
                    "honest next step"
                ),
                "candidates": ranked,
            }
        best = supported[0]
        return {
            "capability": capability,
            "chosen": best["agent_id"],
            "why": f"{best['agent_id']}: {best['why']}",
            "candidates": ranked,
        }

    def fleet_status(self) -> dict[str, Any]:
        minds = self.all()
        return {
            "agents": len(minds),
            "minds": [mind.as_dict() for mind in sorted(minds, key=lambda m: m.agent_id)],
            "memory": self.memory.status(),
            "lessons": self.memory.lessons(),
        }


_REGISTRY: MindRegistry | None = None


def get_mind_registry(**kwargs: Any) -> MindRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = MindRegistry(**kwargs)
    return _REGISTRY


def set_mind_registry(registry: MindRegistry) -> None:
    global _REGISTRY
    _REGISTRY = registry


def episode_to_line(episode: Episode) -> str:
    """A one-line summary for logs and status output."""
    return episode.one_line()
