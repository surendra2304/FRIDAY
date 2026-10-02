"""A trigger that makes gated self-repair reachable in operation.

Phase F2. The E1 loop is proven end to end by ``research/self_repair_loop.py``,
but that script is a proof, not a service: somebody has to run it. Nothing in
the running system proposes a repair, files the review, or surfaces the result.
So the loop works and the pipeline is still only reachable by hand.

This module is the missing trigger. It drives the steps that do not need a human
— propose, review, verify — and then **stops**. It has no code path that approves
or applies anything. That is deliberate, not an oversight: the gate requires a
human owner, and the standing rule here is that autonomy does not widen past
what was approved.

So an unattended pass can get a repair all the way to ``REVIEWED`` and no
further. The remaining step is the owner's, and it is the only step that is.

Two properties this module is built around:

* **It reaches the gate over HTTP only.** FRIDAY never imports another service's
  package — there is not one such import anywhere in ``src/friday``, because
  peers are always spoken to over the network. The proposer and the reviewer are
  therefore injected, not imported.
* **It cannot approve.** ``GateClient`` below has no approve and no apply, so the
  restriction is enforced by the type, not by a comment.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from friday.core.logging import get_logger

logger = get_logger("autonomous.repair_trigger")


class TriggerNotConfigured(RuntimeError):
    """The trigger is inert because it was built without a proposer or a reviewer.

    Deliberately not swallowed into a per-spec outcome. A misconfigured trigger
    that reported "no proposal" for every spec would be indistinguishable, in the
    summary and in anything built on top of it, from a fleet where nothing was
    broken. An inert trigger must fail loudly on its first pass; that is the only
    reading that cannot be mistaken for good news.
    """



class GateClient(Protocol):
    """The narrow slice of the gate this trigger is allowed to touch.

    Note what is absent: there is no approve and no apply. The type is the
    enforcement.
    """

    async def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]: ...


class Proposer(Protocol):
    """Forge's side: try a candidate fix against a real test command."""

    async def propose(
        self,
        *,
        repo_path: str,
        base_commit: str,
        branch: str,
        candidate: Any,
        test_command: str,
        env: dict[str, str] | None = None,
    ) -> Any: ...


class Reviewer(Protocol):
    """Sentinel's side: inspect a diff and sign a verdict."""

    def review(self, *, patch_fingerprint: str, **kwargs: Any) -> Any: ...


@dataclass
class WatchSpec:
    """One thing worth trying to repair, and how the repair would be proved."""

    name: str
    repo_path: str
    base_commit: str
    branch: str
    target_file: str
    original_snippet: str
    replacement_snippet: str
    rationale: str
    test_command: str
    env: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "repo_path": self.repo_path,
            "base_commit": self.base_commit,
            "branch": self.branch,
            "target_file": self.target_file,
            "original_snippet": self.original_snippet,
            "replacement_snippet": self.replacement_snippet,
            "rationale": self.rationale,
            "test_command": self.test_command,
            "env": dict(self.env),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "WatchSpec":
        return cls(
            name=str(raw["name"]),
            repo_path=str(raw["repo_path"]),
            base_commit=str(raw["base_commit"]),
            branch=str(raw["branch"]),
            target_file=str(raw["target_file"]),
            original_snippet=str(raw["original_snippet"]),
            replacement_snippet=str(raw["replacement_snippet"]),
            rationale=str(raw["rationale"]),
            test_command=str(raw["test_command"]),
            env={str(k): str(v) for k, v in dict(raw.get("env") or {}).items()},
        )


@dataclass
class TriggerOutcome:
    """What happened to one spec — including what did not happen."""

    spec: str
    proposed: bool = False
    patch_id: str | None = None
    proposal_outcome: str = "SKIPPED"
    proposal_detail: str = ""
    test_proved: bool = False
    review_filed: bool = False
    review_outcome: str = "SKIPPED"
    review_detail: str = ""
    waiting_on_owner: bool = False
    signature_verified: bool = False
    findings: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if not self.proposed:
            return f"{self.spec}: no proposal ({self.proposal_detail})"
        if not self.review_filed:
            return f"{self.spec}: proposed {self.patch_id}, review {self.review_outcome}"
        if self.waiting_on_owner:
            return f"{self.spec}: {self.patch_id} REVIEWED and waiting on the owner"
        return f"{self.spec}: {self.patch_id} review {self.review_outcome} ({self.review_detail})"

    def as_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec,
            "proposed": self.proposed,
            "patch_id": self.patch_id,
            "proposal_outcome": self.proposal_outcome,
            "proposal_detail": self.proposal_detail,
            "test_proved": self.test_proved,
            "review_filed": self.review_filed,
            "review_outcome": self.review_outcome,
            "review_detail": self.review_detail,
            "waiting_on_owner": self.waiting_on_owner,
            "signature_verified": self.signature_verified,
            "findings": list(self.findings),
        }


class RepairTrigger:
    """Drives propose and review as far as the owner gate, and no further.

    ``proposal_factory`` and ``reviewer_factory`` are injected so this module
    never imports Forge's or Sentinel's packages. In a deployment they would be
    HTTP clients against those services; ``research/repair_trigger_run.py``
    wires the real in-process implementations for local runs.
    """

    def __init__(
        self,
        client: GateClient,
        *,
        proposal_factory: Callable[[], Proposer] | None = None,
        reviewer_factory: Callable[[], Reviewer] | None = None,
        candidate_factory: Callable[[WatchSpec], Any] | None = None,
    ) -> None:
        self._client = client
        self._proposal_factory = proposal_factory
        self._reviewer_factory = reviewer_factory
        self._candidate_factory = candidate_factory
        self._proposer: Proposer | None = None

    def _propose(self) -> Proposer:
        if self._proposer is None:
            if self._proposal_factory is None:
                raise TriggerNotConfigured(
                    "no proposer configured; the trigger refuses to guess at a repair"
                )
            self._proposer = self._proposal_factory()
        return self._proposer

    def _review(self) -> Reviewer:
        if self._reviewer_factory is None:
            raise TriggerNotConfigured(
                "no reviewer configured; the trigger will not file an unsigned review, "
                "because the gate would refuse it anyway"
            )
        return self._reviewer_factory()

    async def run_once(self, specs: list[WatchSpec]) -> list[TriggerOutcome]:
        """One pass over the given specs. Never approves, never applies."""
        return [await self.run_spec(spec) for spec in specs]

    async def run_spec(self, spec: WatchSpec) -> TriggerOutcome:
        outcome = TriggerOutcome(spec=spec.name)
        candidate = (
            self._candidate_factory(spec)
            if self._candidate_factory is not None
            else _candidate_from_spec(spec)
        )

        try:
            proposal = await self._propose().propose(
                repo_path=spec.repo_path,
                base_commit=spec.base_commit,
                branch=spec.branch,
                candidate=candidate,
                test_command=spec.test_command,
                env=dict(spec.env),
            )
        except TriggerNotConfigured:
            # A deployment fault, not a result about this spec. Let it out.
            raise
        except Exception as exc:  # a broken repo must not stop the other specs
            outcome.proposal_detail = f"{type(exc).__name__}: {exc}"
            logger.warning("proposal raised for %s: %s", spec.name, outcome.proposal_detail)
            return outcome

        # The proposer only emits when the command genuinely went failing to
        # passing. If it did not, there is nothing honest to file.
        if not getattr(proposal, "fixed", False):
            outcome.proposal_detail = str(getattr(proposal, "reason", "proposer declined"))
            logger.info("proposal declined for %s: %s", spec.name, outcome.proposal_detail)
            return outcome

        outcome.test_proved = True
        request = proposal.to_request(spec.repo_path)
        filed = await self._client.post(
            "/api/self-repair/proposals",
            {
                "repo_path": request.repo_path,
                "branch": request.branch,
                "base_commit": request.base_commit,
                "target_file": request.target_file,
                "original_snippet": request.original_snippet,
                "replacement_snippet": request.replacement_snippet,
                "rationale": request.rationale,
                "proposed_by": request.proposed_by,
                "test_evidence": request.test_evidence,
            },
        )
        receipt = filed.get("receipt", {}) or {}
        outcome.proposal_outcome = str(receipt.get("outcome", "UNKNOWN"))
        outcome.proposal_detail = str(receipt.get("detail", ""))
        if outcome.proposal_outcome != "ACCEPTED":
            return outcome

        record = filed.get("record", {}) or {}
        outcome.proposed = True
        outcome.patch_id = record.get("patch_id")

        try:
            reviewed = self._review().review(
                patch_fingerprint=str(record.get("fingerprint", "")),
                target_file=spec.target_file,
                replacement_snippet=spec.replacement_snippet,
                test_evidence=request.test_evidence,
            )
        except TriggerNotConfigured:
            raise
        except Exception as exc:
            outcome.review_detail = f"{type(exc).__name__}: {exc}"
            logger.warning("review raised for %s: %s", spec.name, outcome.review_detail)
            return outcome

        outcome.findings = [str(r) for r in getattr(reviewed, "reasons", [])]
        document = reviewed.review.to_document()
        review_result = await self._client.post(
            f"/api/self-repair/{outcome.patch_id}/review", {"document": document}
        )
        review_receipt = review_result.get("receipt", {}) or {}
        outcome.review_filed = True
        outcome.review_outcome = str(review_receipt.get("outcome", "UNKNOWN"))
        outcome.review_detail = str(review_receipt.get("detail", ""))
        outcome.waiting_on_owner = outcome.review_outcome == "ACCEPTED"
        if outcome.waiting_on_owner:
            stored = (review_result.get("record", {}) or {}).get("review") or {}
            outcome.signature_verified = bool(stored.get("signature_verified"))
        return outcome


def _candidate_from_spec(spec: WatchSpec) -> Any:
    """Build the candidate fix object the proposer expects.

    Kept duck-typed on purpose: the real ``CandidateFix`` lives in Forge's
    package, which this module must not import.
    """
    return _Candidate(
        target_file=spec.target_file,
        original_snippet=spec.original_snippet,
        replacement_snippet=spec.replacement_snippet,
        rationale=spec.rationale,
    )


@dataclass
class _Candidate:
    target_file: str
    original_snippet: str
    replacement_snippet: str
    rationale: str


class HttpxGateClient:
    """The production gate client: plain HTTP, no shortcuts."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 300.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"x-friday-api-key": api_key}
        self._timeout = timeout

    async def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        import httpx

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}{path}", json=body, headers=self._headers
            )
            response.raise_for_status()
            return response.json()


def render_summary(outcomes: list[TriggerOutcome]) -> str:
    lines = ["", "=== repair trigger summary ==="]
    for outcome in outcomes:
        lines.append(f"  {outcome.summary}")
    waiting = [o for o in outcomes if o.waiting_on_owner]
    lines += [
        "",
        f"  specs attempted     : {len(outcomes)}",
        f"  proposals filed     : {sum(1 for o in outcomes if o.proposed)}",
        f"  reviews accepted    : {len(waiting)}",
        f"  waiting on the owner: {len(waiting)}  (this trigger never approves or applies)",
    ]
    return "\n".join(lines)


def outcomes_as_json(outcomes: list[TriggerOutcome]) -> str:
    return json.dumps([o.as_dict() for o in outcomes], indent=2)
