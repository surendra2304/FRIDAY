"""BUG-011: authority came from a deny-list, so every unlisted name had it.

The audit found `NON_OWNER_ACTORS`, a set of fifteen agent names, guarding
approval. The comment above it claimed "a new agent added tomorrow is excluded by
default rather than admitted by omission", which was exactly backwards: a new agent
name, a typo, or any string a caller picked was admitted as the owner. Approval on
that path needs no key, so nothing else stood in the way.

The rule is now positive: an actor carries owner authority only by being the
configured owner (`FRIDAY_USER_NAME`) or the literal word "owner". These tests use
the real gate and the real mandate authority, and they name agents that do not
exist in this codebase - the case the old list could not cover.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from friday.autonomous.self_repair import (
    GitRepairApplier,
    RepairProposal,
    SelfRepairGate,
)
from friday.cognition.identity import is_owner_identity
from friday.cognition.mandate import AutonomyMandate, MandateAuthority
from tests.test_self_repair_gate import REVIEW_KEY
from tests.test_self_repair_gate import _sign_review as sign_review

MANDATE_KEY = b"identity-test-mandate-key"

#: Agents that do not exist today. Under the old rule every one of these could
#: approve a repair, because the list could only refuse names already on it.
FUTURE_AGENTS = ("atlas", "nova", "quill", "orion", "friday-2", "vault")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "o@example.invalid")
    _git(path, "config", "user.name", "Owner")
    (path / "mod.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "base")
    return path


def _reviewed_and_proposed(repo: Path) -> tuple[SelfRepairGate, str]:
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)
    base = _git(repo, "rev-parse", "HEAD")
    proposal = RepairProposal(
        repo_path=str(repo),
        branch="fix/identity",
        base_commit=base,
        target_file="mod.py",
        original_snippet="def value():\n    return 1\n",
        replacement_snippet="def value():\n    return 2\n",
        rationale="return the documented value",
        proposed_by="forge",
        test_evidence={"command": "pytest -q tests/test_thing.py", "passed": True, "summary": "1 passed"},
    )
    record, _ = gate.propose(proposal)
    # A review that passes, so the approval is the only step left.
    receipt = gate.record_review(record.patch_id, sign_review(record.proposal.fingerprint()))
    assert receipt.outcome == "ACCEPTED", receipt.detail
    assert gate.get(record.patch_id).state.value == "REVIEWED"
    return gate, record.patch_id


@pytest.mark.parametrize("agent", FUTURE_AGENTS)
def test_an_agent_that_does_not_exist_yet_cannot_approve(repo: Path, agent: str) -> None:
    gate, patch_id = _reviewed_and_proposed(repo)
    receipt = gate.record_owner_decision(patch_id, approver=agent, approve=True)

    assert receipt.outcome == "REFUSED", f"{agent!r} approved a repair"
    assert "WRONG_APPROVER" in receipt.detail
    assert gate.get(patch_id).state.value == "REVIEWED", "the refusal did not halt the pipeline"


def test_a_name_nobody_configured_cannot_approve(repo: Path) -> None:
    """An arbitrary string is not an owner just because it is not an agent name."""
    gate, patch_id = _reviewed_and_proposed(repo)
    receipt = gate.record_owner_decision(patch_id, approver="whoever-typed-this", approve=True)
    assert receipt.outcome == "REFUSED"
    assert "not an identified owner" in receipt.detail


def test_the_configured_owner_can_still_approve(repo: Path, monkeypatch) -> None:
    """The fix must not lock the owner out of their own machine."""
    monkeypatch.setenv("FRIDAY_USER_NAME", "Surendra")
    gate, patch_id = _reviewed_and_proposed(repo)
    receipt = gate.record_owner_decision(patch_id, approver="Surendra (CLI)", approve=True)

    assert receipt.outcome == "ACCEPTED", receipt.detail
    assert gate.get(patch_id).state.value == "APPROVED"


def test_the_literal_word_owner_is_accepted(repo: Path, monkeypatch) -> None:
    """An operator who never set a name is called this, and must still work."""
    monkeypatch.delenv("FRIDAY_USER_NAME", raising=False)
    monkeypatch.setattr("friday.cognition.identity.configured_owner_name", lambda: "Unset")
    gate, patch_id = _reviewed_and_proposed(repo)
    receipt = gate.record_owner_decision(patch_id, approver="owner", approve=True)
    assert receipt.outcome == "ACCEPTED", receipt.detail


def test_a_future_agent_cannot_issue_a_mandate(tmp_path: Path, monkeypatch) -> None:
    """The same hole existed on mandate issuance, so it is closed with the same rule."""
    monkeypatch.setenv("FRIDAY_AUTONOMY_KEY", MANDATE_KEY.hex())
    from friday.cognition.mandate import MandateLedger

    authority = MandateAuthority(key=MANDATE_KEY, ledger=MandateLedger(str(tmp_path / "mandates.json")))
    with pytest.raises(ValueError, match="not an identified owner"):
        authority.issue("atlas", scopes=("source_repair",))


def test_an_agent_signed_mandate_is_refused_even_with_a_valid_signature(repo: Path) -> None:
    """Signed by the real key, and still refused: the issuer must be the owner."""
    gate, patch_id = _reviewed_and_proposed(repo)
    forged = AutonomyMandate(issued_by="nova", scopes=("source_repair",))
    document = forged.sign(MANDATE_KEY)

    receipt = gate.record_mandate_decision(patch_id, document, MANDATE_KEY)
    assert receipt.outcome == "REFUSED"
    assert "WRONG_APPROVER" in receipt.detail


@pytest.mark.parametrize(
    "actor,expected",
    [
        ("owner", True),
        ("Owner (CLI)", True),
        ("friday", False),
        ("", False),
        ("  ", False),
        ("atlas", False),
        ("system", False),
    ],
)
def test_the_identity_rule_itself(actor: str, expected: bool, monkeypatch) -> None:
    monkeypatch.setattr("friday.cognition.identity.configured_owner_name", lambda: "Surendra")
    assert is_owner_identity(actor) is expected
