from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from friday.api import server
from friday.cli.auth import CLIAuthorizer
from friday.core import config
from friday.core.auth import DefaultSecureAuthorizer
from friday.core.types import AuthorizationDecision, AuthorizationRequest, SafetyLevel


def _request() -> AuthorizationRequest:
    return AuthorizationRequest(
        tool_name="send_email",
        safety_level=SafetyLevel.SENSITIVE,
        arguments={"to": "user@example.invalid"},
    )


def _client(monkeypatch) -> TestClient:
    monkeypatch.setitem(server.app.dependency_overrides, server._require_control_access, lambda: None)
    return TestClient(server.app)


def test_autonomous_status_reads_the_authorization_setting(monkeypatch) -> None:
    settings = SimpleNamespace(autonomous_mode=False, full_access_mode=False)
    monkeypatch.setattr(config, "get_settings", lambda: settings)

    response = _client(monkeypatch).get("/api/autonomous/status")

    assert response.status_code == 200
    assert response.json()["autonomous_mode"] is False
    assert response.json()["full_access_mode"] is False
    assert response.json()["sensitive_actions_auto_approved"] is False
    assert response.json()["autonomous_mode_persistence"] == "runtime_only"
    assert server.autonomous_controller.is_autonomous() is False


def test_default_authorizer_never_auto_approves_dangerous_actions(monkeypatch) -> None:
    settings = SimpleNamespace(autonomous_mode=True, full_access_mode=True)
    monkeypatch.setattr(config, "get_settings", lambda: settings)

    response = DefaultSecureAuthorizer().authorize(
        AuthorizationRequest(
            tool_name="run_command",
            safety_level=SafetyLevel.DANGEROUS,
            arguments={"command": "destructive-operation"},
        )
    )

    assert response.decision == AuthorizationDecision.DENIED
    assert "explicit user confirmation" in response.reason.lower()


def test_cli_authorizer_observes_runtime_autonomous_toggles(monkeypatch) -> None:
    settings = SimpleNamespace(autonomous_mode=False, full_access_mode=False)
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    controller = server.autonomous_controller
    controller.enabled = False
    authorizer = CLIAuthorizer()

    assert authorizer.authorize(_request()).decision == AuthorizationDecision.DENIED
    assert controller.toggle() is True
    assert settings.autonomous_mode is True
    assert authorizer.authorize(_request()).decision == AuthorizationDecision.APPROVED
    assert controller.toggle() is False
    assert authorizer.authorize(_request()).decision == AuthorizationDecision.DENIED


def test_api_toggle_updates_the_setting_used_by_authorization(monkeypatch) -> None:
    settings = SimpleNamespace(autonomous_mode=True, full_access_mode=False)
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    monkeypatch.setattr(server.autonomous_controller, "enabled", True)
    client = _client(monkeypatch)

    assert DefaultSecureAuthorizer().authorize(_request()).decision == AuthorizationDecision.APPROVED
    response = client.post("/api/autonomous/toggle")

    assert response.status_code == 200
    assert response.json()["autonomous_mode"] is False
    assert response.json()["full_access_mode"] is False
    assert response.json()["sensitive_actions_auto_approved"] is False
    assert response.json()["autonomous_mode_persistence"] == "runtime_only"
    assert settings.autonomous_mode is False
    assert client.get("/api/autonomous/status").json()["autonomous_mode"] is False
    assert DefaultSecureAuthorizer().authorize(_request()).decision == AuthorizationDecision.DENIED


def test_command_mode_changes_disclose_runtime_only_scope(monkeypatch) -> None:
    settings = SimpleNamespace(autonomous_mode=False, full_access_mode=False)
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    client = _client(monkeypatch)

    activated = client.post("/api/command", json={"command": "enable autonomous mode"})
    assert activated.status_code == 200
    assert settings.autonomous_mode is True
    assert activated.json()["metadata"]["autonomous_mode_persistence"] == "runtime_only"
    assert "not saved" in activated.json()["reply"].lower()
    assert "dangerous actions still require explicit confirmation" in activated.json()["reply"].lower()

    deactivated = client.post("/api/command", json={"command": "disable autonomous mode"})
    assert deactivated.status_code == 200
    assert settings.autonomous_mode is False
    assert deactivated.json()["metadata"]["autonomous_mode_persistence"] == "runtime_only"
    assert "manual approval" in deactivated.json()["reply"].lower()


def test_disabling_autonomous_mode_keeps_full_access_mode_visible(monkeypatch) -> None:
    settings = SimpleNamespace(autonomous_mode=True, full_access_mode=True)
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    monkeypatch.setattr(server.autonomous_controller, "enabled", True)
    client = _client(monkeypatch)

    response = client.post("/api/autonomous/toggle")

    assert response.status_code == 200
    assert response.json()["autonomous_mode"] is False
    assert response.json()["full_access_mode"] is True
    assert response.json()["sensitive_actions_auto_approved"] is True
    assert settings.autonomous_mode is False
    assert DefaultSecureAuthorizer().authorize(_request()).decision == AuthorizationDecision.APPROVED
