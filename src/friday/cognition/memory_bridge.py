"""Shared episodic recall: one memory that every FRIDAY-side agent reads and writes.

Each agent in this repository already owns a private conversation buffer, and
that buffer dies with the process. Nothing an agent learned was available to any
other agent, so a repair the reflex brain proved at 03:00 was invisible to the
agent asked the same question at 09:00. The owner's requirement was that the nine
agents "recall memories" and "help each other" — which needs one memory, not nine.

What an episode is
------------------
A short, structured record of something that actually happened: a task that ran,
a fault that was detected, a repair that was proven, a peer that refused. Every
episode carries the agent that observed it, what happened, whether it worked, and
the evidence. Episodes are append-only on disk, so they survive a restart, and
bounded in size, so the log cannot grow forever.

How recall works, said plainly
------------------------------
Retrieval is **lexical** — token overlap plus a recency decay. It is not semantic
search, and it does not pretend to be: every recall carries the mode it used and
the reason it matched. Semantic recall is available through the Memora peer, and
when a mesh is attached episodes are mirrored there best-effort; the mirror's own
outcome is recorded as evidence, and a mirror that fails never fails a task and is
never reported as success.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from friday.core.logging import get_logger

logger = get_logger("cognition.memory_bridge")

#: Kinds of episode. Kept small so recall can filter meaningfully.
KINDS = frozenset({"task", "repair", "observation", "lesson", "refusal", "peer"})

_WORD = re.compile(r"[a-z0-9_]{3,}")

#: Common words carry no recall signal and, worse, make unrelated episodes look
#: related ("built the module" matching anything containing "the"). Recall
#: quality depends on this list being boring.
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "was", "were", "has", "have",
        "had", "not", "but", "from", "into", "its", "you", "your", "our", "their",
        "there", "here", "then", "than", "when", "what", "which", "who", "how",
        "are", "did", "does", "can", "could", "would", "should", "will", "been",
    }
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_path() -> Path:
    override = os.getenv("FRIDAY_EPISODE_LOG", "").strip()
    if override:
        return Path(override).expanduser()
    return Path("data/shared_episodes.jsonl")


@dataclass
class Episode:
    """Something that happened, and what it is evidence of."""

    summary: str
    agent: str = "friday"
    role: str = ""
    kind: str = "task"
    outcome: str = ""
    success: bool | None = None
    detail: str = ""
    capability: str = ""
    tags: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] = field(default_factory=dict)
    at: str = field(default_factory=_now_iso)
    episode_id: str = field(default_factory=lambda: f"ep_{uuid.uuid4().hex[:10]}")

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            self.kind = "observation"

    def as_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "at": self.at,
            "agent": self.agent,
            "role": self.role,
            "kind": self.kind,
            "summary": self.summary,
            "detail": self.detail,
            "outcome": self.outcome,
            "success": self.success,
            "capability": self.capability,
            "tags": list(self.tags),
            "evidence": self.evidence,
            "refs": self.refs,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Episode:
        return cls(
            summary=str(data.get("summary", "")),
            agent=str(data.get("agent", "friday")),
            role=str(data.get("role", "")),
            kind=str(data.get("kind", "task")),
            outcome=str(data.get("outcome", "")),
            success=data.get("success"),
            detail=str(data.get("detail", "")),
            capability=str(data.get("capability", "")),
            tags=tuple(str(tag) for tag in data.get("tags", []) or []),
            evidence=dict(data.get("evidence") or {}),
            refs=dict(data.get("refs") or {}),
            at=str(data.get("at", _now_iso())),
            episode_id=str(data.get("episode_id") or f"ep_{uuid.uuid4().hex[:10]}"),
        )

    def one_line(self) -> str:
        mark = "ok" if self.success is True else "failed" if self.success is False else "unknown"
        return f"[{self.agent}/{self.kind}/{mark}] {self.summary}"


@dataclass
class Recall:
    """One episode that matched, with the reason it matched."""

    episode: Episode
    score: float
    why: str

    def as_dict(self) -> dict[str, Any]:
        return {"score": round(self.score, 4), "why": self.why, "episode": self.episode.as_dict()}


def _tokens(text: str) -> set[str]:
    return {word for word in _WORD.findall(text.lower()) if word not in _STOPWORDS}


class SharedMemory:
    """One episodic store, durable to a JSONL file, readable by every agent."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        mirror: Callable[[Episode], dict[str, Any]] | None = None,
        limit: int = 5000,
        half_life_seconds: float = 7 * 24 * 3600,
    ) -> None:
        self.path = Path(path) if path is not None else _default_path()
        self.limit = limit
        self.half_life_seconds = half_life_seconds
        self._mirror = mirror
        self._episodes: list[Episode] = []
        self._lock = threading.RLock()
        self._loaded = False
        self._mirror_outcomes: dict[str, int] = {}

    # -- storage -----------------------------------------------------------

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        try:
            kept: list[Episode] = []
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    kept.append(Episode.from_dict(json.loads(line)))
                except (ValueError, TypeError):
                    continue  # a corrupt line must not lose the rest of the history
            self._episodes = kept[-self.limit :]
        except OSError as exc:
            logger.warning("episode log at %s could not be read: %s", self.path, exc)

    def _append(self, episode: Episode) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(episode.as_dict(), default=str) + "\n")
        except OSError as exc:
            logger.warning("episode %s could not be persisted: %s", episode.episode_id, exc)

    def _compact(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".jsonl.tmp")
            with temp.open("w", encoding="utf-8") as handle:
                for episode in self._episodes[-self.limit :]:
                    handle.write(json.dumps(episode.as_dict(), default=str) + "\n")
            temp.replace(self.path)
        except OSError as exc:
            logger.warning("episode log could not be compacted: %s", exc)

    # -- writing -----------------------------------------------------------

    def record(
        self,
        summary: str,
        *,
        agent: str = "friday",
        role: str = "",
        kind: str = "task",
        outcome: str = "",
        success: bool | None = None,
        detail: str = "",
        capability: str = "",
        tags: tuple[str, ...] | list[str] = (),
        evidence: dict[str, Any] | None = None,
        refs: dict[str, Any] | None = None,
        mirror: bool = True,
    ) -> Episode:
        """Remember something that happened. Never invents a result."""
        episode = Episode(
            summary=summary.strip()[:500],
            agent=agent,
            role=role,
            kind=kind,
            outcome=outcome,
            success=success,
            detail=detail[:2000],
            capability=capability,
            tags=tuple(tags),
            evidence=dict(evidence or {}),
            refs=dict(refs or {}),
        )
        with self._lock:
            self._load()
            self._episodes.append(episode)
            if len(self._episodes) > self.limit:
                self._episodes = self._episodes[-self.limit :]
                self._compact()
            else:
                self._append(episode)

        if mirror and self._mirror is not None:
            self._mirror_safely(episode)
        return episode

    def _mirror_safely(self, episode: Episode) -> None:
        try:
            result = self._mirror(episode) or {}
        except Exception as exc:
            result = {"state": "MIRROR_FAILED", "detail": f"{type(exc).__name__}: {exc}"}
        state = str(result.get("state", "UNKNOWN"))
        self._mirror_outcomes[state] = self._mirror_outcomes.get(state, 0) + 1
        # Record the mirror's fate on the episode's own evidence in memory only:
        # rewriting the log for a failed mirror would be worse than the failure.
        logger.debug("episode %s mirror -> %s", episode.episode_id, state)

    # -- reading -----------------------------------------------------------

    def all(self, *, agent: str | None = None, kind: str | None = None) -> list[Episode]:
        with self._lock:
            self._load()
            episodes = list(self._episodes)
        if agent:
            episodes = [event for event in episodes if event.agent == agent]
        if kind:
            episodes = [event for event in episodes if event.kind == kind]
        return episodes

    def recent(self, limit: int = 10, *, agent: str | None = None) -> list[Episode]:
        return self.all(agent=agent)[-limit:][::-1]

    def recall(
        self,
        query: str,
        *,
        limit: int = 5,
        agent: str | None = None,
        kind: str | None = None,
        min_score: float = 0.01,
        now: float | None = None,
    ) -> list[Recall]:
        """Lexical recall with a recency decay. The mode is reported, not implied."""
        wanted = _tokens(query)
        if not wanted:
            return []
        reference = now if now is not None else time.time()
        scored: list[Recall] = []

        for episode in self.all(agent=agent, kind=kind):
            haystack = _tokens(
                " ".join(
                    [
                        episode.summary,
                        episode.detail,
                        episode.capability,
                        episode.outcome,
                        " ".join(episode.tags),
                        episode.agent,
                        episode.role,
                    ]
                )
            )
            if not haystack:
                continue
            overlap = wanted & haystack
            if not overlap:
                continue
            coverage = len(overlap) / len(wanted)
            age = max(0.0, reference - _parse_time(episode.at))
            recency = 0.5 ** (age / self.half_life_seconds)
            score = coverage * (0.6 + 0.4 * recency)
            if score < min_score:
                continue
            why = f"matched {', '.join(sorted(overlap))}"
            scored.append(Recall(episode=episode, score=score, why=why))

        scored.sort(key=lambda recall: recall.score, reverse=True)
        return scored[:limit]

    def agents(self) -> list[str]:
        return sorted({episode.agent for episode in self.all() if episode.agent})

    def success_rate(self, *, agent: str | None = None, capability: str = "") -> dict[str, Any]:
        relevant = [
            episode
            for episode in self.all(agent=agent)
            if episode.success is not None and (not capability or episode.capability == capability)
        ]
        if not relevant:
            return {"samples": 0, "successes": 0, "failures": 0, "rate": None}
        successes = sum(1 for episode in relevant if episode.success)
        return {
            "samples": len(relevant),
            "successes": successes,
            "failures": len(relevant) - successes,
            "rate": round(successes / len(relevant), 3),
        }

    def lessons(self, *, min_samples: int = 2) -> list[dict[str, Any]]:
        """What the fleet's own record says, per capability and agent."""
        buckets: dict[tuple[str, str], list[bool]] = {}
        for episode in self.all():
            if episode.success is None or not episode.capability:
                continue
            buckets.setdefault((episode.agent, episode.capability), []).append(episode.success)

        lessons: list[dict[str, Any]] = []
        for (agent, capability), outcomes in sorted(buckets.items()):
            if len(outcomes) < min_samples:
                continue
            rate = sum(outcomes) / len(outcomes)
            lessons.append(
                {
                    "agent": agent,
                    "capability": capability,
                    "samples": len(outcomes),
                    "success_rate": round(rate, 3),
                    "reading": (
                        "reliable so far"
                        if rate >= 0.8
                        else "mixed"
                        if rate >= 0.4
                        else "unreliable so far"
                    ),
                }
            )
        lessons.sort(key=lambda lesson: (lesson["success_rate"], -lesson["samples"]))
        return lessons

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._load()
            count = len(self._episodes)
        return {
            "path": str(self.path),
            "episodes": count,
            "agents": self.agents(),
            "retrieval_mode": "lexical (token overlap + recency decay)",
            "semantic_retrieval": (
                "available through the Memora peer only; CONFIGURED-BUT-UNVERIFIED here "
                "because no live Memora response has been observed"
            ),
            "mirror_outcomes": dict(self._mirror_outcomes),
        }


def _parse_time(value: str) -> float:
    try:
        return datetime.fromisoformat(value).timestamp()
    except (ValueError, TypeError):
        return time.time()


# ── the singleton, so every agent shares one memory ────────────────────────

_SHARED: SharedMemory | None = None


def get_shared_memory(**kwargs: Any) -> SharedMemory:
    global _SHARED
    if _SHARED is None:
        _SHARED = SharedMemory(**kwargs)
    return _SHARED


def set_shared_memory(memory: SharedMemory) -> None:
    """Swap the shared store. Used by tests and by process wiring."""
    global _SHARED
    _SHARED = memory


def mesh_mirror(mesh: Any, *, agent: str = "friday") -> Callable[[Episode], dict[str, Any]]:
    """Build a mirror function that copies episodes to the Memora peer.

    The mirror is deliberately *not* in the critical path: an episode is remembered
    locally first, and a Memora outage is recorded as a mirror outcome rather than
    raised into whatever task produced the memory.
    """
    import asyncio

    def mirror(episode: Episode) -> dict[str, Any]:
        async def send() -> dict[str, Any]:
            outcome = await mesh.dispatch(
                "memora",
                "store",
                objective=f"remember episode {episode.episode_id}",
                inputs={
                    "query": episode.summary,
                    "episode": episode.as_dict(),
                    "agent": agent,
                },
                attempts=1,
            )
            return {"state": outcome.state.value, "detail": outcome.detail[:300]}

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(send())
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, send()).result()

    return mirror
