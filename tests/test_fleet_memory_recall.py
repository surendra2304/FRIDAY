"""Fleet memory: asking what the other agents remember, before asking them to act.

The owner's requirement, in their words: the agents must "recall memories,
communicate with each other, fix their own systems, and help each other".

This pins the recall half against the real contracts, in process. The peer side here
is the contract harness — the same one the mesh's own tests use — so an unreachable
peer, a peer answering without a receipt and a peer with a memory are three different
things produced by the same code path the wire uses. What the *live* Memora and the
other seven peers do with a `memory_recall` action is CONFIGURED-BUT-UNVERIFIED on
this host: there is no egress from this sandbox, so nothing here claims a live peer
answered, and the tests say so rather than implying it.

The rule this file exists to protect: a recalled memory is knowledge, not work. It
names the peer it came from and whether that peer says it verified the repair it came
from; it never counts as help performed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from friday.cognition.assistance import AssistanceBroker, _memories_from
from friday.cognition.mesh import ContractTransport, HarnessBehaviour, Mesh, build_contracts
from friday.cognition.reflex import (
    Incident,
    IncidentKind,
    IncidentSeverity,
    OutcomeStatus,
    ReflexBrain,
)


def _mesh(*, request_timeout: float = 30.0) -> tuple[Mesh, ContractTransport]:
    contracts = build_contracts()
    for contract in contracts.values():
        contract.api_key = contract.api_key or "peer-key"
    mesh, harness = Mesh.in_process(
        contracts, backoff_seconds=0.0, attempts=1, request_timeout=request_timeout
    )
    return mesh, harness


def _memories(*memories: object) -> HarnessBehaviour:
    """A peer that answers the task normally and also reports what it remembers.

    The receipt is the harness's own, built for the peer that was actually asked -
    hand-writing one is how the first draft of this file produced a target mismatch
    and proved `verify_receipt` right.
    """
    return HarnessBehaviour(result={"memories": list(memories)})


def _first_peer(mesh: Mesh) -> str:
    return sorted(mesh.contracts)[0]


def _incident() -> Incident:
    return Incident(
        kind=IncidentKind.TEST_FAILURE,
        severity=IncidentSeverity.HIGH,
        source="tests/test_calc.py::test_add",
        summary="NameError: name 'totl' is not defined",
        evidence={
            "test_node_id": "tests/test_calc.py::test_add",
            "source_file": "src/friday/calc.py",
        },
    )


# ── the recall itself ─────────────────────────────────────────────────────────


def test_a_peer_that_remembers_is_reported_with_its_own_attribution() -> None:
    mesh, harness = _mesh()
    peer = _first_peer(mesh)
    harness.behave(
        peer,
        _memories(
            {
                "capability": "source_repair",
                "answer": "the same NameError was fixed by adding the missing import",
                "verified": True,
            }
        ),
    )

    recalled = asyncio.run(
        AssistanceBroker(mesh=mesh).recall_from_peers(
            "source_repair", question="NameError in src/friday/calc.py"
        )
    )

    assert recalled["answered_by"] == [peer], recalled
    assert len(recalled["memories"]) == 1
    memory = recalled["memories"][0]
    assert memory["peer"] == peer, "a memory must name where it came from"
    assert memory["capability"] == "source_repair"
    assert "missing import" in memory["answer"]
    assert memory["peer_says_verified"] is True
    assert "remembered this kind of fault" in recalled["reason"]

    # The question went out on the wire as a typed task, not as prose.
    recall_calls = [
        call for call in harness.calls if call.json_body.get("action") == "memory_recall"
    ]
    assert recall_calls, [call.json_body for call in harness.calls]
    assert recall_calls[0].json_body["capability"] == "source_repair"


def test_a_memory_about_something_else_is_dropped_not_used_to_target() -> None:
    """Retrieving the wrong thing confidently is worse than retrieving nothing."""
    mesh, harness = _mesh()
    peer = _first_peer(mesh)
    harness.behave(
        peer,
        _memories(
            {"capability": "scheduling", "answer": "I moved the standup to 9am"},
            {"capability": "source_repair", "answer": ""},
            "a memory that is not even an object",
        ),
    )

    recalled = asyncio.run(AssistanceBroker(mesh=mesh).recall_from_peers("source_repair"))

    assert recalled["memories"] == []
    assert recalled["answered_by"] == []
    # The peers that got the ordinary answer are empty too; only this peer had
    # anything to say, and what it said was not usable.
    assert peer in recalled["answered_but_empty"]
    reasons = [item["reason"] for item in recalled["dropped"]]
    assert "about a different capability" in reasons
    assert "carries no answer" in reasons
    assert "not a memory object" in reasons


def test_an_answer_without_a_receipt_is_not_a_memory() -> None:
    """The same rule as everywhere else: no verified receipt, no completion."""
    mesh, harness = _mesh()
    for peer in mesh.contracts:
        harness.behave(peer, HarnessBehaviour(result={"memories": [{"capability": "source_repair", "answer": "trust me"}]}, receipt=False))

    recalled = asyncio.run(AssistanceBroker(mesh=mesh).recall_from_peers("source_repair"))

    assert recalled["memories"] == [], "an unverified answer was accepted as memory"
    assert recalled["answered_by"] == []
    assert set(recalled["answered_but_empty"]) == set()


def test_an_unreachable_peer_is_not_a_peer_with_nothing_to_say() -> None:
    """An unreachable peer and an empty answer are different facts."""
    mesh, harness = _mesh()
    quiet, broken = sorted(mesh.contracts)[:2]
    harness.behave(quiet, _memories())
    harness.behave(broken, HarnessBehaviour(raise_transport_error=True))

    recalled = asyncio.run(AssistanceBroker(mesh=mesh).recall_from_peers("source_repair"))

    assert broken in recalled["unreachable"], recalled["attempts"][broken]
    assert quiet in recalled["answered_but_empty"]
    assert broken not in recalled["answered_but_empty"]


def test_asking_yourself_is_refused_rather_than_counted() -> None:
    mesh, _harness = _mesh()
    caller = _first_peer(mesh)

    recalled = asyncio.run(
        AssistanceBroker(mesh=mesh).recall_from_peers(
            "source_repair", caller=caller, peers=(caller,)
        )
    )

    assert recalled["asked"] == []
    assert recalled["excluded"] == [caller]
    assert "asking yourself is not an attempt" in recalled["reason"]
    assert recalled["memories"] == []


def test_no_mesh_is_said_plainly(monkeypatch: pytest.MonkeyPatch) -> None:
    broker = AssistanceBroker(mesh=None)
    # `mesh=None` means "build the configured one", so the unavailability has to be
    # pinned the way it happens in the world: the accessor answers None.
    monkeypatch.setattr(broker, "mesh", lambda: None)

    recalled = asyncio.run(broker.recall_from_peers("source_repair"))
    assert recalled["memories"] == []
    assert recalled["asked"] == []
    assert recalled["reason"] == "no mesh client is attached, so no peer could be asked"


def test_a_memory_that_is_not_shaped_like_one_is_dropped_with_the_reason() -> None:
    class Outcome:
        result = {"memories": "not a list"}

    accepted, dropped = _memories_from("memora", Outcome(), "source_repair")
    assert accepted == []
    assert dropped == []

    class Weird:
        result = {"memories": [None, 7, {"answer": "no capability stated"}]}

    accepted, dropped = _memories_from("memora", Weird(), "source_repair")
    assert len(accepted) == 1, "a memory with no capability is for the capability asked about"
    assert accepted[0]["peer"] == "memora"
    assert [item["reason"] for item in dropped] == ["not a memory object", "not a memory object"]


# ── the reflex uses the fleet's memory to aim its request ─────────────────────


def test_the_reflex_asks_the_peer_that_remembers_instead_of_broadcasting(tmp_path: Path) -> None:
    mesh, harness = _mesh()
    remembering = _first_peer(mesh)
    others = [peer for peer in mesh.contracts if peer != remembering]
    harness.behave(
        remembering,
        _memories(
            {
                "capability": "source_repair",
                "answer": "the missing name was a one-character typo; the fix committed",
                "verified": True,
            }
        ),
    )
    brain = ReflexBrain(tmp_path, mesh=mesh, enabled=True)

    outcome = asyncio.run(brain.handle(_incident()))

    assert outcome.status is OutcomeStatus.RESOLVED, outcome.detail
    delegation = outcome.evidence["delegation"]
    assert delegation["asked"] == [remembering], delegation["asked"]
    assert all(peer not in delegation["asked"] for peer in others)
    assert outcome.evidence["targeted_by_memory"] is True
    assert outcome.evidence["fleet_recall"]["memories"][0]["peer"] == remembering
    assert "memory held a fix" in outcome.detail, outcome.detail


def test_a_fleet_that_does_not_remember_still_gets_asked(tmp_path: Path) -> None:
    """Recall aims the request; it never replaces it."""
    mesh, harness = _mesh()
    for peer in mesh.contracts:
        harness.behave(peer, _memories())
    brain = ReflexBrain(tmp_path, mesh=mesh, enabled=True)

    outcome = asyncio.run(brain.handle(_incident()))

    assert outcome.status is OutcomeStatus.RESOLVED, outcome.detail
    delegation = outcome.evidence["delegation"]
    assert set(delegation["asked"]) == set(mesh.contracts), delegation["asked"]
    assert outcome.evidence["targeted_by_memory"] is False
    recall = outcome.evidence["fleet_recall"]
    assert recall["reason"] == "no peer remembered this kind of fault", recall
    assert recall["memories"] == [] and recall["answered_by"] == []


def test_a_peer_that_remembers_but_cannot_do_the_work_is_reported_as_such(tmp_path: Path) -> None:
    """Knowledge and capability are different, and the outcome keeps them apart."""
    mesh, harness = _mesh()
    remembering = _first_peer(mesh)
    harness.behave(
        remembering,
        _memories({"capability": "source_repair", "answer": "I saw this once", "verified": False}),
        action="memory_recall",
    )
    # The same peer will not take the work: authorised to answer, not to act.
    harness.behave(remembering, HarnessBehaviour(status_code=503), action="source_repair")

    brain = ReflexBrain(tmp_path, mesh=mesh, enabled=True)
    outcome = asyncio.run(brain.handle(_incident()))

    assert outcome.status is not OutcomeStatus.RESOLVED, outcome.detail
    escalation = outcome.evidence["peer_escalation"]
    assert escalation["asked"] == [remembering], escalation["asked"]
    assert escalation["completed_by"] is None
    # 503 is DEGRADED: a peer that answered the question and then could not take the
    # work is degraded, not refused, and certainly not completed.
    assert escalation["attempts"][remembering]["state"] == "DEGRADED", escalation["attempts"]
    assert "remembered" in outcome.detail
    # And the sentence must not leave the owner thinking the work happened.
    assert "none of them completed it" in outcome.detail, outcome.detail


def test_recall_is_bounded_and_honest_under_a_hostile_fleet(tmp_path: Path) -> None:
    """Pressure: slow peers, dead peers, and one that remembers, all at once."""
    mesh, harness = _mesh(request_timeout=0.25)
    peers = sorted(mesh.contracts)
    remembering = peers[0]
    harness.behave(
        remembering,
        _memories({"capability": "source_repair", "answer": "one line, one fix", "verified": True}),
    )
    harness.behave(peers[1], HarnessBehaviour(raise_transport_error=True))
    for peer in peers[2:5]:
        harness.behave(peer, HarnessBehaviour(latency_ms=5_000))  # slower than the timeout
    for peer in peers[5:]:
        harness.behave(peer, HarnessBehaviour(status_code=500))

    recalled = asyncio.run(AssistanceBroker(mesh=mesh).recall_from_peers("source_repair"))

    assert recalled["answered_by"] == [remembering], recalled
    assert len(recalled["memories"]) == 1
    assert set(recalled["unreachable"]) == {peers[1], *peers[2:5]}, recalled["unreachable"]
    assert set(recalled["attempts"]) == set(peers), "every peer asked must be accounted for"


@pytest.mark.parametrize("capability", ["source_repair", "resource_pressure"])
def test_recall_works_for_more_than_one_kind_of_capability(capability: str) -> None:
    mesh, harness = _mesh()
    peer = _first_peer(mesh)
    harness.behave(
        peer,
        _memories({"capability": capability, "answer": f"what I know about {capability}", "verified": True}),
    )

    recalled = asyncio.run(AssistanceBroker(mesh=mesh).recall_from_peers(capability))

    assert recalled["answered_by"] == [peer]
    assert recalled["memories"][0]["capability"] == capability


def test_the_wire_shape_is_what_is_read_and_a_flat_answer_still_works() -> None:
    """The first draft of the extractor read a shape no peer sends.

    `PeerOutcome.result` is the whole response body, so a peer's payload is under
    "result", beside the receipt. The extractor was written against a flat
    `{"memories": [...]}` and therefore found nothing in a verified answer - which
    is the bug this test exists to keep fixed. Both shapes are accepted, because a
    contract is read as it arrives.
    """

    class Wire:
        # exactly what the harness (and the live contract) returns
        result = {
            "task_id": "t1",
            "status": "success",
            "summary": "memora completed the task",
            "result": {"memories": [{"capability": "source_repair", "answer": "the fix", "verified": True}]},
            "receipt": {"requested_action": "memory_recall", "target": "memora"},
        }

    class Flat:
        result = {"memories": [{"capability": "source_repair", "answer": "the fix"}]}

    for outcome in (Wire(), Flat()):
        accepted, dropped = _memories_from("memora", outcome, "source_repair")
        assert len(accepted) == 1, (outcome, accepted, dropped)
        assert accepted[0]["answer"] == "the fix"

    class NoMemoriesAnywhere:
        result = {"task_id": "t", "result": {"echo": "objective"}, "receipt": {}}

    accepted, dropped = _memories_from("memora", NoMemoriesAnywhere(), "source_repair")
    assert (accepted, dropped) == ([], [])
