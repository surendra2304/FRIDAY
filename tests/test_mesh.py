"""Tests for the peer mesh: typed tasks, receipt verification, honest failures.

Everything here runs in-process against `ContractTransport`, which enforces the
real wire contract (path, credentials, envelope shape). No test in this file
touches the network; the live HTTP transport is labelled
CONFIGURED-BUT-UNVERIFIED in the handoff, not asserted here.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from friday.cognition.mesh import (
    ContractTransport,
    CircuitBreaker,
    HarnessBehaviour,
    HttpTransport,
    Mesh,
    OutcomeState,
    PeerContract,
    TransportError,
    build_contracts,
    verify_receipt,
)
from friday.core.task_envelope import ActionReceipt, TaskEnvelope, TaskResult


@pytest.fixture()
def contracts() -> dict[str, PeerContract]:
    """The real contracts, with a key configured so auth is exercised."""
    built = build_contracts()
    for contract in built.values():
        contract.api_key = contract.api_key or "test-key"
    return built


@pytest.fixture()
def mesh(contracts: dict[str, PeerContract]) -> tuple[Mesh, ContractTransport]:
    return Mesh.in_process(contracts, backoff_seconds=0.0)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


# ── contracts are derived, not retyped ────────────────────────────────────


def test_the_contract_table_is_read_from_the_live_fleet_client() -> None:
    from friday.ecosystem.fleet_client import FleetClient

    fleet = FleetClient()
    contracts = build_contracts(fleet)

    assert sorted(contracts) == [
        "cortex",
        "forge",
        "futuris",
        "inference",
        "intelx",
        "memora",
        "sentinel",
        "stratex",
    ]
    # The endpoints must be the ones the production client posts to.
    assert contracts["inference"].task_path == "/v1/task/execute"
    assert contracts["forge"].task_path == "/api/v1/forge/delegate"
    assert contracts["sentinel"].task_path == "/api/v1/friday/delegate"
    assert contracts["inference"].url_for("/health").endswith("/health")
    # Credentials are carried the way each peer expects, and only when present.
    assert "X-FRIDAY-API-Key" not in contracts["inference"].headers()
    contracts["inference"].api_key = "k"
    assert contracts["inference"].headers()["X-FRIDAY-API-Key"] == "k"
    contracts["sentinel"].api_key = "k"
    assert contracts["sentinel"].headers()["X-API-Key"] == "k"
    contracts["cortex"].api_key = "k"
    assert contracts["cortex"].headers()["X-Friday-Api-Key"] == "k"


# ── the harness enforces the real contract ────────────────────────────────


def test_the_harness_404s_an_unknown_path(mesh: tuple[Mesh, ContractTransport]) -> None:
    _, transport = mesh
    outcome = run(_dispatch_to_unknown_path(transport))

    assert outcome.status_code == 404


async def _dispatch_to_unknown_path(transport: ContractTransport) -> Any:
    from friday.cognition.mesh import PeerRequest

    return await transport.send(
        PeerRequest(peer="forge", method="POST", url="https://forge.example/nope", json_body={})
    )


def test_the_harness_401s_when_a_keyed_peer_gets_no_credentials(contracts: dict[str, PeerContract]) -> None:
    transport = ContractTransport(contracts)
    from friday.cognition.mesh import PeerRequest

    response = run(
        transport.send(
            PeerRequest(
                peer="forge",
                method="GET",
                url=f"{contracts['forge'].base_url}/health",
                headers={"Content-Type": "application/json"},
            )
        )
    )
    assert response.status_code == 401


def test_the_harness_422s_a_malformed_envelope(contracts: dict[str, PeerContract]) -> None:
    transport = ContractTransport(contracts)
    from friday.cognition.mesh import PeerRequest

    response = run(
        transport.send(
            PeerRequest(
                peer="forge",
                method="POST",
                url=f"{contracts['forge'].base_url}/api/v1/forge/delegate",
                headers=contracts["forge"].headers(),
                json_body={"not": "an envelope"},
            )
        )
    )
    assert response.status_code == 422


# ── the vocabulary that was missing ───────────────────────────────────────


def test_a_peer_that_never_answers_is_unreachable_not_degraded(
    mesh: tuple[Mesh, ContractTransport],
) -> None:
    """The core fix: no response is a different fact from a bad response."""
    client, transport = mesh
    transport.behave("cortex", HarnessBehaviour(raise_transport_error=True))

    outcome = run(client.dispatch("cortex", "scrape", attempts=1))

    assert outcome.state is OutcomeState.UNREACHABLE
    assert outcome.state is not OutcomeState.DEGRADED
    assert outcome.http_status is None
    assert not outcome.reached_peer
    assert not outcome.verified


def test_a_peer_that_answers_unhealthy_is_degraded(mesh: tuple[Mesh, ContractTransport]) -> None:
    client, transport = mesh
    transport.behave("sentinel", HarnessBehaviour(status_code=503))

    outcome = run(client.dispatch("sentinel", "audit", attempts=1))

    assert outcome.state is OutcomeState.DEGRADED
    assert outcome.reached_peer
    assert outcome.http_status == 503


def test_a_peer_that_rejects_us_is_refused(mesh: tuple[Mesh, ContractTransport]) -> None:
    client, transport = mesh
    transport.behave("intelx", HarnessBehaviour(status_code=403))

    outcome = run(client.dispatch("intelx", "research", attempts=1))

    assert outcome.state is OutcomeState.REFUSED
    assert "credentials" in outcome.detail


def test_an_accepted_but_unfinished_task_is_pending(mesh: tuple[Mesh, ContractTransport]) -> None:
    client, transport = mesh
    transport.behave("futuris", HarnessBehaviour(status_code=202))

    outcome = run(client.dispatch("futuris", "forecast", attempts=1))

    assert outcome.state is OutcomeState.PENDING
    assert "unproven" in outcome.detail


def test_a_200_without_a_receipt_is_unverified_not_completed(
    mesh: tuple[Mesh, ContractTransport],
) -> None:
    client, transport = mesh
    transport.behave("memora", HarnessBehaviour(receipt=False))

    outcome = run(client.dispatch("memora", "recall", attempts=1))

    assert outcome.state is OutcomeState.UNVERIFIED
    assert not outcome.verified
    assert "no receipt" in outcome.detail


def test_a_verified_receipt_completes_the_task(mesh: tuple[Mesh, ContractTransport]) -> None:
    client, _ = mesh

    outcome = run(client.dispatch("forge", "refactor", objective="tidy the parser", attempts=1))

    assert outcome.state is OutcomeState.COMPLETED
    assert outcome.verified
    assert outcome.evidence["receipt"]["ok"] is True
    assert outcome.result["task_id"] == outcome.task_id


# ── receipt verification, in isolation ────────────────────────────────────


def _envelope() -> TaskEnvelope:
    return TaskEnvelope(actor="friday", target_agent="forge", action="refactor", objective="tidy")


def _result(**receipt_kwargs: Any) -> TaskResult:
    base = {
        "requested_action": "refactor",
        "target": "forge",
        "authorization_decision": "AUTHORIZED",
        "verification_evidence": {"tests": "passed"},
    }
    base.update(receipt_kwargs)
    return TaskResult(task_id="t", target_agent="forge", receipt=ActionReceipt(**base))


def test_a_receipt_for_a_different_action_is_not_evidence() -> None:
    verdict = verify_receipt(_envelope(), _result(requested_action="delete_everything"))

    assert verdict.ok is False
    assert verdict.state is OutcomeState.UNVERIFIED
    assert "delete_everything" in verdict.reason


def test_a_receipt_from_a_different_peer_is_not_evidence() -> None:
    verdict = verify_receipt(_envelope(), _result(target="stratex"))

    assert verdict.ok is False
    assert verdict.state is OutcomeState.UNVERIFIED
    assert "stratex" in verdict.reason


def test_a_receipt_without_verification_evidence_is_not_evidence() -> None:
    verdict = verify_receipt(_envelope(), _result(verification_evidence={}))

    assert verdict.ok is False
    assert verdict.state is OutcomeState.UNVERIFIED
    assert "no verification evidence" in verdict.reason


def test_a_rejected_receipt_is_a_refusal() -> None:
    verdict = verify_receipt(
        _envelope(),
        _result(authorization_decision="REJECTED", failure_reason="policy forbids this"),
    )

    assert verdict.ok is False
    assert verdict.state is OutcomeState.REFUSED
    assert "policy forbids this" in verdict.reason


def test_a_receipt_naming_a_failure_is_an_error() -> None:
    verdict = verify_receipt(_envelope(), _result(failure_reason="the compiler exploded"))

    assert verdict.ok is False
    assert verdict.state is OutcomeState.ERROR


def test_no_receipt_at_all_is_unverified() -> None:
    verdict = verify_receipt(_envelope(), TaskResult(task_id="t", target_agent="forge"))

    assert verdict.ok is False
    assert verdict.state is OutcomeState.UNVERIFIED


def test_a_fully_formed_receipt_completes() -> None:
    verdict = verify_receipt(_envelope(), _result())

    assert verdict.ok is True
    assert verdict.state is OutcomeState.COMPLETED
    assert verdict.as_dict()["ok"] is True


# ── fallback paths ────────────────────────────────────────────────────────


def test_a_peer_without_the_task_contract_falls_back_and_says_so(
    mesh: tuple[Mesh, ContractTransport],
) -> None:
    """A legacy endpoint answering is proof of life, not proof of work."""
    client, transport = mesh
    # stratex does not expose the task contract; its documented fallback is a GET
    # on /api/engine-health. Model exactly that: 404 on the task path, 200 on the
    # legacy path.
    transport.behave("stratex", HarnessBehaviour(status_code=404), path="/v1/task/execute")
    transport.behave(
        "stratex", HarnessBehaviour(status_code=200, body={"engine": "ok"}), path="/api/engine-health"
    )

    outcome = run(client.dispatch("stratex", "rebalance", attempts=1))

    assert outcome.http_status == 200
    assert outcome.state is OutcomeState.DEGRADED
    assert outcome.contract_used == "/api/engine-health"
    assert "NOT performed or verified" in outcome.detail or "not" in outcome.detail.lower()


# ── retries and the breaker ───────────────────────────────────────────────


def test_unreachable_peers_are_retried_and_refusals_are_not(
    mesh: tuple[Mesh, ContractTransport],
) -> None:
    client, transport = mesh
    transport.behave("cortex", HarnessBehaviour(raise_transport_error=True))
    outcome = run(client.dispatch("cortex", "scrape", attempts=3))
    assert outcome.state is OutcomeState.UNREACHABLE
    assert outcome.attempts == 3
    assert len(transport.calls) == 3

    transport.calls.clear()
    transport.behave("intelx", HarnessBehaviour(status_code=403))
    refused = run(client.dispatch("intelx", "research", attempts=3))
    assert refused.state is OutcomeState.REFUSED
    assert len(transport.calls) == 1, "a refusal must not be retried"


def test_the_breaker_stops_the_mesh_hammering_a_dead_peer(
    mesh: tuple[Mesh, ContractTransport],
) -> None:
    client, transport = mesh
    client.breaker = CircuitBreaker(threshold=2, cooldown_seconds=300)
    transport.behave("cortex", HarnessBehaviour(raise_transport_error=True))

    run(client.dispatch("cortex", "a", attempts=1))
    run(client.dispatch("cortex", "b", attempts=1))
    calls_before = len(transport.calls)
    blocked = run(client.dispatch("cortex", "c", attempts=1))

    assert blocked.state is OutcomeState.BLOCKED
    assert "circuit is open" in blocked.detail
    assert len(transport.calls) == calls_before, "an open circuit must not send anything"


def test_an_answered_peer_does_not_open_the_breaker(mesh: tuple[Mesh, ContractTransport]) -> None:
    client, transport = mesh
    client.breaker = CircuitBreaker(threshold=1, cooldown_seconds=300)
    transport.behave("sentinel", HarnessBehaviour(status_code=500))

    run(client.dispatch("sentinel", "audit", attempts=1))
    again = run(client.dispatch("sentinel", "audit", attempts=1))

    assert again.state is OutcomeState.DEGRADED, "a peer that answers must keep being listened to"


def test_an_unconfigured_peer_is_blocked_with_the_reason(contracts: dict[str, PeerContract]) -> None:
    contracts["forge"].base_url = ""
    client, transport = Mesh.in_process(contracts)

    outcome = run(client.dispatch("forge", "build"))

    assert outcome.state is OutcomeState.BLOCKED
    assert "FRIDAY_FORGE_URL" in outcome.detail
    assert transport.calls == []


def test_an_unknown_peer_is_blocked_and_the_known_peers_are_listed(
    mesh: tuple[Mesh, ContractTransport],
) -> None:
    client, _ = mesh
    outcome = run(client.dispatch("hal9000", "open the pod bay doors"))

    assert outcome.state is OutcomeState.BLOCKED
    assert "inference" in outcome.detail


# ── many peers, and health ────────────────────────────────────────────────


def test_dispatch_many_returns_one_typed_outcome_per_peer(
    mesh: tuple[Mesh, ContractTransport],
) -> None:
    client, transport = mesh
    transport.behave("cortex", HarnessBehaviour(raise_transport_error=True))

    outcomes = run(
        client.dispatch_many(
            {"forge": ("build", {}), "cortex": ("scrape", {}), "memora": ("recall", {})},
            attempts=1,
        )
    )

    assert set(outcomes) == {"forge", "cortex", "memora"}
    assert outcomes["forge"].state is OutcomeState.COMPLETED
    assert outcomes["cortex"].state is OutcomeState.UNREACHABLE
    assert outcomes["memora"].state is OutcomeState.COMPLETED


def test_health_separates_unreachable_from_degraded_and_pending(
    mesh: tuple[Mesh, ContractTransport],
) -> None:
    client, transport = mesh
    transport.behave("cortex", HarnessBehaviour(raise_transport_error=True))
    transport.behave("forge", HarnessBehaviour(status_code=502))
    transport.behave("sentinel", HarnessBehaviour(status_code=403))
    transport.behave("memora", HarnessBehaviour(status_code=200, body={"status": "healthy"}))

    outcomes = run(client.health())

    assert outcomes["cortex"].state is OutcomeState.UNREACHABLE
    assert outcomes["forge"].state is OutcomeState.DEGRADED
    assert outcomes["sentinel"].state is OutcomeState.REFUSED
    assert outcomes["memora"].state is OutcomeState.PENDING
    assert "does not prove task execution" in outcomes["memora"].detail


def test_a_health_endpoint_that_says_unhealthy_is_degraded(
    mesh: tuple[Mesh, ContractTransport],
) -> None:
    client, transport = mesh
    transport.behave("inference", HarnessBehaviour(status_code=200, body={"status": "unhealthy"}))

    outcomes = run(client.health("inference"))

    assert outcomes["inference"].state is OutcomeState.DEGRADED
    assert "unhealthy" in outcomes["inference"].detail


# ── reconnect, and the reflex brain's use of it ──────────────────────────


def test_reconnect_reports_reachability_not_health(
    mesh: tuple[Mesh, ContractTransport],
) -> None:
    client, transport = mesh
    transport.behave("cortex", HarnessBehaviour(raise_transport_error=True))

    dead = run(client.reconnect("cortex", attempts=2))
    assert dead.recovered is False
    assert dead.state is OutcomeState.UNREACHABLE
    assert dead.attempts == 2

    transport.behave("cortex", HarnessBehaviour(status_code=200, body={"status": "healthy"}))
    alive = run(client.reconnect("cortex", attempts=2))
    assert alive.recovered is True
    assert alive.state is OutcomeState.PENDING
    assert "not proof" in alive.detail


def test_the_reflex_brain_escalates_an_unreachable_peer_and_resolves_it_on_reconnect(
    contracts: dict[str, PeerContract],
) -> None:
    """The real integration: reflex brain -> mesh -> harness peer."""
    from friday.cognition.reflex import IncidentKind, IncidentSeverity
    from friday.cognition.reflex import Incident as ReflexIncident
    from friday.cognition.reflex import ReflexBrain, OutcomeStatus

    mesh, transport = Mesh.in_process(contracts, backoff_seconds=0.0)
    brain = ReflexBrain(repo_root=".", mesh=mesh)
    incident = ReflexIncident(
        kind=IncidentKind.PEER_UNREACHABLE,
        severity=IncidentSeverity.HIGH,
        source="cortex",
        summary="cortex did not answer",
        evidence={"probe": "health"},
    )

    transport.behave("cortex", HarnessBehaviour(raise_transport_error=True))
    first = run(brain.handle(incident))
    assert first.status is OutcomeStatus.ESCALATED
    assert "did not answer" in first.detail

    transport.behave("cortex", HarnessBehaviour(status_code=200, body={"status": "healthy"}))
    second = run(brain.handle(incident))
    assert second.status is OutcomeStatus.RESOLVED
    assert second.evidence_class == "transport_recovery"


def test_the_brain_reports_degraded_as_an_observation_without_touching_the_peer(
    contracts: dict[str, PeerContract],
) -> None:
    from friday.cognition.reflex import IncidentKind, IncidentSeverity
    from friday.cognition.reflex import Incident as ReflexIncident
    from friday.cognition.reflex import ReflexBrain, OutcomeStatus

    mesh, _ = Mesh.in_process(contracts)
    brain = ReflexBrain(repo_root=".", mesh=mesh)
    incident = ReflexIncident(
        kind=IncidentKind.PEER_DEGRADED,
        severity=IncidentSeverity.MEDIUM,
        source="sentinel",
        summary="sentinel reports itself unhealthy",
        evidence={},
    )

    outcome = run(brain.handle(incident))

    assert outcome.status is OutcomeStatus.OBSERVED
    assert "no authority over a remote service" in outcome.detail


# ── status honesty ────────────────────────────────────────────────────────


def test_status_says_out_loud_that_a_harness_proves_logic_not_the_network(
    mesh: tuple[Mesh, ContractTransport],
) -> None:
    client, _ = mesh
    run(client.dispatch("forge", "build", attempts=1))

    status = client.status()

    assert "no remote service was contacted" in status["live_verification"]
    assert status["history"] == 1
    assert status["state_counts"]["COMPLETED"] == 1
    assert len(status["receipt_trail"]) == 1


def test_the_live_transport_refuses_to_pretend_a_local_error_is_a_peer_state() -> None:
    transport = HttpTransport(timeout=0.05)

    async def attempt() -> None:
        from friday.cognition.mesh import PeerRequest

        with pytest.raises(TransportError):
            await transport.send(
                PeerRequest(
                    peer="forge",
                    method="GET",
                    url="http://127.0.0.1:9/health",  # discard port: nothing listens
                )
            )

    run(attempt())
