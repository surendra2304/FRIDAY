"""Multi-agent help, proved end to end: local agents and real mesh peers.

The failure mode this file exists to catch is a collaboration feature that reports
help it never got. So every assertion here is about what *actually happened*: a
real attempt recorded in the helper's own ledger, a real task envelope sent over a
real transport, a receipt verified before anything is called completed, and a
loopback refused rather than counted.

The peers are not mocks of the broker's expectations: `Mesh.in_process` speaks the
same wire contract a real peer speaks (404 for unknown paths, 401 without a key,
422 for a malformed envelope, signed receipts), and it refuses or delays exactly
when a real service would.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from friday.cognition.assistance import AssistanceBroker
from friday.cognition.memory_bridge import SharedMemory
from friday.cognition.mesh import HarnessBehaviour, Mesh, build_contracts
from friday.cognition.mind import Mind, MindRegistry


def _registry(tmp_path: Path) -> MindRegistry:
    return MindRegistry(memory=SharedMemory(path=str(tmp_path / "episodes.jsonl")))


def _mind(registry: MindRegistry, agent_id: str, *, role: str = "specialist") -> Mind:
    return registry.register(Mind(agent_id=agent_id, role=role, purpose=f"the {role}"))


def _mesh(*, backoff: float = 0.0) -> tuple[Mesh, object]:
    contracts = build_contracts()
    for contract in contracts.values():
        contract.api_key = contract.api_key or "peer-key"
    mesh, harness = Mesh.in_process(contracts, backoff_seconds=backoff)
    return mesh, harness


def test_a_local_agent_that_knows_research_is_chosen_and_its_help_is_recorded(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    researcher = _mind(registry, "intelx", role="research")
    researcher.observe("research", True, detail="found three sources", outcome="SUCCESS")

    async def executor(request: dict) -> str:
        return f"researched {request['objective']} in three sources"

    broker = AssistanceBroker(registry=registry)
    outcome = asyncio.run(
        broker.request_help(
            "friday",
            "research",
            "the current state of the FRIDAY universe",
            local_executor=executor,
        )
    )

    assert outcome.helper == "intelx"
    assert outcome.performed is True, outcome.as_dict()
    assert "three sources" in outcome.answer
    assert "did it" in outcome.spoken()

    # The helper's own ledger now has this attempt, recorded as assistance.
    record = researcher.ledger.get("research")
    assert record is not None and record.attempts == 2, "the helper did not record its own work"
    assert record.successes == 2
    # And the shared memory carries the exchange, so the other agents can learn it.
    recalled = registry.memory.recall("researched the current state", limit=5)
    assert recalled, "the exchange was not remembered for the other agents"


def test_an_agent_without_evidence_refuses_and_the_refusal_is_kept(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    rookies = _mind(registry, "nova", role="generalist")
    rookies.observe("research", False, detail="timed out", outcome="FAILED")

    async def executor(request: dict) -> str:  # must never run
        raise AssertionError("an agent with no evidence must not be made to act")

    broker = AssistanceBroker(registry=registry)
    outcome = asyncio.run(
        broker.request_help("friday", "research", "anything", helper="nova", local_executor=executor)
    )

    assert outcome.state == "REFUSED"
    assert outcome.performed is False
    assert "no evidence" in outcome.refused_because
    assert "did not help" in outcome.spoken()
    assert rookies.ledger.get("research").attempts == 1, "a refusal is not an attempt"


def test_a_loopback_is_refused_rather_than_counted_as_help(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    friday = _mind(registry, "friday", role="primary")
    friday.observe("source_repair", False, detail="the patch did not apply", outcome="FAILED")

    broker = AssistanceBroker(registry=registry)
    outcome = asyncio.run(
        broker.request_help("friday", "source_repair", "repair the failing test", helper="friday")
    )

    assert outcome.state == "BLOCKED"
    assert outcome.performed is False
    assert "loopback" in outcome.refused_because
    assert friday.ledger.get("source_repair").attempts == 1, "the loopback inflated the ledger"


def test_nobody_with_evidence_means_an_honest_no(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _mind(registry, "stratex", role="trading")
    broker = AssistanceBroker(registry=registry)

    outcome = asyncio.run(broker.request_help("friday", "interpret whale movements", "tell me"))

    assert outcome.state == "BLOCKED"
    assert outcome.performed is False
    assert "no agent" in (outcome.reason or "").lower() or "evidence" in (outcome.reason or "").lower()
    consulted = outcome.attempt.get("consult", {})
    assert consulted.get("chosen") is None


def test_a_real_peer_is_asked_over_the_mesh_and_only_a_receipt_completes(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _mind(registry, "friday", role="primary")
    mesh, _harness = _mesh()
    broker = AssistanceBroker(registry=registry, mesh=mesh)

    outcome = asyncio.run(
        broker.request_help("friday", "research", "summarise the last week", helper="intelx")
    )

    assert outcome.state == "COMPLETED", outcome.as_dict()
    assert outcome.performed is True
    # COMPLETED is only reachable through verify_receipt, so the evidence on the
    # outcome is the receipt's verification: require it, and require it to matter.
    evidence = outcome.attempt.get("evidence") or {}
    assert evidence, "a completion without verified evidence is not a completion"
    assert outcome.attempt.get("task_id"), "the exchange is not traceable to a task"
    # The caller's own mind recorded that its request was carried out.
    caller_mind = registry.for_agent("friday")
    assert caller_mind.ledger.get("research").successes == 1


@pytest.mark.parametrize(
    "behaviour,expected",
    [
        (HarnessBehaviour(status_code=202), "PENDING"),
        (HarnessBehaviour(receipt=False), "UNVERIFIED"),
        (HarnessBehaviour(status_code=401), "REFUSED"),
        (HarnessBehaviour(raise_transport_error=True), "UNREACHABLE"),
    ],
)
def test_every_peer_failure_is_reported_as_itself(
    tmp_path: Path, behaviour: HarnessBehaviour, expected: str
) -> None:
    """A peer that answers oddly is never reported as having done the work."""
    registry = _registry(tmp_path)
    mesh, harness = _mesh()
    harness.behave("cortex", behaviour)
    broker = AssistanceBroker(registry=registry, mesh=mesh)

    outcome = asyncio.run(broker.request_help("friday", "analyse", "check the market", helper="cortex"))

    assert outcome.state == expected, outcome.as_dict()
    assert outcome.performed is False
    assert outcome.helpful is False
    assert "did it" not in outcome.spoken()


def test_a_peer_named_by_another_agent_is_never_trusted_for_its_own_receipt(tmp_path: Path) -> None:
    """A receipt naming a different action does not complete the request."""
    registry = _registry(tmp_path)
    mesh, harness = _mesh()
    harness.behave(
        "memora",
        HarnessBehaviour(
            body={
                "status": "success",
                "receipt": {
                    "requested_action": "something-else-entirely",
                    "target": "memora",
                    "authorization_decision": "AUTHORIZED",
                    "verification_evidence": {"checked": "harness"},
                },
            }
        ),
    )
    broker = AssistanceBroker(registry=registry, mesh=mesh)
    outcome = asyncio.run(broker.request_help("friday", "remember", "keep this", helper="memora"))

    assert outcome.state == "UNVERIFIED"
    assert outcome.performed is False


def test_help_survives_a_peer_that_never_answers(tmp_path: Path) -> None:
    """A hung peer must not hang the caller: the request is bounded and escalated."""
    registry = _registry(tmp_path)
    mesh, harness = _mesh()
    mesh.request_timeout = 0.2
    harness.behave("forge", HarnessBehaviour(latency_ms=2000))
    broker = AssistanceBroker(registry=registry, mesh=mesh)

    started = time.monotonic()
    outcome = asyncio.run(broker.request_help("friday", "build", "install the tool", helper="forge"))
    elapsed = time.monotonic() - started

    assert outcome.state == "UNREACHABLE", outcome.as_dict()
    assert outcome.performed is False
    assert elapsed < 1.0, f"a hung peer held the caller for {elapsed:.1f}s despite a 0.2s budget"


def test_ten_agents_asking_at_once_all_get_their_own_answer(tmp_path: Path) -> None:
    """Concurrency across agents: ten callers, one peer, no crossed answers."""
    registry = _registry(tmp_path)
    mesh, _harness = _mesh()
    broker = AssistanceBroker(registry=registry, mesh=mesh)
    for index in range(10):
        _mind(registry, f"worker_{index}", role="worker")

    async def ask_all() -> list:
        return await asyncio.gather(
            *[
                broker.request_help(
                    f"worker_{index}", "research", f"question number {index}", helper="intelx"
                )
                for index in range(10)
            ]
        )

    outcomes = asyncio.run(ask_all())

    assert len(outcomes) == 10
    assert all(item.state == "COMPLETED" for item in outcomes), [o.state for o in outcomes]
    assert all(item.performed for item in outcomes)
    # The harness echoes the objective back, so a crossed answer is visible.
    echoes = [str(item.attempt.get("result", {}).get("result", {}).get("echo", "")) for item in outcomes]
    for index, echo in enumerate(echoes):
        assert f"question number {index}" in echo, f"worker_{index} got {echo!r} instead"
    # Each caller's own ledger recorded exactly one success.
    for index in range(10):
        mind = registry.for_agent(f"worker_{index}")
        assert mind.ledger.get("research").successes == 1


def test_help_is_refused_when_there_is_no_way_to_ask(tmp_path: Path) -> None:
    """No registry and no mesh: the broker says so instead of inventing help."""
    broker = AssistanceBroker(registry=None, mesh=None)
    outcome = asyncio.run(broker.request_help("friday", "research", "anything", helper="intelx"))

    assert outcome.state in {"BLOCKED", "UNREACHABLE"}
    assert outcome.performed is False
    assert outcome.refused_because or outcome.reason
