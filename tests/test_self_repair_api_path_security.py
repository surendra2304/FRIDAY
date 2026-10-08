"""The HTTP proposal route must enforce repair-path confinement on a local gate."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from friday.api import server
from friday.autonomous.self_repair import GitRepairApplier, SelfRepairGate


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True, timeout=30
    )
    return completed.stdout.strip()


def test_proposals_route_refuses_a_traversal_target_on_the_configured_local_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repairable"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "route-test@localhost")
    _git(repo, "config", "user.name", "Route Test")
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    base_commit = _git(repo, "rev-parse", "HEAD")

    gate = SelfRepairGate(GitRepairApplier(str(repo)))
    monkeypatch.setattr(server, "_self_repair_repo", str(repo))
    monkeypatch.setattr(server, "_self_repair_gate", gate)
    for name in ("RENDER", "FRIDAY_API_KEY", "FRIDAY_UNIVERSE_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    body = {
        "branch": "repair/escape",
        "base_commit": base_commit,
        "target_file": "../outside.py",
        "original_snippet": "return a - b",
        "replacement_snippet": "return a + b",
        "rationale": "test path validation through the API",
        "test_evidence": {
            "command": "pytest -q",
            "passed": True,
            "summary": "1 passed",
            "returncode": 0,
        },
    }

    client = TestClient(server.app)
    response = client.post("/api/self-repair/proposals", json=body)

    assert response.status_code == 200
    payload = response.json()
    assert payload["receipt"]["outcome"] == "REFUSED"
    assert "INVALID_TARGET_PATH" in payload["receipt"]["detail"]
    assert payload["record"]["state"] == "BLOCKED"
    assert not (tmp_path / "outside.py").exists()
    assert _git(repo, "rev-parse", "HEAD") == base_commit
    assert _git(repo, "status", "--porcelain") == ""
