"""Regression tests for BUG-001: drive-by command execution from a web page.

The original defect had two halves that composed into a remote-code-execution
path from any website the owner happened to have open:

* ``allow_origins=["*"]`` next to ``allow_credentials=True`` made Starlette
  reflect whatever origin asked, so CORS offered no protection at all.
* ``_require_control_access`` returned early for loopback callers — and a page in
  the owner's own browser *is* a loopback caller.

These tests fail against the old behaviour and pass against the fix. They assert
the property that matters (a foreign origin cannot drive the control API), not
the implementation that provides it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from friday.api.server import app

#: An origin that is not, and must never become, trusted by default.
ATTACKER_ORIGIN = "https://attacker.example"

#: A state-changing control endpoint. The specific command does not matter: the
#: request must be refused before any handler or fast path can see it.
CONTROL_PATH = "/api/command"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("FRIDAY_API_KEY", raising=False)
    monkeypatch.delenv("FRIDAY_UNIVERSE_API_KEY", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    with TestClient(app) as test_client:
        yield test_client


def _command_body() -> dict[str, str]:
    return {"command": "fix yourself"}


class TestForeignOriginRefused:
    """A browser page from an untrusted origin cannot drive FRIDAY."""

    def test_cross_origin_command_is_refused(self, client: TestClient) -> None:
        response = client.post(
            CONTROL_PATH,
            json=_command_body(),
            headers={"Origin": ATTACKER_ORIGIN},
        )
        assert response.status_code == 403, (
            f"a foreign origin reached the control API (HTTP {response.status_code}): {response.text[:200]}"
        )

    def test_cross_origin_refusal_names_the_reason(self, client: TestClient) -> None:
        response = client.post(
            CONTROL_PATH,
            json=_command_body(),
            headers={"Origin": ATTACKER_ORIGIN},
        )
        assert "origin" in response.json()["detail"].lower()

    def test_opaque_null_origin_is_refused(self, client: TestClient) -> None:
        """`null` is what a sandboxed iframe or a file:// page sends."""
        response = client.post(
            CONTROL_PATH,
            json=_command_body(),
            headers={"Origin": "null"},
        )
        assert response.status_code == 403

    @pytest.mark.parametrize(
        "path",
        ["/api/chat", "/api/screenshot", "/api/android", "/api/tasks/cancel-all"],
    )
    def test_every_state_changing_route_is_covered(self, client: TestClient, path: str) -> None:
        """The origin gate lives in the shared dependency, so no route can miss it."""
        response = client.post(path, json=_command_body(), headers={"Origin": ATTACKER_ORIGIN})
        assert response.status_code == 403, f"{path} accepted a foreign origin"

    def test_attacker_origin_is_never_echoed(self, client: TestClient) -> None:
        """Defence in depth: even a refused response must not authorise the origin."""
        response = client.post(
            CONTROL_PATH,
            json=_command_body(),
            headers={"Origin": ATTACKER_ORIGIN},
        )
        assert response.headers.get("access-control-allow-origin") != ATTACKER_ORIGIN
        assert response.headers.get("access-control-allow-credentials") != "true"


class TestTrustedCallersStillWork:
    """The fix must not break the owner's own tooling."""

    def test_non_browser_caller_without_origin_is_allowed(self, client: TestClient) -> None:
        """curl, the MCP client and server-to-server peers send no Origin."""
        response = client.post(CONTROL_PATH, json={"command": "what time is it"})
        assert response.status_code == 200
        assert response.json()["reply"]

    def test_configured_frontend_origin_is_allowed(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """The Next.js dev server is a legitimate cross-origin frontend."""
        monkeypatch.setenv("FRIDAY_ALLOWED_ORIGINS", "http://localhost:3000")
        from friday.core.config import get_settings

        get_settings(reload=True)
        try:
            response = client.post(
                CONTROL_PATH,
                json={"command": "what time is it"},
                headers={"Origin": "http://localhost:3000"},
            )
            assert response.status_code == 200
            assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
        finally:
            monkeypatch.delenv("FRIDAY_ALLOWED_ORIGINS", raising=False)
            get_settings(reload=True)

    def test_read_only_probes_remain_open(self, client: TestClient) -> None:
        """Health and telemetry are not state-changing and stay reachable."""
        for path in ("/health", "/api/tools", "/api/diagnostics"):
            assert client.get(path).status_code == 200


class TestLoopbackHardening:
    """`require_api_key_on_loopback` closes the same-machine case on request."""

    def test_key_is_demanded_when_hardening_is_on(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FRIDAY_REQUIRE_API_KEY_ON_LOOPBACK", "true")
        monkeypatch.setenv("FRIDAY_API_KEY", "a-real-control-key")
        from friday.core.config import get_settings

        get_settings(reload=True)
        try:
            refused = client.post(CONTROL_PATH, json={"command": "what time is it"})
            assert refused.status_code == 401

            accepted = client.post(
                CONTROL_PATH,
                json={"command": "what time is it"},
                headers={"X-FRIDAY-API-Key": "a-real-control-key"},
            )
            assert accepted.status_code == 200
        finally:
            monkeypatch.delenv("FRIDAY_REQUIRE_API_KEY_ON_LOOPBACK", raising=False)
            monkeypatch.delenv("FRIDAY_API_KEY", raising=False)
            get_settings(reload=True)
