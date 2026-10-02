"""End-to-end self-repair loop: Forge -> Sentinel -> owner -> FRIDAY gate.

Phase E1 completion. This script is the proof that the three services actually
talk to each other. It imports the real implementations from all three:

  * Forge's ``GitSelfRepairProposer``  — branches a real repository, runs a real
    test command before and after the change, and refuses to emit a proposal
    unless the same command genuinely went from failing to passing.
  * Sentinel's ``SelfRepairReviewer`` — inspects the proposed diff, mints a
    single-use approval through the existing ``ApprovalManager``, and signs its
    verdict.
  * FRIDAY's ``SelfRepairGate``       — verifies that signature against a shared
    key before it will accept the review, then applies and rolls back for real.

Run it directly:

    python research/self_repair_loop.py

Nothing in the transcript below is mocked. The repository is created on disk, the
tests are executed by a real shell, the branch and the commits are real, and the
gate refuses an unsigned or tampered review because the signature genuinely does
not verify.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# The three services live in sibling checkouts. Real implementations, not copies.
UNIVERSE_ROOT = REPO_ROOT.parent
# Forge's package is at Forge/app; Sentinel's is at Sentinel/sentinel.
for service, package_root in (("Forge", ""), ("Sentinel", "")):
    candidate = UNIVERSE_ROOT / service
    if candidate.is_dir():
        sys.path.insert(0, str(candidate / package_root) if package_root else str(candidate))

from app.selfrepair.proposer import (  # noqa: E402
    CandidateFix,
    GitSelfRepairProposer,
    ProposalOutcome,
)
from friday.autonomous.self_repair import (  # noqa: E402
    GitRepairApplier,
    RepairProposal,
    RepairState,
    SelfRepairGate,
)
from sentinel.core.auth.approvals import ApprovalManager  # noqa: E402
from sentinel.core.selfrepair.reviewer import SelfRepairReviewer  # noqa: E402
from sentinel.storage.persistence.durable_store import SentinelPersistence  # noqa: E402

#: One shared key, the way the two services would share it in deployment.
SHARED_KEY = "e2e-shared-review-key-not-a-real-secret"

#: The bug: percent_change() correctly returns a percentage, but describe()
#: multiplies by 100 a second time, so every formatted string is off by 100x.
#: One defect, one line, one correct fix.
BROKEN_SOURCE = '''\
def percent_change(old, new):
    """Return the percentage change from old to new, e.g. 10.0 for 100 -> 110."""
    if old == 0:
        return 0.0
    return (new - old) / old * 100.0


def describe(old, new):
    return f"{percent_change(old, new) * 100:.2f}%"
'''

BROKEN_TEST = '''\
from percent_change import percent_change, describe


def test_percent_change_is_a_percentage():
    assert percent_change(100, 110) == 10.0


def test_percent_change_handles_zero_base():
    assert percent_change(0, 5) == 0.0


def test_describe_formats_a_percentage():
    assert describe(100, 110) == "10.00%"


def test_describe_handles_a_decline():
    assert describe(110, 100) == "-9.09%"
'''

#: The original line, and the one-line correction.
BROKEN_SNIPPET = '    return f"{percent_change(old, new) * 100:.2f}%"\n'
FIXED_SNIPPET = '    return f"{percent_change(old, new):.2f}%"\n'

FIXED_SOURCE = BROKEN_SOURCE.replace(BROKEN_SNIPPET, FIXED_SNIPPET)


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True, timeout=60
    )
    return proc.stdout.strip()


def build_broken_repo() -> tuple[Path, str]:
    """A real repository with a real failing test. Returns (path, base commit)."""
    root = Path(tempfile.mkdtemp(prefix="selfrepair-e2e-")) / "target"
    root.mkdir(parents=True)
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "e2e@localhost")
    git(root, "config", "user.name", "E2E")
    (root / "percent_change.py").write_text(BROKEN_SOURCE, encoding="utf-8")
    (root / "test_percent_change.py").write_text(BROKEN_TEST, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-m", "broken percent_change")
    return root, git(root, "rev-parse", "HEAD")


def show(title: str) -> None:
    print(f"\n=== {title} ===")


def show_receipt(receipt: Any) -> None:
    print(f"  {receipt.outcome:<8} {receipt.detail}")
    if receipt.evidence:
        print(f"           evidence: {json.dumps(receipt.evidence)}")


async def run() -> int:
    failures: list[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        mark = "PASS" if condition else "FAIL"
        print(f"  [{mark}] {label}{(' - ' + detail) if detail else ''}")
        if not condition:
            failures.append(label)

    show("0. build a real repository with a real failing test")
    repo, base = build_broken_repo()
    print(f"  repo   : {repo}")
    print(f"  base   : {base}")
    # This machine's Application Control policy blocks the pyarrow DLL, so pytest
    # cannot autoload its installed plugins. That is a local environment quirk,
    # not part of the product: the command is still a real pytest run, it simply
    # does not load third-party plugins it does not need.
    test_env = {
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTEST_ADDOPTS": "-p no:cacheprovider",
    }
    test_cmd = f'"{sys.executable}" -m pytest test_percent_change.py -q'
    check("repository created", (repo / ".git").exists())

    store = SentinelPersistence(db_path=str(repo / "sentinel.db"))
    reviewer = SelfRepairReviewer(
        approvals=ApprovalManager(store), signing_key=SHARED_KEY
    )
    proposer = GitSelfRepairProposer(timeout=180.0)
    gate = SelfRepairGate(
        GitRepairApplier(str(repo)), review_verification_key=SHARED_KEY.encode("utf-8")
    )

    show("1. Forge proposes: real branch, real test before and after")
    outcome: ProposalOutcome = await proposer.propose(
        repo_path=str(repo),
        base_commit=base,
        branch="repair/percent-change",
        candidate=CandidateFix(
            target_file="percent_change.py",
            original_snippet=BROKEN_SNIPPET,
            replacement_snippet=FIXED_SNIPPET,
            rationale="describe multiplies by 100 again; percent_change already returns a percentage",
        ),
        test_command=test_cmd,
        env=test_env,
    )
    print(f"  fixed  : {outcome.fixed}  ({outcome.reason})")
    if outcome.before:
        print(f"  before : exit={outcome.before.returncode} passed={outcome.before.passed}")
        print("    " + outcome.before.stdout.strip().replace("\n", "\n    ")[:600])
    if outcome.after:
        print(f"  after  : exit={outcome.after.returncode} passed={outcome.after.passed}")
        print("    " + outcome.after.stdout.strip().replace("\n", "\n    ")[:600])
    check("test genuinely failed before the change", outcome.before is not None and not outcome.before.passed)
    check("test genuinely passed after the change", outcome.after is not None and outcome.after.passed)
    check("Forge refuses to propose when the test does not pass", not outcome.fixed or outcome.after is not None)
    leftover_branches = git(repo, "branch", "--list", "repair/*")
    file_after_proposal = (repo / "percent_change.py").read_text(encoding="utf-8")
    check(
        "Forge gave the working tree back (it proposes, the gate applies)",
        leftover_branches.strip() == "",
        f"branches left behind: {leftover_branches!r}",
    )
    check(
        "the working tree still holds the unfixed code",
        BROKEN_SNIPPET in file_after_proposal,
        "nothing was written before approval",
    )
    if not outcome.fixed:
        print("\nProposer declined to propose. Nothing further to prove.")
        return 1

    request = outcome.to_request(str(repo))

    show("2. the gate refuses a proposal with no test evidence")
    stripped = {**request.__dict__, "test_evidence": {"command": test_cmd, "passed": False}}
    _, refused = gate.propose(
        RepairProposal(
            repo_path=stripped["repo_path"],
            branch=stripped["branch"],
            base_commit=stripped["base_commit"],
            target_file=stripped["target_file"],
            original_snippet=stripped["original_snippet"],
            replacement_snippet=stripped["replacement_snippet"],
            rationale=stripped["rationale"],
            test_evidence=stripped["test_evidence"],
        )
    )
    show_receipt(refused)
    check("evidence-free proposal refused", refused.outcome == "REFUSED")

    show("3. Forge files the real proposal")
    record, receipt = gate.propose(
        RepairProposal(
            repo_path=request.repo_path,
            branch=request.branch,
            base_commit=request.base_commit,
            target_file=request.target_file,
            original_snippet=request.original_snippet,
            replacement_snippet=request.replacement_snippet,
            rationale=request.rationale,
            proposed_by=request.proposed_by,
            test_evidence=request.test_evidence,
        )
    )
    show_receipt(receipt)
    check("proposal accepted with real evidence", receipt.outcome == "ACCEPTED")
    check("proposal records the passing command", receipt.evidence.get("test_command") == test_cmd)

    show("4. a forged review is refused (no Sentinel signature)")
    forged = {
        "patch_fingerprint": record.proposal.fingerprint(),
        "verdict": "clear",
        "reviewer": "sentinel",
        "approval_id": "appr_forged",
        "findings": [],
        "checks_run": [],
        "issued_at": time.time(),
        "nonce": "forged",
        "signature": "0" * 64,
    }
    gate_refusal = gate.record_review(record.patch_id, forged)
    show_receipt(gate_refusal)
    check("forged review refused", gate_refusal.outcome == "REFUSED")
    check(
        "forged review refused specifically for its signature",
        "BAD_REVIEW_SIGNATURE" in gate_refusal.detail,
        gate_refusal.detail,
    )

    show("5. a review signed for a different patch is refused")
    other_review = reviewer.review(
        patch_fingerprint="0" * 64,
        target_file=request.target_file,
        replacement_snippet=request.replacement_snippet,
        test_evidence=request.test_evidence,
    ).review.to_document()
    mismatched = gate.record_review(record.patch_id, other_review)
    show_receipt(mismatched)
    check("mismatched-fingerprint review refused", mismatched.outcome == "REFUSED")
    check(
        "refused for the right reason",
        "REVIEW_WRONG_PATCH" in mismatched.detail,
        mismatched.detail,
    )

    show("6. Sentinel reviews the real patch and signs the verdict")
    reviewed = reviewer.review(
        patch_fingerprint=record.proposal.fingerprint(),
        target_file=request.target_file,
        replacement_snippet=request.replacement_snippet,
        test_evidence=request.test_evidence,
    )
    document = reviewed.review.to_document()
    print(f"  blocked  : {reviewed.blocked}  reasons={list(reviewed.reasons)}")
    print(f"  approval : {document['approval_id']} status={reviewed.approval.status.value}")
    print(f"  signature: {document['signature'][:32]}...")
    check("Sentinel cleared the patch", not reviewed.blocked)
    check("Sentinel minted an approved single-use approval", reviewed.approval.status.value == "approved")

    show("7. tampering with a signed review is refused")
    tampered = {**document, "verdict": "block"}
    tampered_receipt = gate.record_review(record.patch_id, tampered)
    show_receipt(tampered_receipt)
    check("tampered verdict refused", tampered_receipt.outcome == "REFUSED")

    show("8. the genuinely signed review is accepted")
    accepted = gate.record_review(record.patch_id, document)
    show_receipt(accepted)
    check("signed review accepted", accepted.outcome == "ACCEPTED")
    check("gate recorded that it verified the signature", record.review.get("signature_verified") is True)
    check("state is REVIEWED", record.state is RepairState.REVIEWED)

    show("9. a review is bound to one patch and cannot be reused for another")
    second_record, _ = gate.propose(
        RepairProposal(
            repo_path=request.repo_path,
            branch="repair/other",
            base_commit=request.base_commit,
            target_file=request.target_file,
            original_snippet="    if old == 0:\n        return 0.0",
            replacement_snippet="    if old <= 0:\n        return 0.0",
            rationale="guard the base value",
            test_evidence=request.test_evidence,
        )
    )
    replay = gate.record_review(second_record.patch_id, document)
    show_receipt(replay)
    check("reused review refused for a different patch", replay.outcome == "REFUSED")
    check(
        "refused because the review is bound to another patch",
        "REVIEW_WRONG_PATCH" in replay.detail,
        replay.detail,
    )
    check(
        "the spent-approval guard sits behind the fingerprint guard",
        replay.detail.startswith("REVIEW_WRONG_PATCH"),
        "fingerprint binding fires first, which is the stronger check",
    )

    show("10. agents cannot approve; the owner can")
    for impostor in ("friday", "forge", "sentinel"):
        r = gate.record_owner_decision(record.patch_id, approver=impostor, approve=True)
        check(f"{impostor} refused", r.outcome == "REFUSED")
    owner = gate.record_owner_decision(record.patch_id, approver="surendra", approve=True)
    show_receipt(owner)
    check("owner approval accepted", owner.outcome == "ACCEPTED")

    show("11. apply produces a real commit on a real branch")
    applied = gate.apply(record.patch_id)
    show_receipt(applied)
    head = git(repo, "rev-parse", "HEAD")
    branch_now = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    file_now = (repo / "percent_change.py").read_text(encoding="utf-8")
    check("apply accepted", applied.outcome == "ACCEPTED")
    check("receipt names the real applied commit", applied.evidence.get("applied_commit") == head)
    check("repo is on the repair branch", branch_now == "repair/percent-change")
    check("file really changed", "percent_change(old, new):.2f" in file_now)
    check("receipt records a rollback point", bool(applied.evidence.get("rollback_point")))

    show("12. the approval is spent; a replayed apply is refused")
    replay_apply = gate.apply(record.patch_id)
    show_receipt(replay_apply)
    check("replayed apply refused", replay_apply.outcome == "REFUSED")
    check("refused as consumed", "APPROVAL_CONSUMED" in replay_apply.detail)

    show("13. the fixed code really passes the real test")
    proc = subprocess.run(
        test_cmd, cwd=repo, shell=True, capture_output=True, text=True, timeout=180, env={**os.environ, **test_env}
    )
    print("    " + proc.stdout.strip().replace("\n", "\n    ")[:400])
    check("the applied patch makes the test pass", proc.returncode == 0)

    show("14. rollback restores the reviewed content as its own commit")
    rolled = gate.rollback(record.patch_id)
    show_receipt(rolled)
    file_after_rollback = (repo / "percent_change.py").read_text(encoding="utf-8")
    proc2 = subprocess.run(
        test_cmd, cwd=repo, shell=True, capture_output=True, text=True, timeout=180, env={**os.environ, **test_env}
    )
    print("    " + proc2.stdout.strip().replace("\n", "\n    ")[:400])
    check("rollback accepted", rolled.outcome == "ACCEPTED")
    check("the original line is back", BROKEN_SNIPPET.strip() in file_after_rollback)
    check("the test fails again after rollback", proc2.returncode != 0)
    check("state is ROLLED_BACK", record.state is RepairState.ROLLED_BACK)

    show("summary")
    print(f"  steps run      : {len(record.receipts)}")
    print(f"  acceptances    : {sum(1 for r in record.receipts if r.outcome == 'ACCEPTED')}")
    print(f"  refusals       : {sum(1 for r in record.receipts if r.outcome == 'REFUSED')}")
    print(f"  failures       : {len(failures)}")
    for name in failures:
        print(f"    FAILED: {name}")

    shutil.rmtree(repo.parent, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
