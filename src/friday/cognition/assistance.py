"""Agents helping each other — with a real attempt behind every answer.

The mesh can move a task to a peer; the mind registry knows which agents have
evidence for what. Neither one, on its own, is help. This is the layer that joins
them, and it is deliberately thin, because the honest failure mode of a
"collaboration" feature is a sentence that sounds like help and is not:

* **A loopback** (asking yourself, or the agent that already failed) is refused
  with a reason. It is not an attempt, and calling it one would inflate the
  caller's ledger with a success it did not have.
* **A conscripted agent** can refuse. A local agent asked to consult answers from
  what it has actually recorded, and says `no_evidence` when it has none.
* **A remote peer** is asked over the mesh. Only a verified receipt completes the
  request; anything else is reported as what it was, and the peer's own mind
  records the attempt that it made or did not make.
* **Nobody is ever reported as having done work they did not do.** Every outcome
  carries the state of the attempt that produced it, so `PENDING` never reads as
  `COMPLETED`.

Two shapes of asking, both real:

* :meth:`AssistanceBroker.consult` — "who knows this?" — a private question.
* :meth:`AssistanceBroker.request_help` — "would you do this?" — an action, which
  goes through the mesh when the helper is a remote peer, and is executed by the
  helper when it is a local agent with the capability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("cognition.assistance")


@dataclass
class HelpOutcome:
    """What one agent's help actually amounted to."""

    caller: str
    helper: str
    capability: str
    state: str = "PENDING"          # mirrors OutcomeState's vocabulary
    performed: bool = False         # did the helper really execute the work
    helpful: bool = False           # did it move the caller forward at all
    answer: str = ""
    reason: str = ""
    attempt: dict[str, Any] = field(default_factory=dict)
    refused_because: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "caller": self.caller,
            "helper": self.helper,
            "capability": self.capability,
            "state": self.state,
            "performed": self.performed,
            "helpful": self.helpful,
            "answer": self.answer,
            "reason": self.reason,
            "refused_because": self.refused_because,
            "attempt": self.attempt,
        }

    def spoken(self) -> str:
        if self.performed:
            return f"{self.helper} did it: {self.answer}"
        if self.helpful:
            return f"{self.helper} could not do it, but knows something useful: {self.answer}"
        if self.refused_because:
            return f"{self.helper} did not help: {self.refused_because}"
        return f"No help came from {self.helper}: {self.reason or self.answer or 'no answer'}"


class AssistanceBroker:
    """One agent asking another, locally or across the mesh."""

    def __init__(self, registry: Any | None = None, mesh: Any | None = None) -> None:
        self._registry = registry
        self._mesh = mesh

    # -- collaborators -----------------------------------------------------

    def registry(self) -> Any | None:
        if self._registry is not None:
            return self._registry
        try:
            from friday.cognition.mind import get_mind_registry

            self._registry = get_mind_registry()
        except Exception as exc:  # pragma: no cover - configuration dependent
            logger.warning("no mind registry available for assistance: %s", exc)
            self._registry = None
        return self._registry

    def mesh(self) -> Any | None:
        if self._mesh is not None:
            return self._mesh
        try:
            from friday.cognition.mesh import get_mesh

            self._mesh = get_mesh()
        except Exception as exc:  # pragma: no cover - configuration dependent
            logger.warning("no mesh available for assistance: %s", exc)
            self._mesh = None
        return self._mesh

    # -- who knows this? ---------------------------------------------------

    def consult(self, capability: str, *, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
        """Ask the registry who has evidence for a capability, excluding anyone named."""
        registry = self.registry()
        if registry is None:
            return {
                "capability": capability,
                "chosen": None,
                "why": "no mind registry is attached, so no local agent could be asked",
                "candidates": [],
                "excluded": list(exclude),
            }
        answer = registry.consult(capability)
        blocked = {name.strip().lower() for name in exclude if name}
        candidates = [item for item in answer["candidates"] if item["agent_id"].lower() not in blocked]
        chosen = answer["chosen"]
        if chosen is not None and chosen.lower() in blocked:
            chosen = None
            answer["why"] = (
                f"the only agent with evidence for {capability} was excluded from this request"
            )
        return {**answer, "chosen": chosen, "candidates": candidates, "excluded": list(exclude)}

    # -- would you do this for me? -----------------------------------------

    async def request_help(
        self,
        caller: str,
        capability: str,
        objective: str,
        *,
        helper: str | None = None,
        inputs: dict[str, Any] | None = None,
        local_executor: Any | None = None,
        exclude: tuple[str, ...] = (),
    ) -> HelpOutcome:
        """Ask one helper to do something, and report what it actually did.

        ``helper`` may be a local agent id or a mesh peer. When it is omitted, the
        registry picks the agent with the best evidence for the capability, and a
        refusal from that agent is reported rather than retried behind its back.
        """
        if not capability.strip() or not objective.strip():
            return HelpOutcome(
                caller=caller,
                helper=helper or "",
                capability=capability,
                state="BLOCKED",
                refused_because="a request needs both a capability and an objective",
            )

        excluded = (*[name for name in exclude if name], caller)
        chosen = helper
        why = ""
        if not chosen:
            consulted = self.consult(capability, exclude=excluded)
            chosen = consulted.get("chosen")
            why = consulted.get("why", "")
            if not chosen:
                return HelpOutcome(
                    caller=caller,
                    helper="",
                    capability=capability,
                    state="BLOCKED",
                    reason=why or f"no agent has evidence for {capability}",
                    refused_because="",
                    attempt={"consult": consulted},
                )

        if chosen.strip().lower() in {name.strip().lower() for name in excluded}:
            return HelpOutcome(
                caller=caller,
                helper=chosen,
                capability=capability,
                state="BLOCKED",
                refused_because=(
                    f"{chosen} is the caller (or was excluded): asking the agent that already "
                    "failed is a loopback, not help"
                ),
                attempt={"excluded": list(excluded), "why": why},
            )

        mesh = self.mesh()
        registry = self.registry()
        local = registry.for_agent(chosen) if registry is not None else None

        # A local agent answers from what it has recorded, and may say no.
        if local is not None:
            verdict = local.can(capability)
            if verdict["answer"] != "evidence_supports":
                return HelpOutcome(
                    caller=caller,
                    helper=chosen,
                    capability=capability,
                    state="REFUSED",
                    answer=verdict["why"],
                    reason=verdict["why"],
                    refused_because=f"{chosen} has no evidence it can do this",
                    attempt={"local": verdict, "why": why},
                )
            performed = False
            answer = ""
            if local_executor is not None:
                try:
                    answer = await self._run_local(local_executor, chosen, capability, objective, inputs)
                    performed = True
                except Exception as exc:
                    local.observe(
                        capability,
                        False,
                        detail=f"{type(exc).__name__}: {exc}",
                        outcome="ERROR",
                        kind="assistance",
                        summary=f"{chosen} was asked by {caller} and failed: {objective[:120]}",
                    )
                    return HelpOutcome(
                        caller=caller,
                        helper=chosen,
                        capability=capability,
                        state="ERROR",
                        answer=f"{type(exc).__name__}: {exc}",
                        reason="the helper has the capability but this attempt failed",
                        attempt={"local": verdict, "error": f"{type(exc).__name__}: {exc}"},
                    )
            local.observe(
                capability,
                True,
                detail=answer[:1000],
                outcome="SUCCESS" if performed else "CONSULTED",
                kind="assistance",
                summary=f"{caller} asked {chosen}: {objective[:140]}",
                evidence={"objective": objective[:300], "performed": performed},
            )
            return HelpOutcome(
                caller=caller,
                helper=chosen,
                capability=capability,
                state="COMPLETED",
                performed=performed,
                helpful=True,
                answer=answer or f"{chosen} has evidence for {capability} and no executor was given",
                reason=why,
                attempt={"local": verdict},
            )

        # Otherwise it has to be a mesh peer.
        if mesh is None:
            return HelpOutcome(
                caller=caller,
                helper=chosen,
                capability=capability,
                state="BLOCKED",
                reason="no mesh client is attached, so the peer could not be asked",
                attempt={"why": why},
            )
        if chosen not in getattr(mesh, "contracts", {}):
            return HelpOutcome(
                caller=caller,
                helper=chosen,
                capability=capability,
                state="BLOCKED",
                reason=f"{chosen!r} is neither a local agent nor a known peer",
                attempt={"why": why},
            )

        # `dispatch(peer, action, ...)` — the action is what the receipt must name,
        # and the capability travels with the envelope so a peer can route on it.
        outcome = await mesh.dispatch(
            chosen,
            capability,
            objective=objective,
            inputs=inputs or {},
            capability=capability,
            actor=caller,
        )
        state = str(getattr(outcome.state, "value", outcome.state))
        result = getattr(outcome, "result", None) or {}
        answer = ""
        if isinstance(result, dict):
            answer = str(result.get("summary") or result.get("output") or "")
        # `PeerOutcome` carries the evidence the receipt was verified against, not
        # the receipt object; COMPLETED is only reachable through `verify_receipt`,
        # so it is the state that is authoritative - and its evidence must be
        # non-empty, or the state would be a claim with nothing behind it.
        evidence = getattr(outcome, "evidence", None) or {}
        performed = state == "COMPLETED" and bool(evidence)
        if registry is not None:
            caller_mind = registry.for_agent(caller)
            if caller_mind is not None:
                caller_mind.observe(
                    capability,
                    performed,
                    detail=answer or getattr(outcome, "detail", "")[:500],
                    outcome=state,
                    kind="assistance",
                    summary=f"{caller} asked the peer {chosen}: {objective[:120]}",
                    evidence={"peer": chosen, "state": state, "objective": objective[:300]},
                )
        return HelpOutcome(
            caller=caller,
            helper=chosen,
            capability=capability,
            state=state,
            performed=performed,
            helpful=performed,
            answer=answer,
            reason=getattr(outcome, "detail", ""),
            attempt=outcome.as_dict() if hasattr(outcome, "as_dict") else {"state": state},
        )

    async def _run_local(
        self,
        executor: Any,
        helper: str,
        capability: str,
        objective: str,
        inputs: dict[str, Any] | None,
    ) -> str:
        """Run a local helper's work. The executor is supplied, never invented."""
        request = {
            "agent": helper,
            "capability": capability,
            "objective": objective,
            "inputs": inputs or {},
        }
        result = executor(request)
        if hasattr(result, "__await__"):
            result = await result
        return str(result)

    # -- asking the whole mesh --------------------------------------------

    async def request_help_from_peers(
        self,
        caller: str,
        capability: str,
        objective: str,
        *,
        peers: tuple[str, ...] | None = None,
        inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ask every candidate peer at once, and report each peer's own answer.

        This is the ladder's last rung: a fault this host could not fix, asked of
        the peers that may be able to. Fan-out rather than a queue, because a peer
        that is unreachable must not stop the others from being asked. Completion
        is only ever claimed from a verified receipt, and the summary names *which*
        peer did the work — a delegation reported as local work would be a lie.
        """
        mesh = self.mesh()
        if mesh is None:
            return {
                "capability": capability,
                "asked": [],
                "completed_by": None,
                "performed": False,
                "reason": "no mesh client is attached, so no peer could be asked",
                "attempts": {},
            }

        known = {peer: contract for peer, contract in getattr(mesh, "contracts", {}).items()}
        chosen = tuple(peers) if peers else tuple(sorted(known))
        asked = [peer for peer in chosen if peer in known]
        if not asked:
            return {
                "capability": capability,
                "asked": [],
                "completed_by": None,
                "performed": False,
                "reason": "no known peer matches the peers that were named",
                "attempts": {},
            }

        outcomes = await mesh.dispatch_many(
            {peer: (capability, inputs or {}) for peer in asked},
            objective=objective,
            capability=capability,
            actor=caller,
            attempts=1,
        )
        attempts: dict[str, Any] = {}
        completed_by: str | None = None
        won_answer = ""
        for peer, outcome in outcomes.items():
            state = str(getattr(outcome.state, "value", outcome.state))
            attempts[peer] = {
                "state": state,
                "detail": getattr(outcome, "detail", ""),
                "evidence": getattr(outcome, "evidence", {}) or {},
            }
            if state == "COMPLETED" and completed_by is None:
                completed_by = peer
                result = getattr(outcome, "result", None) or {}
                won_answer = str(result.get("summary") or "") if isinstance(result, dict) else ""

        return {
            "capability": capability,
            "asked": asked,
            "completed_by": completed_by,
            "performed": completed_by is not None,
            "answer": won_answer,
            "reason": (
                f"{completed_by} completed the request"
                if completed_by
                else "no peer completed the request; each peer's own state is recorded"
            ),
            "attempts": attempts,
        }
