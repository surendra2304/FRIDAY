"""The unattended caller for the gated self-repair trigger (Phase F2).

``RepairTrigger`` is the real half of a repair: it drives a proposal as far as a
signed review and then stops at the owner gate. What it did not have is a caller.
It was reached only from ``research/repair_trigger_run.py`` and from tests, so in
a running service it could never fire. A self-repair pipeline that nothing
schedules is a demonstration, not autonomy.

This module is that caller. It owns one question - what an unattended pass is,
and what it is allowed to claim - and it answers it the only way that survives
being read by someone who is looking for good news:

* A pass that checked nothing is ``NOT_CONFIGURED`` and names the key that is
  missing. It is never ``COMPLETED`` and never an empty list of findings, because
  "the loop ran and found nothing" and "the loop has nothing to run" are the same
  string and only one of them is good news.
* A pass that could not finish a spec keeps the trigger's own per-spec record of
  which party lost it, so a transport failure cannot be summarised as a fleet
  that was well.
* Nothing here approves or applies. The owner gate is the only thing that writes,
  and it is not reachable from this module.

Configuration is all environment, so the loop is inert until an owner names a
watchlist and a gate. Default is off: an autonomous repair loop should never be
something a deployment acquires by being redeployed.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from friday.autonomous.repair_trigger import (
    GateClient,
    HttpxGateClient,
    RepairTrigger,
    TriggerNotConfigured,
    WatchSpec,
    render_summary,
)
from friday.core.logging import get_logger

logger = get_logger("autonomous.repair_loop")

#: The universe root: the directory holding this repo and its siblings. Forge and
#: Sentinel are sibling checkouts, not installed packages, so this is the only
#: place their import path can come from.
_DEFAULT_UNIVERSE_ROOT = Path(__file__).resolve().parents[3]


def _env_flag(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


@dataclass
class LoopConfig:
    """Everything this loop needs, and nothing it can assume.

    Defaults are the off position. An unset key is reported by name rather than
    defaulted into something that looks like a working pass.
    """

    enabled: bool = False
    interval_seconds: int = 900
    watchlist_path: str = ""
    gate_url: str = ""
    gate_key: str = ""
    #: The shared review key, which is NOT the control key. Sentinel signs with
    #: this and the gate verifies the signature with the same value, so the gate
    #: refuses a review signed by anything else. Reusing the control key here
    #: produces a review that is always REFUSED - which reads like Sentinel
    #: rejecting the fix, and is not.
    review_key: str = ""
    universe_root: str = str(_DEFAULT_UNIVERSE_ROOT)
    reviewer_state_dir: str = ""

    @classmethod
    def from_env(cls) -> "LoopConfig":
        root = (os.getenv("FRIDAY_UNIVERSE_ROOT") or str(_DEFAULT_UNIVERSE_ROOT)).strip()
        return cls(
            enabled=_env_flag("FRIDAY_SELF_REPAIR_TRIGGER_ENABLED"),
            interval_seconds=_env_int(
                "FRIDAY_SELF_REPAIR_TRIGGER_INTERVAL_SECONDS", 900, minimum=60
            ),
            watchlist_path=(os.getenv("FRIDAY_SELF_REPAIR_WATCHLIST") or "").strip(),
            gate_url=(os.getenv("FRIDAY_SELF_REPAIR_GATE_URL") or "").strip(),
            gate_key=(os.getenv("FRIDAY_SELF_REPAIR_GATE_KEY") or "").strip(),
            review_key=(os.getenv("FRIDAY_SELF_REPAIR_REVIEW_KEY") or "").strip(),
            universe_root=root,
            reviewer_state_dir=(os.getenv("FRIDAY_SELF_REPAIR_REVIEWER_STATE") or "").strip(),
        )

    def missing(self) -> list[str]:
        """The env keys that stop this loop from doing anything, by name.

        Returns the variable, not a description of it, so whoever reads the
        status can fix it without reading this file.
        """
        gaps: list[str] = []
        if not self.enabled:
            gaps.append("FRIDAY_SELF_REPAIR_TRIGGER_ENABLED")
        if not self.watchlist_path:
            gaps.append("FRIDAY_SELF_REPAIR_WATCHLIST")
        if not self.gate_url:
            gaps.append("FRIDAY_SELF_REPAIR_GATE_URL")
        if not self.gate_key:
            gaps.append("FRIDAY_SELF_REPAIR_GATE_KEY")
        if not self.review_key:
            gaps.append("FRIDAY_SELF_REPAIR_REVIEW_KEY")
        return gaps


class AutonomousRepairLoop:
    """One unattended pass per interval, reporting only what it actually did."""

    def __init__(self, config: LoopConfig | None = None) -> None:
        self._config = config or LoopConfig.from_env()
        self._state: dict[str, Any] = {
            "running": False,
            "enabled": self._config.enabled,
            "interval_seconds": self._config.interval_seconds,
            "status": "NOT_STARTED",
            "missing": self._config.missing(),
            "last_started_at": None,
            "last_completed_at": None,
            "last_error": None,
            "last_summary": None,
            "specs": 0,
            "outcomes": [],
        }

    # -- introspection -------------------------------------------------

    @property
    def interval_seconds(self) -> int:
        return self._config.interval_seconds

    def status(self) -> dict[str, Any]:
        """A snapshot an owner can act on.

        ``status`` is the whole point of this method, so it is stated first and
        never inferred from the length of ``outcomes``: a pass with no specs
        reports ``NOT_CONFIGURED``, not a clean sweep.
        """
        return dict(self._state)

    # -- the pass ------------------------------------------------------

    def _load_specs(self) -> list[WatchSpec]:
        path = Path(self._config.watchlist_path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("specs", [])
        if not isinstance(raw, list):
            raise ValueError("watchlist must be a list of specs, or an object with a 'specs' list")
        return [WatchSpec.from_dict(item) for item in raw]

    def _on_universe_path(self, repo: str) -> None:
        """Make a sibling checkout importable.

        Only paths that exist are added, and the addition is idempotent, so a
        repeated pass does not grow ``sys.path`` without bound.
        """
        candidate = Path(repo).resolve()
        if not candidate.is_dir():
            raise FileNotFoundError(f"{repo} is not a directory on this host")
        entry = str(candidate)
        if entry not in sys.path:
            sys.path.insert(0, entry)

    def _build_trigger(self, gate: GateClient) -> RepairTrigger:
        """Wire the real Forge proposer and the real Sentinel reviewer.

        The imports are deliberately inside this method. ``repair_trigger`` itself
        never imports either service, and a deployment where they are absent must
        fail with a name it can print, not at import time of the whole server.
        """
        self._on_universe_path(str(Path(self._config.universe_root) / "Forge"))
        self._on_universe_path(str(Path(self._config.universe_root) / "Sentinel"))

        from app.selfrepair.proposer import CandidateFix, GitSelfRepairProposer
        from sentinel.core.auth.approvals import ApprovalManager
        from sentinel.core.selfrepair.reviewer import SelfRepairReviewer
        from sentinel.storage.persistence.durable_store import SentinelPersistence

        # The reviewer's own audit trail is a service concern. Pointed at a repo
        # under repair it writes sentinel.db into the caller's working tree, which
        # is both noise in their diff and a way for untracked files to accumulate
        # in a tree that is supposed to be untouched.
        state_dir = self._config.reviewer_state_dir or str(
            Path(self._config.universe_root) / ".friday" / "repair-reviewer"
        )
        Path(state_dir).mkdir(parents=True, exist_ok=True)
        store = SentinelPersistence(db_path=str(Path(state_dir) / "sentinel.db"))

        return RepairTrigger(
            gate,
            proposal_factory=lambda: GitSelfRepairProposer(timeout=180.0),
            reviewer_factory=lambda: SelfRepairReviewer(
                approvals=ApprovalManager(store), signing_key=self._config.review_key
            ),
            candidate_factory=lambda spec: CandidateFix(
                target_file=spec.target_file,
                original_snippet=spec.original_snippet,
                replacement_snippet=spec.replacement_snippet,
                rationale=spec.rationale,
            ),
        )

    async def run_once(self) -> dict[str, Any]:
        """One pass. The returned status is what the caller is entitled to believe."""
        gaps = self._config.missing()
        if gaps:
            result = {
                "status": "NOT_CONFIGURED",
                "missing": gaps,
                "detail": "The unattended repair loop checked nothing.",
            }
        else:
            try:
                specs = self._load_specs()
            except Exception as exc:
                result = {
                    "status": "ERROR",
                    "error": type(exc).__name__,
                    "detail": f"The watchlist could not be read: {exc}",
                }
            else:
                result = await self._drive(specs)

        self._state.update(result)
        self._state["last_completed_at"] = datetime.now(timezone.utc).isoformat()
        return dict(result)

    async def _drive(self, specs: list[WatchSpec]) -> dict[str, Any]:
        """Run the trigger over the specs and describe what came back."""
        gate = HttpxGateClient(self._config.gate_url, self._config.gate_key)
        try:
            trigger = self._build_trigger(gate)
            outcomes = await trigger.run_once(specs)
        except TriggerNotConfigured as exc:
            # Deliberately not folded into a pass. A trigger with no proposer or
            # reviewer is inert, and an inert trigger that reported "no proposal"
            # for every spec would be indistinguishable from a fleet where nothing
            # was broken.
            return {
                "status": "NOT_CONFIGURED",
                "missing": ["proposer/reviewer"],
                "detail": str(exc),
            }
        except Exception as exc:
            logger.exception("Autonomous repair pass failed")
            return {"status": "ERROR", "error": type(exc).__name__, "detail": str(exc)}

        unfinished = sum(1 for o in outcomes if o.call_failed)
        return {
            "status": "COMPLETED",
            "specs": len(outcomes),
            "unfinished": unfinished,
            "waiting_on_owner": sum(1 for o in outcomes if o.waiting_on_owner),
            "outcomes": [o.as_dict() for o in outcomes],
            "summary": render_summary(outcomes),
            "detail": (
                f"{len(outcomes)} spec(s) checked; {unfinished} reached no verdict."
                if unfinished
                else f"{len(outcomes)} spec(s) checked; all reached a verdict."
            ),
        }

    async def run_forever(self) -> None:
        """The scheduled half. Sleeps first, so startup is not a repair storm."""
        self._state["running"] = True
        self._state["enabled"] = self._config.enabled
        self._state["missing"] = self._config.missing()
        try:
            while True:
                await asyncio.sleep(self._config.interval_seconds)
                if not self._config.enabled:
                    # Disabled after start: record it once and stop claiming work.
                    self._state.update(
                        {"status": "NOT_CONFIGURED", "running": False, "last_error": None}
                    )
                    return
                self._state["last_started_at"] = datetime.now(timezone.utc).isoformat()
                try:
                    await self.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._state["last_error"] = type(exc).__name__
                    logger.exception("Autonomous repair loop cycle failed")
        finally:
            self._state["running"] = False


#: One process, one loop. Built at import so the endpoints and the lifespan task
#: read the same object rather than two that look identical and disagree.
repair_loop = AutonomousRepairLoop()