"""The gate under a standing mandate: unattended repair without a forged identity.

The existing gate tests prove an agent can never approve a repair. These tests
prove the other half — that the *owner's* pre-signed delegation can, and only
within the bounds the owner wrote down. Together they are the whole point: FRIDAY
repairs itself without asking, and no agent ever approves its own work.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from friday.autonomous.self_repair import (
    GateRefusal,
    GitRepairApplier,
    RepairProposal,
    RepairState,
    SelfRepairGate,
)
from friday.cognition.mandate import (
    SCOPE_CONFIG_REPAIR,
    SCOPE_SOURCE_REPAIR,
    AutonomyMandate,
    MandateAuthority,
    MandateLedger,
)

PASSING_TESTS = {"command": "pytest -q tests/test_thing.py", "passed": True, "summary": "12 passed"}
REVIEW_KEY = b"unit-test-review-key"
MANDATE_KEY = b"unit-test-mandate-key"
_approval_seq = [0]


def _sign_review(patch_fingerprint: str, key: bytes = REVIEW_KEY) -> dict:
    import hashlib
    import hmac
    import json
    import time

    _approval_seq[0] += 1
    body = {
        "patch_fingerprint": patch_fingerprint,
        "verdict": "clear",
        "reviewer": "sentinel",
        "approval_id": f"appr_test_{_approval_seq[0]:04d}",
        "findings": ["no blockers"],
        "checks_run": ["test_evidence_present"],
        "issued_at": time.time(),
        "nonce": f"nonce_{_approval_seq[0]:04d}",
    }
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    body["signature"] = hmac.new(key, digest.encode(), hashlib.sha256).hexdigest()
    return body


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True, timeout=30
    )
    return proc.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repairable"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@localhost")
    _git(root, "config", "user.name", "Test")
    (root / "src").mkdir()
    (root / "src" / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


@pytest.fixture
def authority(tmp_path: Path) -> MandateAuthority:
    return MandateAuthority(
        key=MANDATE_KEY,
        ledger=MandateLedger(str(tmp_path / "mandates.json")),
        allow_auto_issue=False,
    )


def _proposed(gate: SelfRepairGate, repo: Path, target: str = "src/calc.py") -> str:
    base = _git(repo, "rev-parse", "HEAD")
    proposal = RepairProposal(
        repo_path=str(repo),
        branch="repair/add-operator",
        base_commit=base,
        target_file=target,
        original_snippet="    return a - b",
        replacement_snippet="    return a + b",
        rationale="add() subtracts; the operator is wrong",
        proposed_by="forge",
        test_evidence=PASSING_TESTS,
    )
    record, _ = gate.propose(proposal)
    gate.record_review(record.patch_id, _sign_review(record.proposal.fingerprint()))
    return record.patch_id


def _reviewed_gate(repo: Path) -> SelfRepairGate:
    return SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)


class TestMandateApproval:
    """The owner's pre-recorded authority advances the pipeline."""

    def test_a_signed_mandate_approves_a_fingerprint_bound_patch(
        self, repo: Path, authority: MandateAuthority
    ) -> None:
        gate = _reviewed_gate(repo)
        patch_id = _proposed(gate, repo)
        document = authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), ttl_seconds=600)

        receipt = gate.record_mandate_decision(patch_id, document, MANDATE_KEY)

        assert receipt.outcome == "ACCEPTED"
        assert receipt.evidence["signature_verified"] is True
        assert receipt.evidence["mandate_id"] == document["mandate_id"]
        assert gate.get(patch_id).state is RepairState.APPROVED

    def test_the_approval_still_expires_and_is_single_use(
        self, repo: Path, authority: MandateAuthority
    ) -> None:
        """A mandate replaces the keystroke, not the guards around it."""
        gate = _reviewed_gate(repo)
        patch_id = _proposed(gate, repo)
        document = authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), ttl_seconds=600)
        gate.record_mandate_decision(patch_id, document, MANDATE_KEY)

        applied = gate.apply(patch_id)
        assert applied.outcome == "ACCEPTED"
        assert (repo / "src" / "calc.py").read_text(encoding="utf-8").endswith("return a + b\n")

        replayed = gate.apply(patch_id)
        assert replayed.outcome == "REFUSED"
        assert GateRefusal.APPROVAL_CONSUMED.value in replayed.detail

    def test_a_repair_under_mandate_still_rolls_back(
        self, repo: Path, authority: MandateAuthority
    ) -> None:
        gate = _reviewed_gate(repo)
        patch_id = _proposed(gate, repo)
        document = authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), ttl_seconds=600)
        gate.record_mandate_decision(patch_id, document, MANDATE_KEY)
        gate.apply(patch_id)

        rolled = gate.rollback(patch_id)
        assert rolled.outcome == "ACCEPTED"
        assert (repo / "src" / "calc.py").read_text(encoding="utf-8").endswith("return a - b\n")


class TestMandateRefusals:
    """Every way a mandate can fail to cover a repair, named."""

    def test_an_unsigned_document_is_refused(self, repo: Path, authority: MandateAuthority) -> None:
        gate = _reviewed_gate(repo)
        patch_id = _proposed(gate, repo)
        document = authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), ttl_seconds=600)
        document["scopes"] = [SCOPE_SOURCE_REPAIR, SCOPE_CONFIG_REPAIR]  # widened after signing

        receipt = gate.record_mandate_decision(patch_id, document, MANDATE_KEY)
        assert receipt.outcome == "REFUSED"
        assert GateRefusal.BAD_MANDATE_SIGNATURE.value in receipt.detail
        assert gate.get(patch_id).state is RepairState.REVIEWED

    def test_a_mandate_signed_with_another_key_is_refused(
        self, repo: Path, authority: MandateAuthority
    ) -> None:
        gate = _reviewed_gate(repo)
        patch_id = _proposed(gate, repo)
        document = authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), ttl_seconds=600)

        receipt = gate.record_mandate_decision(patch_id, document, b"a-thiefs-key")
        assert receipt.outcome == "REFUSED"
        assert GateRefusal.BAD_MANDATE_SIGNATURE.value in receipt.detail

    def test_an_agent_issued_mandate_is_refused_even_when_correctly_signed(
        self, repo: Path
    ) -> None:
        """A delegate cannot redelegate: FRIDAY may not widen its own authority."""
        gate = _reviewed_gate(repo)
        patch_id = _proposed(gate, repo)
        forged = AutonomyMandate(issued_by="friday", scopes=(SCOPE_SOURCE_REPAIR,))
        document = forged.sign(MANDATE_KEY)

        receipt = gate.record_mandate_decision(patch_id, document, MANDATE_KEY)
        assert receipt.outcome == "REFUSED"
        assert GateRefusal.WRONG_APPROVER.value in receipt.detail
        assert "agent, not the owner" in receipt.detail

    def test_an_expired_mandate_is_refused(self, repo: Path) -> None:
        gate = _reviewed_gate(repo)
        patch_id = _proposed(gate, repo)
        import time

        stale = AutonomyMandate(
            issued_by="surendra",
            scopes=(SCOPE_SOURCE_REPAIR,),
            issued_at=time.time() - 7200,
            expires_at=time.time() - 60,
        )
        receipt = gate.record_mandate_decision(patch_id, stale.sign(MANDATE_KEY), MANDATE_KEY)
        assert receipt.outcome == "REFUSED"
        assert GateRefusal.MANDATE_EXPIRED.value in receipt.detail

    def test_a_mandate_without_the_repair_scope_is_refused(self, repo: Path) -> None:
        gate = _reviewed_gate(repo)
        patch_id = _proposed(gate, repo)
        narrow = AutonomyMandate(issued_by="surendra", scopes=("dependency_install",))
        receipt = gate.record_mandate_decision(patch_id, narrow.sign(MANDATE_KEY), MANDATE_KEY)
        assert receipt.outcome == "REFUSED"
        assert GateRefusal.MANDATE_SCOPE.value in receipt.detail

    def test_a_mandate_that_does_not_permit_the_file_is_refused(self, repo: Path) -> None:
        gate = _reviewed_gate(repo)
        patch_id = _proposed(gate, repo)
        narrow = AutonomyMandate(
            issued_by="surendra", scopes=(SCOPE_SOURCE_REPAIR,), allowed_paths=("docs/**",)
        )
        receipt = gate.record_mandate_decision(patch_id, narrow.sign(MANDATE_KEY), MANDATE_KEY)
        assert receipt.outcome == "REFUSED"
        assert GateRefusal.MANDATE_PATH.value in receipt.detail

    def test_a_mandate_cannot_skip_the_review_step(self, repo: Path, authority: MandateAuthority) -> None:
        """The mandate replaces the owner's keystroke, not Sentinel's review."""
        gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)
        base = _git(repo, "rev-parse", "HEAD")
        proposal = RepairProposal(
            repo_path=str(repo),
            branch="repair/unreviewed",
            base_commit=base,
            target_file="src/calc.py",
            original_snippet="    return a - b",
            replacement_snippet="    return a + b",
            rationale="operator is wrong",
            proposed_by="forge",
            test_evidence=PASSING_TESTS,
        )
        record, _ = gate.propose(proposal)
        document = authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), ttl_seconds=600)

        receipt = gate.record_mandate_decision(record.patch_id, document, MANDATE_KEY)
        assert receipt.outcome == "REFUSED"
        assert GateRefusal.NOT_REVIEWED.value in receipt.detail

    def test_an_empty_document_is_refused(self, repo: Path, authority: MandateAuthority) -> None:
        gate = _reviewed_gate(repo)
        patch_id = _proposed(gate, repo)
        receipt = gate.record_mandate_decision(patch_id, {}, MANDATE_KEY)
        assert receipt.outcome == "REFUSED"
        assert GateRefusal.MALFORMED_MANDATE.value in receipt.detail

    def test_an_unknown_patch_is_refused_not_crashed(self, repo: Path, authority: MandateAuthority) -> None:
        gate = _reviewed_gate(repo)
        document = authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), ttl_seconds=600)
        receipt = gate.record_mandate_decision("patch_does_not_exist", document, MANDATE_KEY)
        assert receipt.outcome == "REFUSED"
        assert GateRefusal.NOT_PROPOSED.value in receipt.detail

    def test_editing_the_patch_after_a_mandate_approval_invalidates_it(
        self, repo: Path, authority: MandateAuthority
    ) -> None:
        """The fingerprint binding survives the mandate path unchanged."""
        gate = _reviewed_gate(repo)
        patch_id = _proposed(gate, repo)
        document = authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), ttl_seconds=600)
        gate.record_mandate_decision(patch_id, document, MANDATE_KEY)

        gate.get(patch_id).proposal.replacement_snippet = "    return a * b"
        receipt = gate.apply(patch_id)
        assert receipt.outcome == "REFUSED"
        assert GateRefusal.FINGERPRINT_MISMATCH.value in receipt.detail

    def test_the_agent_deny_list_still_holds_alongside_mandates(
        self, repo: Path, authority: MandateAuthority
    ) -> None:
        """Adding a mandate path must not have opened the named-approver path."""
        gate = _reviewed_gate(repo)
        patch_id = _proposed(gate, repo)
        for impostor in ("friday", "forge", "sentinel", "system", "  "):
            receipt = gate.record_owner_decision(patch_id, impostor, True)
            assert receipt.outcome == "REFUSED", f"{impostor!r} approved its own work"
        assert gate.get(patch_id).state is RepairState.REVIEWED


class TestAuthorityApprovalBridge:
    """`MandateAuthority.approve_repair` is the end-to-end unattended path."""

    def test_it_approves_when_the_mandate_covers_the_change(
        self, repo: Path, authority: MandateAuthority
    ) -> None:
        gate = _reviewed_gate(repo)
        patch_id = _proposed(gate, repo)
        authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), allowed_paths=("src/**",), ttl_seconds=600)

        receipt = authority.approve_repair(gate, patch_id)
        assert receipt.outcome == "ACCEPTED"
        assert gate.apply(patch_id).outcome == "ACCEPTED"

    def test_it_refuses_with_a_verdict_when_no_mandate_is_in_force(
        self, repo: Path, authority: MandateAuthority
    ) -> None:
        gate = _reviewed_gate(repo)
        patch_id = _proposed(gate, repo)

        verdict = authority.approve_repair(gate, patch_id)
        assert verdict.allowed is False
        assert gate.get(patch_id).state is RepairState.REVIEWED
        assert gate.apply(patch_id).outcome == "REFUSED"

    def test_it_refuses_when_the_change_is_outside_the_granted_paths(
        self, repo: Path, authority: MandateAuthority
    ) -> None:
        gate = _reviewed_gate(repo)
        patch_id = _proposed(gate, repo)
        authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), allowed_paths=("docs/**",), ttl_seconds=600)

        verdict = authority.approve_repair(gate, patch_id)
        assert verdict.allowed is False
        assert verdict.refusal == "FILE_NOT_PERMITTED"

    def test_using_a_mandate_spends_its_budget(self, repo: Path, authority: MandateAuthority) -> None:
        gate = _reviewed_gate(repo)
        patch_id = _proposed(gate, repo)
        document = authority.issue(
            "surendra", scopes=(SCOPE_SOURCE_REPAIR,), allowed_paths=("src/**",), max_changes=1, ttl_seconds=600
        )
        authority.approve_repair(gate, patch_id)
        assert authority._ledger.consumed(document["mandate_id"]) == 1
