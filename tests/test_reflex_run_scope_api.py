"""The reflex HTTP route must refuse misspelled scopes instead of widening them."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from friday.api import server


@pytest.mark.parametrize("scope", ["typo", "tests,typo", ","])
def test_reflex_run_rejects_unknown_scope_without_starting_a_pass(
    scope: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    class CountingBrain:
        calls: list[set[Any] | None] = []

        async def run_once(self, *, include: set[Any] | None = None) -> dict[str, Any]:
            self.calls.append(include)
            return {"status": "COMPLETED", "incidents": 0, "acted_on": 0, "outcomes": []}

    brain = CountingBrain()
    monkeypatch.setattr(server, "get_reflex_brain", lambda: brain)
    server.app.dependency_overrides[server._require_control_access] = lambda: None
    try:
        client = TestClient(server.app)
        response = client.post("/api/reflex/run", json={"scope": scope})
    finally:
        server.app.dependency_overrides.pop(server._require_control_access, None)

    assert response.status_code == 422
    assert "scope" in response.json()["detail"].lower()
    assert brain.calls == []


def test_reflex_run_keeps_a_valid_scope_narrow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from friday.cognition.reflex import IncidentKind

    class CountingBrain:
        calls: list[set[Any] | None] = []

        async def run_once(self, *, include: set[Any] | None = None) -> dict[str, Any]:
            self.calls.append(include)
            return {"status": "COMPLETED", "incidents": 0, "acted_on": 0, "outcomes": []}

    brain = CountingBrain()
    monkeypatch.setattr(server, "get_reflex_brain", lambda: brain)
    server.app.dependency_overrides[server._require_control_access] = lambda: None
    try:
        client = TestClient(server.app)
        response = client.post("/api/reflex/run", json={"scope": "tests"})
    finally:
        server.app.dependency_overrides.pop(server._require_control_access, None)

    assert response.status_code == 200
    assert brain.calls == [{IncidentKind.TEST_FAILURE}]
