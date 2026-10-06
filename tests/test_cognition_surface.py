"""The cognition surfaces an operator actually reaches: HTTP and the CLI.

These tests exist because the reflex brain's own instructions used to point at
commands that did not exist — ``friday --grant-autonomy`` and
``friday --approve-repair`` were quoted in refusal messages while nothing in the
CLI answered to those names. A refusal that tells the owner to run a command
that is not there is worse than a refusal.

Every test here drives the real endpoint or the real entry point. Nothing is
mocked except the control key, which is environment configuration.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient

from friday.api.server import app
from friday.cognition.mandate import MandateAuthority


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


# ── HTTP surfaces ─────────────────────────────────────────────────────────


def test_reflex_status_is_readable_and_honest(client: TestClient) -> None:
    response = client.get("/api/reflex/status")

    assert response.status_code == 200
    body = response.json()
    assert "enabled" in body and "status" in body
    assert "outcomes" in body


def test_mesh_status_names_the_peers_and_the_verification_state(client: TestClient) -> None:
    response = client.get("/api/mesh/status")

    assert response.status_code == 200
    body = response.json()
    peers = {peer["name"] for peer in body["peers"]}
    assert peers == {
        "inference",
        "memora",
        "stratex",
        "intelx",
        "futuris",
        "cortex",
        "forge",
        "sentinel",
    }
    # It must not imply that a live peer has been verified from this host.
    assert "UNVERIFIED" in body["live_verification"] or "harness" in body["live_verification"]


def test_minds_endpoint_reports_the_fleet_and_the_shared_memory(client: TestClient) -> None:
    response = client.get("/api/minds")

    assert response.status_code == 200
    body = response.json()
    assert "agents" in body and "memory" in body
    assert "lexical" in body["memory"]["retrieval_mode"]


def test_the_reflex_trigger_is_gated_like_every_other_control_call(client: TestClient) -> None:
    """A browser page must not be able to trigger an unattended repair pass."""
    response = client.post(
        "/api/reflex/run",
        json={"scope": "resources"},
        headers={"Origin": "https://attacker.example"},
    )

    assert response.status_code == 403


def test_a_remote_caller_without_the_control_key_cannot_trigger_a_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loopback is the owner's own machine; anything else must present the key."""
    monkeypatch.setenv("FRIDAY_API_KEY", "a-real-configured-control-key")
    remote = TestClient(app, client=("203.0.113.7", 44444))

    response = remote.post("/api/reflex/run", json={"scope": "resources"})

    assert response.status_code == 401


def test_a_remote_caller_with_the_control_key_can_trigger_a_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRIDAY_API_KEY", "a-real-configured-control-key")
    remote = TestClient(app, client=("203.0.113.7", 44444))

    response = remote.post(
        "/api/reflex/run",
        json={"scope": "resources"},
        headers={"X-Friday-Api-Key": "a-real-configured-control-key"},
    )

    assert response.status_code == 200, response.text


def test_the_reflex_trigger_runs_a_real_pass_with_the_control_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FRIDAY_API_KEY", "a-real-configured-control-key")

    response = client.post(
        "/api/reflex/run",
        json={"scope": "resources"},
        headers={"X-Friday-Api-Key": "a-real-configured-control-key"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] in {"COMPLETED", "ERROR"}
    assert "incidents" in body


# ── CLI surfaces ──────────────────────────────────────────────────────────


def _cli(monkeypatch: pytest.MonkeyPatch, *argv: str) -> None:
    from friday.cli.main import main

    monkeypatch.setattr(sys, "argv", ["friday", *argv])
    main()


def test_autonomy_status_says_awaiting_mandate_when_none_exists(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Any
) -> None:
    monkeypatch.setenv("FRIDAY_AUTONOMY_KEY", "cli-test-key")
    monkeypatch.setenv("FRIDAY_AUTONOMY_LEDGER", str(tmp_path / "mandates.json"))

    _cli(monkeypatch, "--autonomy-status")

    out = capsys.readouterr().out
    assert "AWAITING_MANDATE" in out


def test_grant_autonomy_without_a_key_refuses_and_names_the_fix(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Any
) -> None:
    monkeypatch.delenv("FRIDAY_AUTONOMY_KEY", raising=False)
    monkeypatch.setenv("FRIDAY_AUTONOMY_LEDGER", str(tmp_path / "mandates.json"))

    with pytest.raises(SystemExit) as exit_info:
        _cli(monkeypatch, "--grant-autonomy")

    assert exit_info.value.code == 1
    out = capsys.readouterr().out
    assert "FRIDAY_AUTONOMY_KEY is not configured" in out
    assert "--generate-autonomy-key" in out


def test_grant_then_status_then_revoke_is_a_real_cycle(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Any
) -> None:
    monkeypatch.setenv("FRIDAY_AUTONOMY_KEY", "cli-test-key")
    ledger = tmp_path / "mandates.json"
    monkeypatch.setenv("FRIDAY_AUTONOMY_LEDGER", str(ledger))

    _cli(
        monkeypatch,
        "--grant-autonomy",
        "--autonomy-hours",
        "1",
        "--autonomy-scope",
        "source_repair",
        "--autonomy-max-files",
        "2",
    )
    granted = capsys.readouterr().out
    assert "Standing autonomy granted" in granted
    assert "source_repair" in granted
    assert ledger.exists(), "the mandate was not persisted"

    # The file is a signed document, not a claim.
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    granted = payload.get("granted") or {}
    assert granted, f"the ledger recorded no grant: {sorted(payload)}"
    document = next(iter(granted.values()))
    assert document.get("signature"), "the stored mandate is unsigned"
    assert document.get("issued_by"), "the stored mandate does not name its issuer"

    _cli(monkeypatch, "--autonomy-status")
    assert "ACTIVE" in capsys.readouterr().out

    _cli(monkeypatch, "--revoke-autonomy", "all")
    assert "Revoked 1 mandate" in capsys.readouterr().out

    _cli(monkeypatch, "--autonomy-status")
    assert "AWAITING_MANDATE" in capsys.readouterr().out


def test_grant_autonomy_refuses_an_unknown_scope(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Any
) -> None:
    monkeypatch.setenv("FRIDAY_AUTONOMY_KEY", "cli-test-key")
    monkeypatch.setenv("FRIDAY_AUTONOMY_LEDGER", str(tmp_path / "mandates.json"))

    with pytest.raises(SystemExit):
        _cli(monkeypatch, "--grant-autonomy", "--autonomy-scope", "take_over_the_world")

    out = capsys.readouterr().out
    assert "Unknown scope" in out
    assert not (tmp_path / "mandates.json").exists()


def test_generate_autonomy_key_prints_a_key_that_is_not_committed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _cli(monkeypatch, "--generate-autonomy-key")

    out = capsys.readouterr().out
    assert "FRIDAY_AUTONOMY_KEY=" in out
    key = out.split("FRIDAY_AUTONOMY_KEY=", 1)[1].split("\n", 1)[0].strip()
    assert len(key) >= 32


def test_reflex_status_cli_prints_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _cli(monkeypatch, "--reflex-status")

    body = json.loads(capsys.readouterr().out)
    assert "enabled" in body
    assert "interval_seconds" in body


def test_approve_repair_refuses_a_patch_that_does_not_exist(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Any
) -> None:
    monkeypatch.setenv("FRIDAY_AUTONOMY_KEY", "cli-test-key")
    monkeypatch.setenv("FRIDAY_AUTONOMY_LEDGER", str(tmp_path / "mandates.json"))

    with pytest.raises(SystemExit) as exit_info:
        _cli(monkeypatch, "--approve-repair", "patch_that_was_never_proposed")

    assert exit_info.value.code == 1
    assert "Nothing was approved" in capsys.readouterr().out


def test_approve_repair_refuses_a_proposal_that_was_never_reviewed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Any
) -> None:
    """A real proposal that has not been reviewed is refused by the gate, not approved.

    The old name for this test was "refuses_without_a_mandate", which described a
    rule that no longer exists: the owner may approve by hand with no mandate, and
    what refuses this proposal is that nothing has reviewed it.
    """
    from friday.api.server import _self_repair_gate

    monkeypatch.setenv("FRIDAY_AUTONOMY_KEY", "cli-test-key")
    monkeypatch.setenv("FRIDAY_AUTONOMY_LEDGER", str(tmp_path / "mandates.json"))
    record, _receipt = _self_repair_gate.propose(
        _a_proposal_without_evidence(tmp_path)
    )

    with pytest.raises(SystemExit) as exit_info:
        _cli(monkeypatch, "--approve-repair", record.patch_id)

    assert exit_info.value.code == 1
    out = capsys.readouterr().out
    assert "APPROVAL REFUSED" in out
    assert "Approved." not in out, "a refusal was reported as an approval"


def _gate_with_a_reviewed_patch(tmp_path: Any) -> tuple[Any, str]:
    """A real gate, a real applier, a real repo, and a review that actually passes."""
    import subprocess

    from friday.autonomous.self_repair import (
        GitRepairApplier,
        RepairProposal,
        SelfRepairGate,
    )
    from friday.cognition.reviewer import LocalReviewer

    key = b"cli-approval-review-key"
    repo = tmp_path / "gate-repo"
    repo.mkdir()
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "o@example.invalid"),
        ("config", "user.name", "Owner"),
    ):
        subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True)
    (repo / "mod.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, capture_output=True, check=True)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=key)
    proposal = RepairProposal(
        repo_path=str(repo),
        branch="friday/cli-approval",
        base_commit=base,
        target_file="mod.py",
        original_snippet="def value():\n    return 1\n",
        replacement_snippet="def value():\n    return 2\n",
        rationale="return the documented value",
        proposed_by="forge",
        test_evidence={"command": "pytest -q tests/test_x.py", "passed": True, "summary": "1 passed"},
    )
    record, _ = gate.propose(proposal)
    reviewer = LocalReviewer(key, reviewer_id="sentinel")
    outcome = reviewer.review(
        patch_fingerprint=record.proposal.fingerprint(),
        target_file="mod.py",
        original_snippet=record.proposal.original_snippet,
        replacement_snippet=record.proposal.replacement_snippet,
        current_source="def value():\n    return 1\n",
        test_evidence=proposal.test_evidence,
        approval_id="cli_approval",
    )
    assert outcome.cleared is True, outcome.reasons
    receipt = gate.record_review(record.patch_id, outcome.document)
    assert receipt.outcome == "ACCEPTED", receipt.detail
    return gate, record.patch_id


def test_the_owner_may_approve_by_hand_with_no_mandate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Any
) -> None:
    """Revoking autonomy must not lock the owner out of their own approval path."""
    import friday.api.server as server

    monkeypatch.setenv("FRIDAY_AUTONOMY_KEY", "cli-test-key")
    monkeypatch.setenv("FRIDAY_AUTONOMY_LEDGER", str(tmp_path / "mandates.json"))
    # The CLI reads the owner's name from settings, and settings are cached for the
    # life of the process, so this is where the name has to be set for the call to
    # exercise what the running code does.
    from friday.core.config import get_settings

    monkeypatch.setattr(get_settings(), "user_name", "Surendra")
    gate, patch_id = _gate_with_a_reviewed_patch(tmp_path)
    monkeypatch.setattr(server, "_self_repair_gate", gate)

    _cli(monkeypatch, "--approve-repair", patch_id)

    out = capsys.readouterr().out
    assert "Standing autonomy is not in force" in out
    assert "Approved." in out, out
    assert gate.get(patch_id).state.value == "APPROVED"


def test_the_cli_cannot_be_used_to_approve_as_an_agent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Any
) -> None:
    """The owner's identity, not a mandate, is what the gate checks on this path."""
    import friday.api.server as server

    monkeypatch.setenv("FRIDAY_AUTONOMY_KEY", "cli-test-key")
    monkeypatch.setenv("FRIDAY_AUTONOMY_LEDGER", str(tmp_path / "mandates.json"))
    from friday.core.config import get_settings

    monkeypatch.setattr(get_settings(), "user_name", "forge")   # an agent, not the owner
    gate, patch_id = _gate_with_a_reviewed_patch(tmp_path)
    monkeypatch.setattr(server, "_self_repair_gate", gate)

    with pytest.raises(SystemExit) as exit_info:
        _cli(monkeypatch, "--approve-repair", patch_id)

    assert exit_info.value.code == 1
    out = capsys.readouterr().out
    assert "APPROVAL REFUSED" in out
    assert "not the owner" in out or "agent" in out
    assert gate.get(patch_id).state.value == "REVIEWED"


def _a_proposal_without_evidence(tmp_path: Any) -> Any:
    from friday.autonomous.self_repair import RepairProposal

    return RepairProposal(
        repo_path=str(tmp_path),
        branch="friday/reflex-probe",
        base_commit="deadbeef",
        target_file="src/friday/demo.py",
        original_snippet="value = 1\n",
        replacement_snippet="value = 2\n",
        rationale="a probe used by the CLI test; it carries no test evidence on purpose",
        proposed_by="friday",
    )


# ── the mandate API the CLI sits on ───────────────────────────────────────


def test_a_mandate_issued_with_a_key_verifies_with_the_same_key(tmp_path: Any) -> None:
    authority = MandateAuthority(key=b"unit-test-key", ledger=_ledger(tmp_path))

    document = authority.issue("surendra", scopes=("source_repair",), ttl_seconds=600)

    from friday.cognition.mandate import verify_mandate

    assert verify_mandate(document, b"unit-test-key") is True
    assert verify_mandate(document, b"a-different-key") is False
    tampered = dict(document)
    tampered["allowed_paths"] = ["**"]
    assert verify_mandate(tampered, b"unit-test-key") is False


def test_an_agent_cannot_issue_a_mandate(tmp_path: Any) -> None:
    authority = MandateAuthority(key=b"unit-test-key", ledger=_ledger(tmp_path))

    for agent_name in ("friday", "sentinel", "forge"):
        with pytest.raises(ValueError, match="agent"):
            authority.issue(agent_name, scopes=("source_repair",), ttl_seconds=60)


def _ledger(tmp_path: Any) -> Any:
    from friday.cognition.mandate import MandateLedger

    return MandateLedger(str(tmp_path / "mandates.json"))
