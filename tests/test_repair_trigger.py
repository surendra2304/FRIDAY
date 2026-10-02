"""Tests for the Phase F2 repair trigger, and for the runner that exercises it.

The trigger is the piece that makes gated self-repair reachable in operation,
and its whole value is in what it *refuses* to do. It may propose, review and
verify. It may not approve and it may not apply. If that restriction were ever
softened by a stray call, every other guarantee in the loop would still look
intact while the gate quietly stopped meaning anything.

So most of these tests are about restraint, and two of them are structural: they
read the source, because a guarantee that only exists in a comment is not a
guarantee.
"""

from __future__ import annotations

import ast
import json
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest

from friday.autonomous.repair_trigger import (
    HttpxGateClient,
    RepairTrigger,
    TriggerNotConfigured,
    TriggerOutcome,
    WatchSpec,
    outcomes_as_json,
    render_summary,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "friday" / "autonomous"
TRIGGER = SRC / "repair_trigger.py"
RUNNER = Path(__file__).resolve().parents[1] / "research" / "repair_trigger_run.py"


# ── stand-ins for the two services the trigger is allowed to drive ────────


class _TestRun:
    def __init__(self, passed: bool) -> None:
        self.passed = passed
        self.command = "pytest -q"
        self.returncode = 0 if passed else 1
        self.stdout = "1 passed" if passed else "1 failed"
        self.stderr = ""
        self.duration_ms = 12

    def as_evidence(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "passed": self.passed,
            "summary": self.stdout,
            "returncode": self.returncode,
        }


class _Request:
    def __init__(self, spec: WatchSpec) -> None:
        self.repo_path = spec.repo_path
        self.branch = spec.branch
        self.base_commit = spec.base_commit
        self.target_file = spec.target_file
        self.original_snippet = spec.original_snippet
        self.replacement_snippet = spec.replacement_snippet
        self.rationale = spec.rationale
        self.proposed_by = "forge"
        self.test_evidence = _TestRun(True).as_evidence()


class _Outcome:
    def __init__(self, fixed: bool, reason: str = "") -> None:
        self.fixed = fixed
        self.before = _TestRun(not fixed)
        self.after = _TestRun(True) if fixed else None
        self.reason = reason or ("proposer declined" if not fixed else "")

    def to_request(self, repo_path: str) -> _Request:
        if not self.fixed:
            raise RuntimeError("refusing to emit a proposal")
        return _Request(_SPEC)


class _Document:
    def __init__(self, signature: str = "deadbeef") -> None:
        self.signature = signature

    def to_document(self) -> dict[str, Any]:
        return {"patch_fingerprint": "fp_1", "signature": self.signature}


class _Review:
    def __init__(self, signature: str = "deadbeef") -> None:
        self.reasons = ["touches one file", "test evidence present"]
        self.review = _Document(signature)
        self.action = "propose_for_approval"


class _Proposer:
    """Stands in for Forge. Records what it was asked to do."""

    def __init__(self, fixed: bool = True, raises: Exception | None = None,
                 raise_first_only: bool = False) -> None:
        self.fixed = fixed
        self.raises = raises
        self.raise_first_only = raise_first_only
        self.calls: list[dict[str, Any]] = []

    async def propose(self, **kwargs: Any) -> _Outcome:
        self.calls.append(kwargs)
        if self.raises is not None and not (
            self.raise_first_only and len(self.calls) > 1
        ):
            raise self.raises
        return _Outcome(self.fixed, "the test still fails after the change (exit=1)")


class _Reviewer:
    def __init__(self, raises: Exception | None = None) -> None:
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    def review(self, *, patch_fingerprint: str, **kwargs: Any) -> _Review:
        self.calls.append({"patch_fingerprint": patch_fingerprint, **kwargs})
        if self.raises is not None:
            raise self.raises
        return _Review()


class _Gate:
    """A gate that answers whatever the test tells it to, and records the paths."""

    def __init__(self, proposal_outcome: str = "ACCEPTED", review_outcome: str = "ACCEPTED",
                 signature_verified: bool = True) -> None:
        self.paths: list[str] = []
        self.bodies: list[dict[str, Any]] = []
        self.proposal_outcome = proposal_outcome
        self.review_outcome = review_outcome
        self.signature_verified = signature_verified
        #: 1-based call numbers that raise instead of answering, e.g. {2}.
        self.fail_on: set[int] = set()

    async def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.paths.append(path)
        self.bodies.append(body)
        if len(self.paths) in self.fail_on:
            raise httpx.ConnectError("connection refused")
        if path.endswith("/proposals"):
            return {
                "receipt": {
                    "outcome": self.proposal_outcome,
                    "detail": "proposal accepted" if self.proposal_outcome == "ACCEPTED"
                    else "refused",
                },
                "record": {"patch_id": "patch_0001", "fingerprint": "fp_1"},
            }
        return {
            "receipt": {"outcome": self.review_outcome, "detail": "signed review verified"},
            "record": {"review": {"signature_verified": self.signature_verified}},
        }


_SPEC = WatchSpec(
    name="describe-double-scales",
    repo_path="/tmp/repo",
    base_commit="abc123",
    branch="repair/percent-change",
    target_file="percent_change.py",
    original_snippet="    return f'{pct}%'\n",
    replacement_snippet="    return f'{pct:.2f}%'\n",
    rationale="percent_change already returns a percentage",
    test_command="pytest -q",
    env={"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
)


def _trigger(gate: _Gate, proposer: _Proposer | None = None, reviewer: _Reviewer | None = None):
    return RepairTrigger(
        gate,
        proposal_factory=lambda: proposer or _Proposer(),
        reviewer_factory=lambda: reviewer or _Reviewer(),
    )


# ── the happy path, and exactly how far it goes ───────────────────────────


@pytest.mark.asyncio
async def test_a_proved_repair_reaches_reviewed_and_waits_for_the_owner():
    gate = _Gate()
    outcome = await _trigger(gate).run_spec(_SPEC)

    assert outcome.proposed is True
    assert outcome.patch_id == "patch_0001"
    assert outcome.test_proved is True
    assert outcome.review_filed is True
    assert outcome.review_outcome == "ACCEPTED"
    assert outcome.waiting_on_owner is True
    assert outcome.signature_verified is True
    assert outcome.summary.endswith("REVIEWED and waiting on the owner")


@pytest.mark.asyncio
async def test_the_trigger_calls_only_the_two_paths_that_cannot_write():
    gate = _Gate()
    await _trigger(gate).run_spec(_SPEC)
    assert gate.paths == [
        "/api/self-repair/proposals",
        "/api/self-repair/patch_0001/review",
    ]


@pytest.mark.asyncio
async def test_the_proposal_carries_the_real_test_evidence_and_not_a_claim():
    gate = _Gate()
    proposer = _Proposer()
    await _trigger(gate, proposer).run_spec(_SPEC)

    body = gate.bodies[0]
    assert body["test_evidence"]["passed"] is True
    assert body["test_evidence"]["command"] == "pytest -q"
    assert body["target_file"] == "percent_change.py"
    assert gate.bodies[1]["document"]["signature"] == "deadbeef"


@pytest.mark.asyncio
async def test_the_reviewer_is_handed_the_gate_fingerprint_not_a_local_one():
    """A review must bind to what the gate stored, or the gate refuses it."""
    gate = _Gate()
    reviewer = _Reviewer()
    await _trigger(gate, reviewer=reviewer).run_spec(_SPEC)
    assert reviewer.calls[0]["patch_fingerprint"] == "fp_1"


def gate_seen_proposal_body(gate: _Gate) -> dict[str, Any]:
    """The first body the gate received."""
    return gate.bodies[0]


# ── every refusal path ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_declined_candidate_files_nothing_at_all():
    gate = _Gate()
    outcome = await _trigger(gate, _Proposer(fixed=False)).run_spec(_SPEC)

    assert outcome.proposed is False
    assert outcome.review_filed is False
    assert gate.paths == [], "a declined candidate must not reach the gate at all"
    assert "the test still fails after the change" in outcome.proposal_detail


@pytest.mark.asyncio
async def test_a_refused_proposal_is_never_reviewed():
    """Filing a review for a patch the gate never stored would be a phantom."""
    gate = _Gate(proposal_outcome="REFUSED")
    reviewer = _Reviewer()
    outcome = await _trigger(gate, reviewer=reviewer).run_spec(_SPEC)

    assert outcome.proposed is False
    assert outcome.review_filed is False
    assert reviewer.calls == []
    assert gate.paths == ["/api/self-repair/proposals"]


@pytest.mark.asyncio
async def test_an_unverified_signature_is_not_reported_as_waiting_on_the_owner():
    """The gate accepted the document but could not verify it. That is a refusal."""
    gate = _Gate(review_outcome="REFUSED", signature_verified=False)
    outcome = await _trigger(gate).run_spec(_SPEC)

    assert outcome.proposed is True
    assert outcome.review_filed is True
    assert outcome.review_outcome == "REFUSED"
    assert outcome.waiting_on_owner is False
    assert outcome.signature_verified is False


@pytest.mark.asyncio
async def test_one_broken_repository_does_not_stop_the_others():
    gate = _Gate()
    trigger = _trigger(
        gate,
        _Proposer(raises=RuntimeError("not a git repository: /tmp/repo"), raise_first_only=True),
    )
    outcomes = await trigger.run_once([_SPEC, WatchSpec(**{**_SPEC.as_dict(), "name": "second"})])

    assert [o.spec for o in outcomes] == ["describe-double-scales", "second"]
    assert outcomes[0].proposed is False
    assert "RuntimeError" in outcomes[0].proposal_detail
    # Both specs ran; the failure was contained rather than raised out of the pass.
    assert outcomes[1].proposed is True


@pytest.mark.asyncio
async def test_a_reviewer_that_raises_leaves_the_patch_proposed_not_reviewed():
    gate = _Gate()
    outcome = await _trigger(gate, reviewer=_Reviewer(raises=ValueError("no signing key"))).run_spec(
        _SPEC
    )
    assert outcome.proposed is True
    assert outcome.review_filed is False
    assert outcome.waiting_on_owner is False
    assert "no signing key" in outcome.review_detail
    assert gate.paths == ["/api/self-repair/proposals"]


@pytest.mark.asyncio
async def test_the_trigger_refuses_to_guess_a_repair_with_no_proposer():
    """An inert trigger must not report a plausible-looking 'no proposal'.

    Returned as an outcome it would be indistinguishable from a fleet where
    nothing was broken — the failure mode this whole project exists to avoid.
    """
    trigger = RepairTrigger(_Gate())
    with pytest.raises(TriggerNotConfigured, match="refuses to guess at a repair"):
        await trigger.run_spec(_SPEC)


@pytest.mark.asyncio
async def test_the_trigger_refuses_to_file_an_unsigned_review_with_no_reviewer():
    """A review with no signer is one the gate will refuse; do not spend the attempt."""
    trigger = RepairTrigger(_Gate(), proposal_factory=_Proposer)
    with pytest.raises(TriggerNotConfigured, match="will not file an unsigned review"):
        await trigger.run_spec(_SPEC)


# ── a call that fails must cost its own spec and nothing else ─────────────


@pytest.mark.asyncio
async def test_a_failed_propose_call_is_recorded_and_does_not_abort_the_pass():
    """The flakiest dependency in the system is the network. One call, one spec."""
    gate = _Gate()
    gate.fail_on = {1}
    specs = [_SPEC, WatchSpec(**{**_SPEC.as_dict(), "name": "second"})]

    outcomes = await _trigger(gate).run_once(specs)

    assert [o.spec for o in outcomes] == ["describe-double-scales", "second"]
    first, second = outcomes

    assert first.call_failed is True
    assert first.has_result is False
    assert "ConnectError" in first.call_detail
    assert "NO RESULT" in first.summary
    # It must not read as a settled "no", which is what a refusal or a declined
    # proposal means.
    assert not first.summary.startswith("describe-double-scales: no proposal")

    # The second spec is unaffected, and its real result is intact.
    assert second.call_failed is False
    assert second.proposed is True
    assert second.waiting_on_owner is True


@pytest.mark.asyncio
async def test_a_failed_review_call_keeps_the_proposal_that_already_succeeded():
    """Work that succeeded is not undone by the next call failing."""
    gate = _Gate()
    gate.fail_on = {2}  # the review call
    outcome = await _trigger(gate).run_spec(_SPEC)

    assert outcome.call_failed is True
    assert outcome.has_result is False
    # The proposal really was filed, and that fact survives the review failing.
    assert outcome.proposed is True
    assert outcome.patch_id == "patch_0001"
    assert outcome.test_proved is True
    # And it is honest about not knowing how the review landed.
    assert outcome.review_filed is False
    assert outcome.waiting_on_owner is False
    assert "review call failed" in outcome.call_detail


@pytest.mark.asyncio
async def test_a_refused_call_is_not_reported_as_a_failed_call():
    """Three distinct things: a refusal, a decline, and no answer at all."""
    refused = await _trigger(_Gate(proposal_outcome="REFUSED")).run_spec(_SPEC)
    assert refused.call_failed is False
    assert refused.has_result is True

    declined = await _trigger(_Gate(), _Proposer(fixed=False)).run_spec(_SPEC)
    assert declined.call_failed is False
    assert declined.has_result is True
    assert "no proposal" in declined.summary


@pytest.mark.asyncio
async def test_a_failure_on_the_last_spec_still_returns_the_earlier_ones():
    """Work already done is never discarded by what happens afterwards."""
    gate = _Gate()
    gate.fail_on = {5, 6}  # both calls of the third spec
    specs = [_SPEC, WatchSpec(**{**_SPEC.as_dict(), "name": "second"}),
             WatchSpec(**{**_SPEC.as_dict(), "name": "third"})]

    outcomes = await _trigger(gate).run_once(specs)

    assert [(o.spec, o.proposed, o.call_failed) for o in outcomes] == [
        ("describe-double-scales", True, False),
        ("second", True, False),
        ("third", False, True),
    ]


@pytest.mark.asyncio
async def test_an_unexpected_error_in_one_spec_is_contained_not_raised():
    """The net under everything run_spec knows about."""

    class Exploding:
        async def propose(self, **kwargs: Any) -> Any:
            raise KeyboardInterrupt  # not an Exception: must still escape

    class Fine:
        async def propose(self, **kwargs: Any) -> Any:
            return _Outcome(True)

    trigger = RepairTrigger(_Gate(), proposal_factory=lambda: Exploding())
    with pytest.raises(KeyboardInterrupt):
        await trigger.run_once([_SPEC])

    # An ordinary error is contained and labelled as a lost result.
    trigger = RepairTrigger(
        _Gate(), proposal_factory=lambda: Fine(), candidate_factory=_boom
    )
    outcomes = await trigger.run_once([_SPEC])
    assert outcomes[0].call_failed is True
    assert "unexpected failure" in outcomes[0].call_detail
    assert "NO RESULT" in outcomes[0].summary


def _boom(spec: WatchSpec) -> Any:
    raise ValueError("cannot build a candidate for this spec")


# ── the same thing again, against a real socket ──────────────────────────
#
# The tests above hand the trigger a stub that raises. This one gives it the real
# production client pointed at a real HTTP server on a real port, and makes that
# server genuinely drop one connection mid-pass. Nothing is mocked: the failure is
# a socket closing without a response, which is what a free-tier host waking up or
# a load balancer cutting a request actually looks like.


class _DroppingGate:
    """A real threaded HTTP server that answers, except on one chosen call."""

    def __init__(self, fail_on_call: int) -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.requests = 0
        fail_on_call = fail_on_call
        gate = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # keep the transcript clean
                return

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
                gate.requests += 1
                length = int(self.headers.get("content-length") or 0)
                self.rfile.read(length)
                if gate.requests == fail_on_call:
                    # Drop the connection with no response at all.
                    self.close_connection = True
                    self.connection.close()
                    return
                body = json.dumps(
                    {
                        "receipt": {"outcome": "ACCEPTED", "detail": "accepted"},
                        "record": {
                            "patch_id": "patch_0001",
                            "fingerprint": "fp_1",
                            "review": {"signature_verified": True},
                        },
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=10)


@pytest.mark.parametrize(
    ("fail_on_call", "lost_spec", "lost_step", "kept_proposed", "calls_made", "filed"),
    [
        # call 2 is the first spec's review: its proposal already landed, so the
        # pass still makes all six calls and still counts three proposals.
        (2, "first", "review", True, 6, 3),
        # call 3 is the second spec's propose: no review follows it, so five calls.
        (3, "second", "propose", False, 5, 2),
    ],
)
@pytest.mark.asyncio
async def test_a_real_dropped_connection_costs_one_spec_and_nothing_else(
    fail_on_call: int,
    lost_spec: str,
    lost_step: str,
    kept_proposed: bool,
    calls_made: int,
    filed: int,
):
    """Real client, real server, real transport failure, mid-pass.

    Both halves matter. A dropped *propose* loses that spec entirely. A dropped
    *review* must not undo the proposal that already landed on the gate, because
    the gate is now holding a PROPOSED patch with no review and throwing that
    away would discard work that genuinely succeeded.
    """
    gate = _DroppingGate(fail_on_call=fail_on_call)
    try:
        specs = [
            WatchSpec(**{**_SPEC.as_dict(), "name": name})
            for name in ("first", "second", "third")
        ]
        trigger = RepairTrigger(
            HttpxGateClient(gate.base_url, api_key="k", timeout=10.0),
            proposal_factory=_Proposer,
            reviewer_factory=_Reviewer,
        )
        outcomes = await trigger.run_once(specs)
    finally:
        gate.close()

    assert gate.requests == calls_made, (
        "the run stopped early instead of finishing the pass"
    )

    lost = next(o for o in outcomes if o.spec == lost_spec)
    assert lost.call_failed is True
    assert lost.has_result is False
    assert f"{lost_step} call failed" in lost.call_detail
    assert "RemoteProtocolError" in lost.call_detail
    assert "NO RESULT" in lost.summary
    # Whatever had already succeeded for this spec is still reported.
    assert lost.proposed is kept_proposed

    healthy = [o for o in outcomes if o.spec != lost_spec]
    assert len(healthy) == 2
    for outcome in healthy:
        assert outcome.call_failed is False
        assert outcome.proposed is True
        assert outcome.waiting_on_owner is True

    text = render_summary(outcomes)
    assert "no result at all    : 1" in text
    assert "INCOMPLETE PASS" in text
    assert f"proposals filed     : {filed}" in text


# ── structural guarantees, read from the source ───────────────────────────


def test_the_gate_client_type_has_no_approve_and_no_apply():
    """The restriction is the type. A method would be a way around it."""
    for forbidden in ("approve", "apply", "rollback", "owner_decision"):
        assert not hasattr(HttpxGateClient, forbidden), (
            f"HttpxGateClient gained {forbidden}; the trigger must not be able to "
            "write, and the way to guarantee that is the absence of the method"
        )


def test_the_module_never_imports_a_sibling_service():
    """FRIDAY has no cross-repo imports anywhere in src/. This must stay true."""
    tree = ast.parse(TRIGGER.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(name.startswith(("app.", "sentinel.")) for name in imported), (
        f"the trigger imports a sibling service directly: {sorted(imported)}"
    )


def test_the_module_names_no_endpoint_that_can_write():
    """Enumerated from the source, so adding one is a visible change here.

    ``/api/self-repair/{id}/owner-decision``, ``.../apply`` and ``.../rollback``
    are the three endpoints that change a repository or an approval. The trigger
    may not name any of them.
    """
    source = TRIGGER.read_text(encoding="utf-8")
    for forbidden in ("owner-decision", "/apply", "/rollback"):
        assert forbidden not in source, (
            f"the trigger references {forbidden!r}; that endpoint can write, and "
            "this module's whole value is that it cannot"
        )
    # The two it is allowed to use, spelled out so the guarantee is symmetric.
    assert '"/api/self-repair/proposals"' in source
    assert 'f"/api/self-repair/{outcome.patch_id}/review"' in source


# ── the runner that exercises it over real HTTP ───────────────────────────


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_the_runner_does_not_import_the_gate_it_is_proving():
    """Same property as the E1 driver: the gate must be reached over HTTP."""
    assert "friday.autonomous.self_repair" not in _imported_modules(RUNNER), (
        "the runner imports the gate module, so it could call it directly instead "
        "of over HTTP; that would not prove the deployed surface"
    )


def test_the_runner_uses_the_real_sibling_implementations():
    modules = _imported_modules(RUNNER)
    assert "app.selfrepair.proposer" in modules, "Forge's real proposer is not imported"
    assert "sentinel.core.selfrepair.reviewer" in modules, (
        "Sentinel's real reviewer is not imported"
    )


def test_the_runner_starts_the_gate_as_a_separate_process():
    """It reuses the E1 driver's server rather than duplicating it — check that
    the thing it reuses is a real subprocess serving the real application."""
    source = RUNNER.read_text(encoding="utf-8")
    assert "from self_repair_loop import" in source and "GateServer" in source
    assert "server.start()" in source and "wait_until_serving" in source

    loop = Path(__file__).resolve().parents[1] / "research" / "self_repair_loop.py"
    loop_source = loop.read_text(encoding="utf-8")
    assert "uvicorn" in loop_source and "friday.api.server:app" in loop_source
    assert "subprocess.Popen" in loop_source


def test_the_runner_labels_its_own_limits_instead_of_implying_a_live_proof():
    """A transcript that does not say it is local will be read as a live claim."""
    source = RUNNER.read_text(encoding="utf-8").lower()
    assert "local, not live" in source, "the runner must state it is not a deployed service"
    assert "not a deployed service" in source
    assert "not deployment secrets" in source, "the key literals must be labelled as literals"
    assert "simulated" in source, "the owner decision must be labelled as a caller, not a human"


def test_the_runner_keeps_reviewer_state_out_of_the_repository_under_repair():
    """A review audit trail inside the caller's repo is untracked noise in their diff."""
    source = RUNNER.read_text(encoding="utf-8")
    assert 'db_path=str(repo / "sentinel.db")' not in source, (
        "the reviewer is writing its database into the repository it is auditing"
    )
    assert 'repo.parent / "reviewer-state"' in source


# ── reporting ─────────────────────────────────────────────────────────────


def test_render_summary_reports_the_halves_separately():
    gate = _Gate()
    outcomes = [
        TriggerOutcome(spec="a", proposed=True, patch_id="patch_0001", review_filed=True,
                       waiting_on_owner=True),
        TriggerOutcome(spec="b", proposed=False, proposal_detail="test still fails"),
    ]
    text = render_summary(outcomes)
    assert "specs attempted     : 2" in text
    assert "proposals filed     : 1" in text
    assert "this trigger never approves or applies" in text
    assert "test still fails" in text
    assert "INCOMPLETE PASS" not in text, "a clean pass must not cry wolf"
    assert "no result at all    : 0" in text


def test_render_summary_cannot_present_a_lost_call_as_a_quiet_pass():
    """The failure mode this guards: zeros that read like 'nothing was wrong'."""
    outcomes = [
        TriggerOutcome(spec="a", call_failed=True, call_detail="propose call failed: x"),
    ]
    text = render_summary(outcomes)
    assert "proposals filed     : 0" in text
    assert "no result at all    : 1" in text
    assert "INCOMPLETE PASS" in text
    assert "NOT evidence that nothing was wrong" in text
    assert "NO RESULT" in text


def test_outcomes_json_keeps_a_lost_call_visible_to_whatever_reads_it():
    """A dashboard built on as_dict must not be able to drop the negative."""
    payload = json.loads(
        outcomes_as_json([TriggerOutcome(spec="a", call_failed=True, call_detail="boom")])
    )[0]
    assert payload["call_failed"] is True
    assert payload["call_detail"] == "boom"
    assert payload["waiting_on_owner"] is False


def test_outcomes_are_json_serialisable_and_keep_the_negative_facts():
    """A negative result must survive serialisation, or a dashboard will hide it."""
    outcome = TriggerOutcome(
        spec="b",
        proposed=False,
        proposal_detail="the snippet is not present",
        review_filed=False,
        signature_verified=False,
        findings=["nothing was filed"],
    )
    payload = json.loads(outcomes_as_json([outcome]))[0]
    assert payload["proposed"] is False
    assert payload["signature_verified"] is False
    assert payload["waiting_on_owner"] is False
    assert payload["proposal_detail"] == "the snippet is not present"


def test_a_watch_spec_round_trips_through_json():
    """Specs come from configuration, so a lost field is a silent no-op repair."""
    assert WatchSpec.from_dict(_SPEC.as_dict()) == _SPEC
