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

#: How each failing party is described to a reader. The wording is the point: a
#: reader who is told the wrong party failed will go and look in the wrong place,
#: and "we never asked" and "we asked and got no answer" are not the same event.
_PARTY_PHRASE = {
    "local": "nothing was submitted; the failure was local",
    "forge": "the proposer failed, so no repair was attempted",
    "sentinel": "the reviewer failed, so this repair has no verdict",
    "gate": "the gate could not be reached",
}


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
    #: This spec ended with no verdict at all. Distinct from a result of "no",
    #: and never summarised as one. Whatever the reason, it is counted in the
    #: incompleteness banner, because a pass that could not finish something must
    #: not present as a pass that had nothing to do.
    call_failed: bool = False
    #: Which party failed: ``local``, ``forge``, ``sentinel`` or ``gate``. Empty
    #: when nobody failed. Named rather than inferred, because "the gate was
    #: unreachable" and "we never got as far as asking it" send a reader to two
    #: completely different places to look.
    failed_party: str = ""
    call_detail: str = ""
    findings: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        # Checked first and phrased as a loss, so it cannot be misread as a
        # settled "no" no matter how the other branches are worded.
        if self.call_failed:
            return (
                f"{self.spec}: NO RESULT - {_PARTY_PHRASE.get(self.failed_party, self.failed_party)}"
                f" ({self.call_detail})"
            )
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
            "call_failed": self.call_failed,
            "failed_party": self.failed_party,
            "call_detail": self.call_detail,
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
        """One pass over the given specs. Never approves, never applies.

        A failure that belongs to one spec must not cost the results of the others.
        ``run_spec`` contains the failures it knows about, and this loop is the net
        under the ones it does not: whatever goes wrong, the specs that already
        finished keep their outcomes and the pass still returns. Discarding three
        good results because the fourth could not reach the network turns a
        transport blip into an empty report, which is the one reading nobody can
        act on.
        """
        outcomes: list[TriggerOutcome] = []
        for spec in specs:
            try:
                outcomes.append(await self.run_spec(spec))
            except TriggerNotConfigured:
                # A deployment fault, not a result about any spec. Let it out.
                raise
            except Exception as exc:  # the net, deliberately wide
                outcomes.append(
                    TriggerOutcome(
                        spec=spec.name,
                        call_failed=True,
                        failed_party="local",
                        call_detail=f"unexpected failure: {type(exc).__name__}: {exc}",
                    )
                )
                logger.error(
                    "unexpected failure running spec %s: %s: %s",
                    spec.name,
                    type(exc).__name__,
                    exc,
                )
        return outcomes

    @staticmethod
    def _call_failed(
        outcome: TriggerOutcome, step: str, exc: Exception, party: str = "gate"
    ) -> TriggerOutcome:
        """Record that this spec ended with no verdict, and who lost it.

        Kept apart from the other two outcomes on purpose. A refusal means the gate
        answered "no" and the question is settled. A declined proposal means Forge
        answered "no". Neither says anything here: this spec has **no result at
        all**, and nothing may be inferred about whether the repair was needed.

        ``party`` is the difference between "nobody answered" and "we never got as
        far as asking". A payload that could not be built never reaches the
        network, and saying the gate was unreachable sends the reader after the
        wrong component entirely.

        One honest edge case is worth stating rather than hiding. When ``party`` is
        ``gate``, the request may have reached it and only the response been lost,
        so the proposal may exist on the gate under an id this process never
        learned. The record says exactly that — no result known — instead of
        claiming the proposal did not happen.
        """
        outcome.call_failed = True
        outcome.failed_party = party
        outcome.call_detail = f"{step} failed ({type(exc).__name__}: {exc})"
        logger.warning(
            "no verdict for %s at %s, party=%s: %s",
            outcome.spec,
            step,
            party,
            outcome.call_detail,
        )
        return outcome

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
            # Forge raising is not Forge declining. Reporting a crash as "no
            # proposal" would put a broken proposer and a healthy one in the same
            # bucket, and only one of them needs fixing.
            outcome.proposal_detail = f"{type(exc).__name__}: {exc}"
            return self._call_failed(outcome, "propose", exc, party="forge")

        # The proposer only emits when the command genuinely went failing to
        # passing. If it did not, there is nothing honest to file.
        if not getattr(proposal, "fixed", False):
            outcome.proposal_detail = str(getattr(proposal, "reason", "proposer declined"))
            logger.info("proposal declined for %s: %s", spec.name, outcome.proposal_detail)
            return outcome

        outcome.test_proved = True
        try:
            request = proposal.to_request(spec.repo_path)
        except Exception as exc:  # nothing has been sent yet
            # The gate has not been asked and never will be for this spec. Saying
            # otherwise points the reader at a service that was never involved.
            return self._call_failed(outcome, "building the proposal payload", exc, party="local")
        try:
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
        except Exception as exc:  # one spec, one lost result
            return self._call_failed(outcome, "propose", exc)
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
            # A deployment fault, not a result about this spec. Let it out.
            raise
        except Exception as exc:
            # The proposal is not undone by the reviewer failing, so it stays
            # reported. But this spec now has no verdict at all, and saying
            # nothing about that would let the pass look complete.
            outcome.review_detail = f"{type(exc).__name__}: {exc}"
            return self._call_failed(outcome, "review", exc, party="sentinel")

        outcome.findings = [str(r) for r in getattr(reviewed, "reasons", [])]
        document = reviewed.review.to_document()
        try:
            review_result = await self._client.post(
                f"/api/self-repair/{outcome.patch_id}/review", {"document": document}
            )
        except Exception as exc:  # the proposal stands; the review is unknown
            # The proposal is not undone by a failed review call. Keep it: the gate
            # holds a PROPOSED patch with no review, which is a safe and truthful
            # state, and throwing that away would discard work that did succeed.
            return self._call_failed(outcome, "review", exc)
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
    lost = [o for o in outcomes if o.call_failed]
    lines += [
        "",
        f"  specs attempted     : {len(outcomes)}",
        f"  proposals filed     : {sum(1 for o in outcomes if o.proposed)}",
        f"  reviews accepted    : {len(waiting)}",
        f"  waiting on the owner: {len(waiting)}  (this trigger never approves or applies)",
        f"  no verdict reached  : {len(lost)}",
    ]
    if lost:
        # Without this, a run that could not finish prints zeros that read exactly
        # like a run that had nothing to do. The breakdown is here so the reader
        # knows which component to go and look at.
        breakdown = ", ".join(
            f"{party or 'unknown'} {sum(1 for o in lost if o.failed_party == party)}"
            for party in sorted({o.failed_party for o in lost})
        )
        lines += [
            f"  unfinished by party: {breakdown}",
            "",
            f"  INCOMPLETE PASS: {len(lost)} of {len(outcomes)} spec(s) reached no verdict. "
            "The counts above are NOT evidence that nothing was wrong with them.",
        ]
    return "\n".join(lines)


def outcomes_as_json(outcomes: list[TriggerOutcome]) -> str:
    return json.dumps([o.as_dict() for o in outcomes], indent=2)
