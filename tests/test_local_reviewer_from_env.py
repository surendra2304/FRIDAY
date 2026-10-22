"""The environment-built reviewer, driven all the way through the real gate.

`build_local_reviewer_from_env()` existed and had never been executed by
anything — not by the reflex loop (which built its reviewer from an explicit
key) and not by a test. An unexecuted factory is an assumption, and the audit
found it. These tests execute it and then hand its signed verdict to the gate,
which is the only thing that makes it real.
"""

from __future__ import annotations

from typing import Any

import pytest

from friday.autonomous.self_repair import (
    RepairProposal,
    SelfRepairGate,
    _REVIEW_SIGNING_ENV,
)
from friday.cognition.reviewer import LocalReviewer, build_local_reviewer_from_env

REVIEW_KEY = "local-reviewer-integration-key"
#: The shape the gate's evidence check demands: a named command, and a pass.
PASSING_TESTS = {
    "command": "pytest -q tests/test_demo.py",
    "passed": True,
    "summary": "1 passed",
}

#: A patch that is genuinely correct: the broken function returns the running
#: total instead of the sum, and the replacement returns the sum.
CURRENT_SOURCE = """\
def add_all(values):
    \"\"\"Return the sum of values.\"\"\"
    total = 0
    for value in values:
        total += value
    return total
"""
ORIGINAL_SNIPPET = "    return total\n"
REPLACEMENT_SNIPPET = "    return sum(values)\n"


@pytest.fixture()
def gate(tmp_path: Any) -> tuple[SelfRepairGate, Any]:
    """A real gate and a real repository containing the file being patched.

    No applier is attached: `propose` and `record_review` do not touch git, and
    the tests below stop before `apply`. The repository path still has to exist
    with real content, because the reviewer reads the file it is judging.
    """
    repo = tmp_path / "repo"
    (repo / "src" / "friday").mkdir(parents=True)
    (repo / "src" / "friday" / "demo.py").write_text(CURRENT_SOURCE, encoding="utf-8")
    return SelfRepairGate(review_verification_key=REVIEW_KEY.encode("utf-8")), repo


def test_the_factory_returns_none_when_no_key_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _REVIEW_SIGNING_ENV:
        monkeypatch.delenv(name, raising=False)

    assert build_local_reviewer_from_env() is None


@pytest.mark.parametrize("name", _REVIEW_SIGNING_ENV)
def test_the_factory_builds_from_any_of_the_documented_key_names(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    for other in _REVIEW_SIGNING_ENV:
        monkeypatch.delenv(other, raising=False)
    monkeypatch.setenv(name, REVIEW_KEY)

    reviewer = build_local_reviewer_from_env()

    assert isinstance(reviewer, LocalReviewer)


def test_a_review_built_from_the_environment_clears_a_real_patch(
    monkeypatch: pytest.MonkeyPatch, gate: tuple[SelfRepairGate, Any]
) -> None:
    monkeypatch.setenv(_REVIEW_SIGNING_ENV[0], REVIEW_KEY)
    reviewer = build_local_reviewer_from_env()
    assert reviewer is not None

    gate, repo = gate
    proposal = _propose(gate, repo)
    fingerprint = gate.get(proposal).proposal.fingerprint()  # type: ignore[union-attr]

    outcome = reviewer.review(
        patch_fingerprint=fingerprint,
        target_file="src/friday/demo.py",
        replacement_snippet=REPLACEMENT_SNIPPET,
        original_snippet=ORIGINAL_SNIPPET,
        current_source=CURRENT_SOURCE,
        test_evidence=PASSING_TESTS,
        approval_id="approval_probe",
    )

    assert outcome.cleared is True, outcome.reasons
    assert outcome.checks_run, "a review that ran no checks must not clear anything"
    assert outcome.document.get("signature"), "the review must be signed"

    receipt = gate.record_review(proposal, outcome.document)

    assert receipt.outcome == "ACCEPTED"
    assert gate.get(proposal).state.value == "REVIEWED"  # type: ignore[union-attr]


def test_a_review_that_rejects_a_breaking_patch_is_still_well_formed(
    monkeypatch: pytest.MonkeyPatch, gate: tuple[SelfRepairGate, Any]
) -> None:
    monkeypatch.setenv(_REVIEW_SIGNING_ENV[0], REVIEW_KEY)
    reviewer = build_local_reviewer_from_env()
    assert reviewer is not None
    gate, repo = gate
    proposal = _propose(gate, repo)
    fingerprint = gate.get(proposal).proposal.fingerprint()  # type: ignore[union-attr]

    outcome = reviewer.review(
        patch_fingerprint=fingerprint,
        target_file="src/friday/demo.py",
        replacement_snippet="    return sum(values  # unterminated\n",
        original_snippet=ORIGINAL_SNIPPET,
        current_source=CURRENT_SOURCE,
        test_evidence=PASSING_TESTS,
    )

    assert outcome.cleared is False
    assert outcome.reasons
    assert outcome.document.get("verdict") == "reject"

    # A refusal is a first-class result here, not an exception: the gate reports
    # *which* refusal by name so a caller can act on it.
    receipt = gate.record_review(proposal, outcome.document)

    assert receipt.outcome == "REFUSED"
    assert "REVIEW_REJECTED" in receipt.detail
    assert gate.get(proposal).state.value == "BLOCKED"  # type: ignore[union-attr]

    # ...and the file that broke the patch could never have been applied.
    proposal_file = repo / "src" / "friday" / "demo.py"
    assert proposal_file.read_text(encoding="utf-8") == CURRENT_SOURCE


def test_the_gate_refuses_a_review_signed_with_a_different_key(
    monkeypatch: pytest.MonkeyPatch, gate: tuple[SelfRepairGate, Any]
) -> None:
    """The factory and the gate must share a key or the pipeline refuses."""
    monkeypatch.setenv(_REVIEW_SIGNING_ENV[0], "a-different-key")
    reviewer = build_local_reviewer_from_env()
    assert reviewer is not None
    gate, repo = gate
    proposal = _propose(gate, repo)

    outcome = reviewer.review(
        patch_fingerprint=gate.get(proposal).proposal.fingerprint(),  # type: ignore[union-attr]
        target_file="src/friday/demo.py",
        replacement_snippet=REPLACEMENT_SNIPPET,
        original_snippet=ORIGINAL_SNIPPET,
        current_source=CURRENT_SOURCE,
        test_evidence=PASSING_TESTS,
    )

    assert outcome.cleared is True  # locally it looks fine...

    # ...but the gate verifies with its own key, and this document was signed with
    # another one. The refusal is by name, and nothing was applied.
    receipt = gate.record_review(proposal, outcome.document)

    assert receipt.outcome == "REFUSED"
    assert "BAD_REVIEW_SIGNATURE" in receipt.detail
    # Still PROPOSED, not BLOCKED: a mis-signed document is a transport problem,
    # and the patch is not burnt by it. A rejected *verdict* is terminal.
    assert gate.get(proposal).state.value == "PROPOSED"  # type: ignore[union-attr]


def _propose(gate: SelfRepairGate, repo: Any) -> str:
    record, receipt = gate.propose(
        RepairProposal(
            repo_path=str(repo),
            branch="friday/local-reviewer-probe",
            base_commit="deadbeefdeadbeef",
            target_file="src/friday/demo.py",
            original_snippet=ORIGINAL_SNIPPET,
            replacement_snippet=REPLACEMENT_SNIPPET,
            rationale="build_local_reviewer_from_env must actually clear a patch",
            proposed_by="friday",
            test_evidence=PASSING_TESTS,
        )
    )
    assert receipt.outcome == "ACCEPTED", receipt.detail
    return record.patch_id
