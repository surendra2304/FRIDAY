"""The user-facing peer-task route must dispatch and verify, not health-probe.

All peer behavior is served by ``ContractTransport`` in-process. The test
requests never reach configured peer URLs or a provider.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from friday.api import server
from friday.api.server import app
from friday.cognition.mesh import HarnessBehaviour, Mesh, build_contracts
from friday.ecosystem.fleet_client import fleet_client


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _local_mesh() -> tuple[Mesh, object, object]:
    contracts = build_contracts(fleet_client)
    mesh, transport = Mesh.in_process(contracts, attempts=1, backoff_seconds=0.0)
    return mesh, transport, contracts


def _post(client: TestClient, command: str):
    return client.post("/api/command", json={"command": command})


def _forbidden_query(*_args, **_kwargs):
    raise AssertionError("delegation must not call a read-only ask/status endpoint")


@pytest.mark.parametrize(
    ("behaviour", "expected_http", "expected_state", "expected_success"),
    [
        (HarnessBehaviour(), 200, "COMPLETED", True),
        (
            HarnessBehaviour(status_code=202, body={"state": "queued", "task_id": "forge-task-27"}),
            202,
            "PENDING",
            False,
        ),
        (HarnessBehaviour(receipt=False), 502, "UNVERIFIED", False),
    ],
)
def test_user_delegation_uses_typed_mesh_and_preserves_completion_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    behaviour: HarnessBehaviour,
    expected_http: int,
    expected_state: str,
    expected_success: bool,
) -> None:
    mesh, transport, contracts = _local_mesh()
    transport.behave("forge", behaviour)
    controller = server.autonomous_controller
    monkeypatch.setattr(controller, "_peer_mesh", mesh, raising=False)
    monkeypatch.setattr(fleet_client, "ask_forge", _forbidden_query)
    monkeypatch.setattr(fleet_client, "ask_inference", _forbidden_query)

    class AgentMustNotRun:
        authorizer = None

        def process_message(self, _command: str):
            raise AssertionError("a peer delegation must not fall through to the local LLM")

    monkeypatch.setattr(server, "agent", AgentMustNotRun())
    directive = "build a small local command-line demo"
    response = _post(client, f"tell forge to {directive}")

    assert response.status_code == expected_http, response.text
    metadata = response.json()["metadata"]
    assert metadata["task_state"] == expected_state
    assert metadata["success"] is expected_success
    assert metadata["task_completion_verified"] is expected_success
    assert len(transport.calls) == 1

    request = transport.calls[0]
    assert request.method == "POST"
    assert request.url == contracts["forge"].url_for(contracts["forge"].task_path)
    assert request.json_body["target_agent"] == "forge"
    assert request.json_body["action"] == "execute"
    assert request.json_body["objective"] == directive
    assert request.json_body["payload"]["directive"] == directive
    assert request.json_body["capability"] == "forge.execute"
    assert request.json_body["trust_level"] == "operator_confirmed"

    if expected_state == "COMPLETED":
        assert metadata["receipt"]["verification_evidence"]
    elif expected_state == "PENDING":
        assert metadata["task_id"] == "forge-task-27"
        assert "unproven" in response.json()["reply"].lower()
    else:
        assert metadata["error"]
        assert "receipt" in response.json()["reply"].lower()
