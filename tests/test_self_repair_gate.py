"""End-to-end tests for the gated self-repair pipeline.

These run against a **real** throwaway git repository, so the receipts under
assertion come from real branches and real commits. A mocked git would prove the
state machine but not that a repair can actually be applied and rolled back.
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

PASSING_TESTS = {"command": "pytest -q tests/test_thing.py", "passed": True, "summary": "12 passed"}

#: The shared key the gate and Sentinel's reviewer would hold in deployment.
REVIEW_KEY = b"unit-test-review-key"
_approval_seq = [0]


def _sign_review(
    patch_fingerprint: str,
    verdict: str = "clear",
    key: bytes = REVIEW_KEY,
    approval_id: str | None = None,
    issued_at: float | None = None,
    findings: tuple[str, ...] = ("no blockers",),
) -> dict:
    """Build a review document signed the way Sentinel signs one.

    Deliberately re-implemented here rather than imported from Sentinel: the gate
    must be able to verify a review without executing the signer's code, and a
    test that shares the signer's implementation proves nothing about the gate.
    """
    import hashlib
    import hmac
    import json
    import time

    _approval_seq[0] += 1
    body = {
        "patch_fingerprint": patch_fingerprint,
        "verdict": verdict,
        "reviewer": "sentinel",
        "approval_id": approval_id or f"appr_test_{_approval_seq[0]:04d}",
        "findings": list(findings),
        "checks_run": ["test_evidence_present", "no_hardcoded_credentials"],
        "issued_at": time.time() if issued_at is None else issued_at,
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
    """A real git repo with one committed file to repair."""
    root = tmp_path / "repairable"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@localhost")
    _git(root, "config", "user.name", "Test")
    (root / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _proposal(repo: Path, base: str, **overrides) -> RepairProposal:
    defaults = dict(
        repo_path=str(repo),
        branch="repair/add-operator",
        base_commit=base,
        target_file="calc.py",
        original_snippet="    return a - b",
        replacement_snippet="    return a + b",
        rationale="add() subtracts; the operator is wrong",
        proposed_by="forge",
        test_evidence=PASSING_TESTS,
    )
    defaults.update(overrides)
    return RepairProposal(**defaults)


def _fully_approved(
    gate: SelfRepairGate,
    patch_id: str,
    approver: str = "surendra",
    fingerprint: str | None = None,
) -> None:
    record = gate.get(patch_id)
    target = fingerprint or record.proposal.fingerprint()
    gate.record_review(patch_id, _sign_review(target))
    gate.record_owner_decision(patch_id, approver=approver, approve=True)


# ── the happy path, on a real repository ──────────────────────────────────


def test_approved_repair_applies_and_rolls_back_for_real(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    base_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    assert base_branch == "main", "the fixture is not on the branch the owner works on"
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)

    record, receipt = gate.propose(_proposal(repo, base))
    assert receipt.outcome == "ACCEPTED"
    assert record.state is RepairState.PROPOSED

    signed = _sign_review(record.proposal.fingerprint())
    assert gate.record_review(record.patch_id, signed).outcome == "ACCEPTED"
    assert record.state is RepairState.REVIEWED

    assert gate.record_owner_decision(record.patch_id, "surendra", True).outcome == "ACCEPTED"
    assert record.state is RepairState.APPROVED

    applied = gate.apply(record.patch_id)
    assert applied.outcome == "ACCEPTED"
    assert record.state is RepairState.APPLIED

    # Real commits on a real branch, and the file really changed. The work lands on
    # the branch the owner is working on: a repair that leaves the repository checked
    # out on a side branch is not applied to the tree the owner is looking at, and
    # the next install would stack on top of it. Found by driving a real install in a
    # fresh clone, where the tools ended up on capability/* while HEAD sat there.
    assert applied.evidence["branch"] == "repair/add-operator"
    assert applied.evidence["branch_before"] == "main"
    assert applied.evidence["merged_into"] == "main"
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main", (
        "the repair left the repository checked out on the side branch"
    )
    assert applied.evidence["applied_commit"] == _git(repo, "rev-parse", "HEAD"), (
        "the owner's branch does not hold the repair that was reported applied"
    )
    assert _git(repo, "rev-parse", "repair/add-operator") == applied.evidence["applied_commit"], (
        "the repair branch does not point at the commit that was applied"
    )
    assert _git(repo, "diff", "--stat", "repair/add-operator", "HEAD") == "", (
        "the owner's branch and the repair branch disagree"
    )
    assert _git(repo, "status", "--porcelain") == "", (
        "the repair left files staged or modified in the owner's tree"
    )
    assert _git(repo, "show", "HEAD:calc.py").strip().endswith("return a + b")
    assert applied.evidence["rollback_point"] == base

    reverted = gate.rollback(record.patch_id)
    assert reverted.outcome == "ACCEPTED"
    assert record.state is RepairState.ROLLED_BACK

    # Rollback restored the reviewed content, and left the reversal auditable.
    assert _git(repo, "show", "HEAD:calc.py").strip().endswith("return a - b")
    assert reverted.evidence["revert_commit"] == _git(repo, "rev-parse", "HEAD")
    assert reverted.evidence["reverted_commit"] == applied.evidence["applied_commit"]


# ── the gate: every unsafe path is refused ────────────────────────────────


def test_proposal_without_passing_tests_is_refused(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)

    for bad in (None, {}, {"command": "pytest -q", "passed": False}, {"passed": True}):
        record, receipt = gate.propose(_proposal(repo, base, test_evidence=bad))
        assert receipt.outcome == "REFUSED", f"should refuse {bad!r}"
        assert GateRefusal.NO_TEST_EVIDENCE.value in receipt.detail
        assert record.state is RepairState.BLOCKED
        # Refused at propose: nothing was ever written.
        assert not (repo / "repair").exists()
        assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_patch_that_changes_nothing_is_refused(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)

    _, receipt = gate.propose(
        _proposal(repo, base, original_snippet="x", replacement_snippet="x")
    )
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.EMPTY_PATCH.value in receipt.detail


def test_the_proposer_cannot_review_its_own_patch(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)
    record, _ = gate.propose(_proposal(repo, base))

    for impostor in ("forge", "friday", ""):
        receipt = gate.record_review(
            record.patch_id, {**_sign_review(record.proposal.fingerprint()), "reviewer": impostor}
        )
        assert receipt.outcome == "REFUSED"
        assert GateRefusal.WRONG_REVIEWER.value in receipt.detail

    signed = _sign_review(record.proposal.fingerprint())
    assert gate.record_review(record.patch_id, signed).outcome == "ACCEPTED"


def test_a_rejected_review_blocks_the_pipeline(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)
    record, _ = gate.propose(_proposal(repo, base))

    receipt = gate.record_review(
        record.patch_id, _sign_review(record.proposal.fingerprint(), verdict="block")
    )
    assert receipt.outcome == "REFUSED"
    assert record.state is RepairState.BLOCKED

    # And no amount of owner enthusiasm gets it applied.
    gate.record_owner_decision(record.patch_id, "surendra", True)
    assert gate.apply(record.patch_id).outcome == "REFUSED"
    assert _git(repo, "show", "HEAD:calc.py").strip().endswith("return a - b")


def test_unreviewed_patch_cannot_be_approved_or_applied(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)
    record, _ = gate.propose(_proposal(repo, base))

    receipt = gate.record_owner_decision(record.patch_id, "surendra", True)
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.NOT_REVIEWED.value in receipt.detail

    assert gate.apply(record.patch_id).outcome == "REFUSED"
    assert _git(repo, "show", "HEAD:calc.py").strip().endswith("return a - b")


def test_an_agent_cannot_approve_its_own_patch(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)
    record, _ = gate.propose(_proposal(repo, base))
    gate.record_review(record.patch_id, _sign_review(record.proposal.fingerprint()))

    # Every agent in the universe, including FRIDAY itself, which is the component
    # that would carry the repair out. Approval is a human act.
    for impostor in ("friday", "forge", "sentinel", "futuris", "  ", "bot", "system"):
        receipt = gate.record_owner_decision(record.patch_id, impostor, True)
        assert receipt.outcome == "REFUSED", f"{impostor!r} should not be able to approve"
        assert GateRefusal.WRONG_APPROVER.value in receipt.detail

    assert record.state is RepairState.REVIEWED


def test_apply_without_approval_is_refused(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)
    record, _ = gate.propose(_proposal(repo, base))
    gate.record_review(record.patch_id, _sign_review(record.proposal.fingerprint()))

    receipt = gate.apply(record.patch_id)
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.NOT_APPROVED.value in receipt.detail
    assert _git(repo, "show", "HEAD:calc.py").strip().endswith("return a - b")


def test_approval_is_single_use(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)
    record, _ = gate.propose(_proposal(repo, base))
    _fully_approved(gate, record.patch_id)

    assert gate.apply(record.patch_id).outcome == "ACCEPTED"
    assert record.approval.consumed is True

    replay = gate.apply(record.patch_id)
    assert replay.outcome == "REFUSED"
    assert GateRefusal.APPROVAL_CONSUMED.value in replay.detail
    # The refusal must not strand the record: rollback is still reachable.
    assert gate.rollback(record.patch_id).outcome == "ACCEPTED"
    assert record.state is RepairState.ROLLED_BACK


def test_expired_approval_is_refused(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)
    record, _ = gate.propose(_proposal(repo, base))
    _fully_approved(gate, record.patch_id)

    # Age the approval past its TTL rather than sleeping for it.
    record.approval.expires_at = record.approval.approved_at

    receipt = gate.apply(record.patch_id)
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.APPROVAL_EXPIRED.value in receipt.detail
    assert _git(repo, "show", "HEAD:calc.py").strip().endswith("return a - b")


def test_editing_the_patch_after_approval_invalidates_it(repo: Path):
    """The approval is bound to the patch, not to the patch's paperwork."""
    base = _git(repo, "rev-parse", "HEAD")
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)
    record, _ = gate.propose(_proposal(repo, base))
    _fully_approved(gate, record.patch_id)

    approved_fingerprint = record.approval.patch_fingerprint
    record.proposal.replacement_snippet = "    return a * b  # sneaky"

    receipt = gate.apply(record.patch_id)
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.FINGERPRINT_MISMATCH.value in receipt.detail
    assert record.approval.patch_fingerprint == approved_fingerprint
    assert _git(repo, "show", "HEAD:calc.py").strip().endswith("return a - b")


def test_rewording_the_rationale_keeps_the_approval_valid(repo: Path):
    """Rationale is prose, not payload: editing it must not void an approval."""
    base = _git(repo, "rev-parse", "HEAD")
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)
    record, _ = gate.propose(_proposal(repo, base))
    _fully_approved(gate, record.patch_id)

    record.proposal.rationale = "reworded explanation, same code change"
    assert gate.apply(record.patch_id).outcome == "ACCEPTED"


def test_patch_is_refused_when_the_reviewed_content_is_not_at_the_base_commit(repo: Path):
    """The proposal's claimed 'before' text must actually exist at its base commit.

    This is the case the guard exists for: a proposal whose stated original text
    does not match the revision it pins. Applying it would mean the review was of
    code that is not the code being changed.
    """
    base = _git(repo, "rev-parse", "HEAD")
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)

    # The file at `base` says "a - b". This proposal claims it says "a // b".
    record, _ = gate.propose(
        _proposal(repo, base, original_snippet="    return a // b", replacement_snippet="    return a + b")
    )
    _fully_approved(gate, record.patch_id)

    receipt = gate.apply(record.patch_id)
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.GIT_FAILED.value in receipt.detail
    assert "no longer present" in receipt.detail
    # And the working tree is untouched.
    assert (repo / "calc.py").read_text(encoding="utf-8").strip().endswith("return a - b")


def test_patch_is_refused_when_the_reviewed_text_is_ambiguous(repo: Path):
    """Two occurrences of the same reviewed text: refuse rather than guess."""
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n", encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "duplicate the line")
    base = _git(repo, "rev-parse", "HEAD")

    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)
    record, _ = gate.propose(_proposal(repo, base))
    _fully_approved(gate, record.patch_id)

    receipt = gate.apply(record.patch_id)
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.GIT_FAILED.value in receipt.detail
    assert "which occurrence" in receipt.detail


def test_rollback_without_an_apply_is_refused(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)
    record, _ = gate.propose(_proposal(repo, base))

    receipt = gate.rollback(record.patch_id)
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.NOTHING_TO_ROLL_BACK.value in receipt.detail


def test_gate_without_an_applier_never_claims_to_have_applied(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    gate = SelfRepairGate(review_verification_key=REVIEW_KEY)  # no applier wired
    record, _ = gate.propose(_proposal(repo, base))
    _fully_approved(gate, record.patch_id)

    receipt = gate.apply(record.patch_id)
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.NO_CHECKPOINT.value in receipt.detail
    # Not terminal: nothing was half-applied, and the record stays auditable.
    assert record.state is RepairState.APPROVED
    assert record.applied_commit is None


def test_unknown_patch_ids_are_refused_not_crashed(repo: Path):
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)
    assert gate.apply("patch_9999").outcome == "REFUSED"
    assert gate.rollback("patch_9999").outcome == "REFUSED"
    assert gate.record_review("patch_9999", _sign_review("0" * 64)).outcome == "REFUSED"
    assert gate.record_owner_decision("patch_9999", "surendra", True).outcome == "REFUSED"
    assert gate.get("patch_9999") is None


# ── the receipts are the audit trail ──────────────────────────────────────


def test_every_attempt_leaves_a_receipt_with_honest_labels(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)
    record, _ = gate.propose(_proposal(repo, base))
    _fully_approved(gate, record.patch_id)
    gate.apply(record.patch_id)
    gate.rollback(record.patch_id)
    gate.apply(record.patch_id)  # the replayed one

    assert [r.step for r in record.receipts] == [
        "propose",
        "review",
        "owner_decision",
        "apply",
        "rollback",
        "apply",
    ]
    assert [r.outcome for r in record.receipts] == [
        "ACCEPTED",
        "ACCEPTED",
        "ACCEPTED",
        "ACCEPTED",
        "ACCEPTED",
        "REFUSED",
    ]
    for receipt in record.receipts:
        assert receipt.evidence_class == "pipeline_transition"
        assert receipt.at

    payload = record.as_dict()
    assert payload["state"] == "ROLLED_BACK"
    # The propose receipt proves nothing was written; the apply receipt proves one file was.
    propose_receipt = next(r for r in payload["receipts"] if r["step"] == "propose")
    apply_receipt = next(r for r in payload["receipts"] if r["step"] == "apply")
    assert propose_receipt["evidence"]["files_touched"] == 0
    assert apply_receipt["evidence"]["files_touched"] == 1


def test_a_repair_whose_commit_is_rejected_restores_the_file_it_rewrote(repo: Path):
    """A refusal after the write must leave the reviewed file exactly as it was.

    The installer's version of this is a new file that must disappear. A repair of an
    existing file is the other half: the file is *modified* before the commit is
    rejected, so "leave no trace" means putting the reviewed content back — not
    deleting the owner's file.
    """
    base = _git(repo, "rev-parse", "HEAD")
    base_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    before = (repo / "calc.py").read_text(encoding="utf-8")

    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)

    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)
    record, receipt = gate.propose(_proposal(repo, base))
    assert receipt.outcome == "ACCEPTED"
    _fully_approved(gate, record.patch_id)

    applied = gate.apply(record.patch_id)
    assert applied.outcome == "REFUSED", applied.as_dict()
    assert "GIT_FAILED" in applied.detail
    assert record.state is RepairState.APPROVED, "a refused apply consumed the approval"

    # The file is back, byte for byte, and the repository is where the owner left it.
    assert (repo / "calc.py").read_text(encoding="utf-8") == before, (
        "the refused repair left the half-applied content in the owner's file"
    )
    assert _git(repo, "rev-parse", "HEAD") == base, "the refused repair moved HEAD"
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == base_branch, (
        "the refused repair left the repository on the repair branch"
    )
    assert _git(repo, "status", "--porcelain", "--untracked-files=no") == "", (
        "the refused repair left the change staged"
    )

    # The approval is intact, so the owner can fix the repository and apply again.
    hook.unlink()
    retried = gate.apply(record.patch_id)
    assert retried.outcome == "ACCEPTED", retried.as_dict()
    assert _git(repo, "show", "HEAD:calc.py").strip().endswith("return a + b")
