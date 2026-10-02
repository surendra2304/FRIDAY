"""The gate must verify a review, not believe one.

Phase E1. The previous contract took ``reviewer="sentinel"`` on trust, so anyone
who could reach the review endpoint could assert that the security agent had
cleared their patch. These tests pin the replacement: a review is a signed
document, and the gate checks the signature, the binding, the freshness and the
single-use property before it will act on a verdict.

The signing helper is re-implemented in this file on purpose. If the test imported
Sentinel's signer, a bug that broke both sides identically would pass.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path

import pytest

from friday.autonomous.self_repair import (
    GateRefusal,
    GitRepairApplier,
    RepairProposal,
    RepairState,
    SelfRepairGate,
)

REVIEW_KEY = b"review-key-for-tests"
WRONG_KEY = b"a-different-key-entirely"
_seq = [0]


def _body(
    fingerprint: str,
    verdict: str = "clear",
    approval_id: str | None = None,
    issued_at: float | None = None,
    reviewer: str = "sentinel",
) -> dict:
    _seq[0] += 1
    return {
        "patch_fingerprint": fingerprint,
        "verdict": verdict,
        "reviewer": reviewer,
        "approval_id": approval_id or f"appr_t{_seq[0]:04d}",
        "findings": ["looks fine"],
        "checks_run": ["test_evidence_present"],
        "issued_at": time.time() if issued_at is None else issued_at,
        "nonce": f"n{_seq[0]:04d}",
    }


def _sign(body: dict, key: bytes = REVIEW_KEY) -> dict:
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {**body, "signature": hmac.new(key, digest.encode(), hashlib.sha256).hexdigest()}


def _repo(tmp_path: Path) -> Path:
    import subprocess

    root = tmp_path / "r"
    root.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, capture_output=True, check=True, timeout=60)

    git("init", "-b", "main")
    git("config", "user.email", "t@localhost")
    git("config", "user.name", "T")
    (root / "f.py").write_text("def f():\n    return 1 - 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "init")
    return root


def _gate(repo: Path, key: bytes | None = REVIEW_KEY) -> tuple[SelfRepairGate, dict]:
    import subprocess

    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=key)
    record, _ = gate.propose(
        RepairProposal(
            repo_path=str(repo),
            branch="repair/x",
            base_commit=base,
            target_file="f.py",
            original_snippet="    return 1 - 1",
            replacement_snippet="    return 1 + 1",
            rationale="returns zero",
            test_evidence={"command": "pytest -q", "passed": True},
        )
    )
    return gate, {"record": record, "fingerprint": record.proposal.fingerprint()}


# ── the signature is what is checked ──────────────────────────────────────


def test_unsigned_review_is_refused(tmp_path: Path):
    gate, ctx = _gate(_repo(tmp_path))
    receipt = gate.record_review(ctx["record"].patch_id, _body(ctx["fingerprint"]))
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.BAD_REVIEW_SIGNATURE.value in receipt.detail
    # A forgery is a bad *attempt*, not a judgement on the patch: the record stays
    # open so that a genuine review can still arrive. Wedging it here would let
    # anyone DoS the pipeline by posting garbage.
    assert ctx["record"].state is RepairState.PROPOSED
    genuine = gate.record_review(ctx["record"].patch_id, _sign(_body(ctx["fingerprint"])))
    assert genuine.outcome == "ACCEPTED"
    assert ctx["record"].state is RepairState.REVIEWED


def test_review_signed_with_the_wrong_key_is_refused(tmp_path: Path):
    gate, ctx = _gate(_repo(tmp_path))
    receipt = gate.record_review(
        ctx["record"].patch_id, _sign(_body(ctx["fingerprint"]), WRONG_KEY)
    )
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.BAD_REVIEW_SIGNATURE.value in receipt.detail


def test_flipped_verdict_after_signing_is_refused(tmp_path: Path):
    gate, ctx = _gate(_repo(tmp_path))
    signed = _sign(_body(ctx["fingerprint"], verdict="clear"))
    forged = {**signed, "verdict": "block"}
    receipt = gate.record_review(ctx["record"].patch_id, forged)
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.BAD_REVIEW_SIGNATURE.value in receipt.detail


def test_swapped_fingerprint_after_signing_is_refused(tmp_path: Path):
    gate, ctx = _gate(_repo(tmp_path))
    signed = _sign(_body(ctx["fingerprint"]))
    forged = {**signed, "patch_fingerprint": "0" * 64}
    receipt = gate.record_review(ctx["record"].patch_id, forged)
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.BAD_REVIEW_SIGNATURE.value in receipt.detail


def test_added_field_after_signing_is_refused(tmp_path: Path):
    """Any change to the document invalidates it, including additions."""
    gate, ctx = _gate(_repo(tmp_path))
    signed = _sign(_body(ctx["fingerprint"]))
    receipt = gate.record_review(ctx["record"].patch_id, {**signed, "approved_by_owner": True})
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.BAD_REVIEW_SIGNATURE.value in receipt.detail


# ── the review must be about *this* patch ──────────────────────────────────


def test_review_for_a_different_patch_is_refused(tmp_path: Path):
    gate, ctx = _gate(_repo(tmp_path))
    receipt = gate.record_review(ctx["record"].patch_id, _sign(_body("0" * 64)))
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.REVIEW_WRONG_PATCH.value in receipt.detail


def test_review_signed_with_no_verification_key_configured_is_refused(tmp_path: Path):
    """Fail closed: with no key, no review can be believed, so none is."""
    gate, ctx = _gate(_repo(tmp_path), key=None)
    receipt = gate.record_review(ctx["record"].patch_id, _sign(_body(ctx["fingerprint"])))
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.NO_REVIEW_KEY.value in receipt.detail


# ── freshness and single use ──────────────────────────────────────────────


def test_stale_review_is_refused(tmp_path: Path):
    gate, ctx = _gate(_repo(tmp_path))
    ancient = time.time() - 86_400
    receipt = gate.record_review(
        ctx["record"].patch_id, _sign(_body(ctx["fingerprint"], issued_at=ancient))
    )
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.REVIEW_EXPIRED.value in receipt.detail


def test_review_with_a_missing_timestamp_is_refused(tmp_path: Path):
    gate, ctx = _gate(_repo(tmp_path))
    body = _body(ctx["fingerprint"])
    body.pop("issued_at")
    receipt = gate.record_review(ctx["record"].patch_id, _sign(body))
    assert receipt.outcome == "REFUSED"


def test_one_approval_cannot_be_spent_on_two_patches(tmp_path: Path):
    repo = _repo(tmp_path)
    gate, ctx = _gate(repo)
    import subprocess

    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    second, _ = gate.propose(
        RepairProposal(
            repo_path=str(repo),
            branch="repair/y",
            base_commit=base,
            target_file="f.py",
            original_snippet="def f():",
            replacement_snippet="def g():",
            rationale="rename",
            test_evidence={"command": "pytest -q", "passed": True},
        )
    )
    shared_approval = "appr_shared_0001"

    first = gate.record_review(
        ctx["record"].patch_id, _sign(_body(ctx["fingerprint"], approval_id=shared_approval))
    )
    assert first.outcome == "ACCEPTED"

    replay = gate.record_review(
        second.patch_id,
        _sign(_body(second.proposal.fingerprint(), approval_id=shared_approval)),
    )
    assert replay.outcome == "REFUSED"
    assert GateRefusal.REVIEW_APPROVAL_REPLAYED.value in replay.detail


# ── happy path still works, and is recorded as verified ───────────────────


def test_genuinely_signed_review_is_accepted_and_marked_verified(tmp_path: Path):
    gate, ctx = _gate(_repo(tmp_path))
    receipt = gate.record_review(ctx["record"].patch_id, _sign(_body(ctx["fingerprint"])))
    assert receipt.outcome == "ACCEPTED"
    assert ctx["record"].state is RepairState.REVIEWED
    assert ctx["record"].review["signature_verified"] is True
    assert receipt.evidence["signature_verified"] is True
    assert receipt.evidence["bound_fingerprint"] == ctx["fingerprint"]


def test_a_blocking_verdict_still_blocks_the_pipeline(tmp_path: Path):
    gate, ctx = _gate(_repo(tmp_path))
    receipt = gate.record_review(
        ctx["record"].patch_id, _sign(_body(ctx["fingerprint"], verdict="block"))
    )
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.REVIEW_REJECTED.value in receipt.detail
    assert ctx["record"].state is RepairState.BLOCKED
    assert gate.apply(ctx["record"].patch_id).outcome == "REFUSED"


def test_a_non_sentinel_reviewer_is_refused_even_when_signed(tmp_path: Path):
    """A valid signature from the wrong identity is still not a Sentinel review."""
    gate, ctx = _gate(_repo(tmp_path))
    receipt = gate.record_review(
        ctx["record"].patch_id, _sign(_body(ctx["fingerprint"], reviewer="forge"))
    )
    assert receipt.outcome == "REFUSED"
    assert GateRefusal.WRONG_REVIEWER.value in receipt.detail


def test_malformed_review_is_refused(tmp_path: Path):
    gate, ctx = _gate(_repo(tmp_path))
    for bad in ("not a dict", 42, None, []):
        receipt = gate.record_review(ctx["record"].patch_id, bad)
        assert receipt.outcome == "REFUSED", f"{bad!r} should be refused"
        assert GateRefusal.MALFORMED_REVIEW.value in receipt.detail
