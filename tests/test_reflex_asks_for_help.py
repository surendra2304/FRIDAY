"""The reflex's help ladder: this host first, the peers second, the truth always.

When FRIDAY cannot repair a fault on its own machine, it must not stop at "no
known fix" while eight peers sit unasked. It must also not claim a peer repaired
something unless that peer's receipt verifies. Both halves are pinned here with a
real mesh: a real envelope on the wire, a real receipt, and a real classification.

The peer in the "helped" case is a transport that answers with a verified receipt;
the peers in the "nobody could" case are the harness's own failure modes (401 by
default for a keyed peer without a key, unreachable transport, 202 accepted but
unfinished). Nothing is mocked at the level of the question being asked.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from friday.cognition.mesh import ContractTransport, HarnessBehaviour, Mesh, build_contracts
from friday.cognition.reflex import (
    ActionOutcome,
    Incident,
    IncidentKind,
    IncidentSeverity,
    OutcomeStatus,
    ReflexBrain,
)


def _incident() -> Incident:
    return Incident(
        kind=IncidentKind.TEST_FAILURE,
        severity=IncidentSeverity.HIGH,
        source="tests/test_calc.py::test_add",
        summary="NameError: name 'totl' is not defined",
        evidence={"test_node_id": "tests/test_calc.py::test_add", "source_file": "src/friday/calc.py"},
    )


def _brain(tmp_path: Path, mesh: Mesh | None) -> ReflexBrain:
    return ReflexBrain(tmp_path, mesh=mesh, enabled=True)


def _mesh(*, answer: bool = True) -> tuple[Mesh, ContractTransport]:
    contracts = build_contracts()
    for contract in contracts.values():
        contract.api_key = contract.api_key or "peer-key"
    mesh, harness = Mesh.in_process(contracts, backoff_seconds=0.0)
    if not answer:
        for peer in contracts:
            harness.behave(peer, HarnessBehaviour(raise_transport_error=True))
    return mesh, harness


def test_a_local_fix_is_preferred_and_no_peer_is_asked(tmp_path: Path) -> None:
    """The ladder only goes up when the local rung fails.

    The fake is synchronous because the real `_repair_test_failure` is: it runs in
    a thread precisely because it shells out to pytest.
    """
    mesh, harness = _mesh()
    brain = _brain(tmp_path, mesh)

    called: list[str] = []

    def fake_local(incident: Incident) -> ActionOutcome:
        called.append("local")
        return ActionOutcome(
            incident=incident,
            status=OutcomeStatus.RESOLVED,
            action="propose_review_approve_apply_verify",
            detail="repaired locally",
        )

    brain._repair_test_failure = fake_local  # type: ignore[assignment]
    outcome = asyncio.run(brain.handle(_incident()))

    assert called == ["local"]
    assert outcome.status is OutcomeStatus.RESOLVED
    assert outcome.action == "propose_review_approve_apply_verify"
    assert harness.calls == [], "peers were asked even though the local repair worked"


def test_when_no_local_fix_exists_the_peers_are_asked(tmp_path: Path) -> None:
    mesh, harness = _mesh()
    brain = _brain(tmp_path, mesh)

    outcome = asyncio.run(brain.handle(_incident()))

    assert harness.calls, "the peers were never asked"
    # Every call carried the real envelope for the peer's own task endpoint.
    for call in harness.calls:
        assert call.json_body["task_id"]
        assert call.json_body["target_agent"]
        assert "could not be repaired locally" in call.json_body["objective"]

    assert outcome.status is OutcomeStatus.RESOLVED, outcome.detail
    assert outcome.action == "delegated_to_peer"
    assert outcome.evidence_class == "peer_verified_work"
    assert "not this host's" in outcome.detail
    delegation = outcome.evidence["delegation"]
    assert delegation["performed"] is True
    assert delegation["completed_by"] in delegation["asked"]
    # The peers that did not answer first are reported as they answered, not hidden.
    assert len(delegation["attempts"]) == len(delegation["asked"]) >= 2


def test_a_peer_that_answers_without_a_receipt_never_counts_as_help(tmp_path: Path) -> None:
    mesh, harness = _mesh()
    for peer in mesh.contracts:
        harness.behave(peer, HarnessBehaviour(receipt=False))
    brain = _brain(tmp_path, mesh)

    outcome = asyncio.run(brain.handle(_incident()))

    assert outcome.status is not OutcomeStatus.RESOLVED
    assert outcome.action == "synthesise_patch"
    escalation = outcome.evidence["peer_escalation"]
    assert escalation["performed"] is False
    assert escalation["completed_by"] is None
    assert all(
        attempt["state"] in {"UNVERIFIED", "UNREACHABLE", "REFUSED", "PENDING"}
        for attempt in escalation["attempts"].values()
    )


def test_no_mesh_means_the_local_answer_stands_unchanged(tmp_path: Path) -> None:
    brain = _brain(tmp_path, mesh=None)
    outcome = asyncio.run(brain.handle(_incident()))

    assert outcome.action == "synthesise_patch"
    assert outcome.status is OutcomeStatus.NO_FIX_KNOWN
    assert "peer_escalation" not in outcome.evidence
    assert "No patcher" in outcome.detail


def test_a_mesh_that_raises_while_being_asked_does_not_lose_the_finding(tmp_path: Path) -> None:
    """Help is best-effort: a broken transport must not swallow the incident."""
    mesh, _harness = _mesh()
    mesh.dispatch_many = _boom  # type: ignore[assignment]
    brain = _brain(tmp_path, mesh)

    outcome = asyncio.run(brain.handle(_incident()))

    assert outcome.status is OutcomeStatus.NO_FIX_KNOWN
    assert "asking the peers raised" in outcome.detail
    assert outcome.evidence["peer_escalation_error"].startswith("RuntimeError")


async def _boom(*args, **kwargs):
    raise RuntimeError("the mesh is not answering questions today")


@pytest.mark.parametrize("kind", [IncidentKind.TEST_FAILURE, IncidentKind.IMPORT_FAILURE])
def test_the_ladder_covers_both_repairable_incident_kinds(tmp_path: Path, kind: IncidentKind) -> None:
    mesh, harness = _mesh()
    brain = _brain(tmp_path, mesh)
    incident = Incident(
        kind=kind,
        severity=IncidentSeverity.HIGH,
        source="tests/test_calc.py::test_add",
        summary="the fault",
        evidence={"test_node_id": "tests/test_calc.py::test_add"},
    )

    outcome = asyncio.run(brain.handle(incident))

    assert harness.calls, "the peers were never asked"
    assert outcome.action in {"delegated_to_peer", "synthesise_patch", "report_unproven_fix"}
