"""Gated self-repair pipeline for the FRIDAY Universe.

Phase E1. Forge proposes a repair, Sentinel reviews it, the owner approves it, and
only then does anything touch a working tree. Every step leaves a receipt, and
every receipt says what it actually proves.

The design assumption is adversarial: the pipeline must be safe when a proposal is
wrong, a review is sloppy, an approval is stale, or a caller replays a request.
So the rules are all *fail-closed*:

1. A proposal without test evidence is refused. "It probably works" is not evidence.
2. Only Sentinel may file a review. The proposer cannot review its own patch.
3. An approval binds to the *fingerprint of the exact patch*. Edit one byte of the
   patch after approval and the approval no longer applies, because the
   fingerprint no longer matches.
4. Approvals are single-use and expire. A replayed apply is refused.
5. Applying requires a recorded checkpoint, so rollback is always possible.
6. A patch may only be applied to content that still matches what was reviewed.
   If the file drifted underneath, the apply is refused rather than guessed.

Every rejection is a first-class result, not an exception. A pipeline that can only
report success cannot be audited.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

#: Only this actor may file a review. The proposer never reviews itself.
REVIEWER = "sentinel"

#: Agents in the universe. None of them may authorize a repair — least of all
#: FRIDAY, which is the component that would carry the repair out. Approval is a
#: human act, so this is a deny-list by role rather than an allow-list by name: a
#: new agent added tomorrow is excluded by default rather than admitted by omission.
NON_OWNER_ACTORS = frozenset(
    {
        "",
        "friday",
        "forge",
        "sentinel",
        "inference",
        "memora",
        "stratex",
        "intelx",
        "futuris",
        "cortex",
        "system",
        "bot",
        "agent",
        "automation",
        "self",
    }
)

#: Approval TTL. Long enough to be usable, short enough that a forgotten approval
#: cannot authorize a repair hours later against a repo that has since moved.
APPROVAL_TTL_SECONDS = 900.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.isoformat()


class RepairState(str, Enum):
    """Lifecycle of a single repair proposal."""

    PROPOSED = "PROPOSED"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
    ROLLED_BACK = "ROLLED_BACK"
    BLOCKED = "BLOCKED"


class GateRefusal(str, Enum):
    """Why a step was refused. Callers switch on these, so they are stable."""

    NO_TEST_EVIDENCE = "NO_TEST_EVIDENCE"
    EMPTY_PATCH = "EMPTY_PATCH"
    NOT_PROPOSED = "NOT_PROPOSED"
    NOT_REVIEWED = "NOT_REVIEWED"
    REVIEW_REJECTED = "REVIEW_REJECTED"
    WRONG_REVIEWER = "WRONG_REVIEWER"
    NOT_APPROVED = "NOT_APPROVED"
    WRONG_APPROVER = "WRONG_APPROVER"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    APPROVAL_CONSUMED = "APPROVAL_CONSUMED"
    FINGERPRINT_MISMATCH = "FINGERPRINT_MISMATCH"
    CONTENT_DRIFTED = "CONTENT_DRIFTED"
    NO_CHECKPOINT = "NO_CHECKPOINT"
    NOTHING_TO_ROLL_BACK = "NOTHING_TO_ROLL_BACK"
    GIT_FAILED = "GIT_FAILED"


#: Refusals that end the pipeline. Everything else refuses *this attempt* and leaves
#: the record where it was, so a legitimate actor can still act and, above all, so
#: that a half-applied patch stays rollbackable.
TERMINAL_REFUSALS = frozenset(
    {
        GateRefusal.NO_TEST_EVIDENCE,
        GateRefusal.EMPTY_PATCH,
        GateRefusal.REVIEW_REJECTED,
    }
)


@dataclass(frozen=True)
class Receipt:
    """One immutable record of one attempted transition."""

    step: str
    outcome: Literal["ACCEPTED", "REFUSED"]
    at: str
    detail: str = ""
    #: What this receipt proves. Never widen this to claim more than it did.
    evidence_class: str = "pipeline_transition"
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "outcome": self.outcome,
            "at": self.at,
            "detail": self.detail,
            "evidence_class": self.evidence_class,
            "evidence": self.evidence,
        }


@dataclass
class TestEvidence:
    """Evidence that a proposed repair was actually exercised.

    Deliberately unforgiving: a named command, and a pass. Without both, the gate
    refuses the proposal outright.
    """

    command: str
    passed: bool
    summary: str = ""
    ran_at: str = ""

    @classmethod
    def from_evidence(cls, raw: Any) -> "TestEvidence | None":
        """Normalise caller-supplied evidence, or return None if it is not evidence.

        Accepts either a raw mapping (how it arrives over the wire) or an existing
        instance. Anything without a named command and a true pass is not evidence.
        """
        if isinstance(raw, TestEvidence):
            return raw if raw.command.strip() and raw.passed else None
        if not isinstance(raw, dict):
            return None
        command = str(raw.get("command", "")).strip()
        if not command or raw.get("passed") is not True:
            return None
        return cls(
            command=command,
            passed=True,
            summary=str(raw.get("summary", "")),
            ran_at=str(raw.get("ran_at", "")),
        )


@dataclass
class RepairProposal:
    """A repair Forge wants applied. Nothing has touched a working tree yet."""

    repo_path: str
    branch: str
    base_commit: str
    target_file: str
    original_snippet: str
    replacement_snippet: str
    rationale: str
    proposed_by: str = "forge"
    proposal_id: str = ""
    proposed_at: str = ""
    #: Raw evidence as submitted by Forge. Normalised by the gate, not trusted.
    test_evidence: Any = None

    def fingerprint(self) -> str:
        """Hash of everything that determines what the patch actually does.

        Deliberately covers the file, the before-text and the after-text, but not
        the rationale: rewording the justification must not invalidate an owner's
        approval, while changing a single byte of code must.
        """
        payload = json.dumps(
            {
                "target_file": self.target_file,
                "original_snippet": self.original_snippet,
                "replacement_snippet": self.replacement_snippet,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class OwnerApproval:
    """A single-use, expiring, fingerprint-bound owner authorization."""

    patch_fingerprint: str
    approver: str
    approval_id: str = ""
    approved_at: datetime = field(default_factory=_now)
    expires_at: datetime = field(default_factory=lambda: _now() + timedelta(seconds=APPROVAL_TTL_SECONDS))
    consumed: bool = False

    def is_expired(self, moment: datetime | None = None) -> bool:
        return (moment or _now()) >= self.expires_at


@dataclass
class RepairRecord:
    """Everything known about one repair, and every receipt ever produced for it."""

    proposal: RepairProposal
    state: RepairState = RepairState.PROPOSED
    review: dict[str, Any] | None = None
    approval: OwnerApproval | None = None
    #: Normalised evidence, set only when the proposal survived the evidence check.
    tests: TestEvidence | None = None
    applied_commit: str | None = None
    checkpoint_commit: str | None = None
    branch_created: str | None = None
    receipts: list[Receipt] = field(default_factory=list)

    @property
    def patch_id(self) -> str:
        return self.proposal.proposal_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "state": self.state.value,
            "branch": self.proposal.branch,
            "target_file": self.proposal.target_file,
            "fingerprint": self.proposal.fingerprint(),
            "proposed_by": self.proposal.proposed_by,
            "rationale": self.proposal.rationale,
            "tests": (
                {
                    "command": self.tests.command,
                    "summary": self.tests.summary,
                    "ran_at": self.tests.ran_at,
                }
                if self.tests
                else None
            ),
            "review": self.review,
            "approval": (
                {
                    "approval_id": self.approval.approval_id,
                    "approver": self.approval.approver,
                    "approved_at": _stamp(self.approval.approved_at),
                    "expires_at": _stamp(self.approval.expires_at),
                    "consumed": self.approval.consumed,
                }
                if self.approval
                else None
            ),
            "applied_commit": self.applied_commit,
            "checkpoint_commit": self.checkpoint_commit,
            "receipts": [r.as_dict() for r in self.receipts],
        }


class GitRepairApplier:
    """Applies and rolls back one repair against a real git working tree.

    Uses the real ``git`` binary. Every invocation is captured, and a non-zero exit
    is an error rather than a silently swallowed exception.
    """

    def __init__(self, repo_path: str, timeout: float = 30.0) -> None:
        self.repo_path = str(Path(repo_path).resolve())
        self.timeout = timeout
        if not (Path(self.repo_path) / ".git").exists():
            raise ValueError(f"not a git repository: {self.repo_path}")

    def _git(self, *args: str) -> tuple[int, str, str]:
        proc = subprocess.run(
            ["git", *args],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

    def current_commit(self) -> str | None:
        code, out, _ = self._git("rev-parse", "HEAD")
        return out if code == 0 else None

    def read_file(self, relative_path: str) -> str | None:
        code, out, _ = self._git("show", f"HEAD:{relative_path}")
        if code != 0:
            return None
        return out

    def create_branch(self, base_commit: str, branch: str) -> str:
        """Branch from a known commit, so the repair is reproducible from a pin."""
        code, out, err = self._git("checkout", "-b", branch, base_commit)
        if code != 0:
            raise RuntimeError(f"git checkout -b failed: {err or out}")
        code, out, _ = self._git("rev-parse", "HEAD")
        if code != 0:
            raise RuntimeError("branch created but HEAD is unreadable")
        return out

    def apply_snippet(self, relative_path: str, original: str, replacement: str) -> None:
        """Write the replacement, but only if the file still holds the original.

        This is the drift guard: a patch reviewed against one revision of a file
        must not silently land on a different revision.
        """
        path = Path(self.repo_path) / relative_path
        if not path.is_file():
            raise FileNotFoundError(relative_path)
        current = path.read_text(encoding="utf-8")
        if original not in current:
            raise LookupError(
                f"reviewed content is no longer present in {relative_path}; refusing to apply"
            )
        if current.count(original) != 1:
            raise LookupError(
                f"reviewed content appears {current.count(original)} times in "
                f"{relative_path}; refusing to guess which occurrence was meant"
            )
        path.write_text(current.replace(original, replacement, 1), encoding="utf-8")

    def commit_all(self, message: str) -> str:
        code, out, err = self._git("add", "-A")
        if code != 0:
            raise RuntimeError(f"git add failed: {err or out}")
        code, out, err = self._git("commit", "-m", message)
        if code != 0:
            raise RuntimeError(f"git commit failed: {err or out}")
        code, out, _ = self._git("rev-parse", "HEAD")
        if code != 0:
            raise RuntimeError("commit created but HEAD is unreadable")
        return out

    def revert_head(self) -> str:
        """Undo the applied commit, leaving the reversal itself as an auditable commit."""
        code, out, err = self._git("revert", "--no-edit", "HEAD")
        if code != 0:
            raise RuntimeError(f"git revert failed: {err or out}")
        code, out, _ = self._git("rev-parse", "HEAD")
        if code != 0:
            raise RuntimeError("revert created but HEAD is unreadable")
        return out


class SelfRepairGate:
    """Holds every repair and refuses every unsafe transition.

    One instance per pipeline. Holds no global state, so a test can build one
    without inheriting another test's approvals.
    """

    def __init__(self, applier: GitRepairApplier | None = None) -> None:
        self._applier = applier
        self._records: dict[str, RepairRecord] = {}
        self._seq = 0

    # ── helpers ────────────────────────────────────────────────────────────
    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}_{self._seq:04d}"

    def _record(self, record: RepairRecord, step: str, outcome: str, **kw: Any) -> Receipt:
        receipt = Receipt(step=step, outcome=outcome, at=_stamp(_now()), **kw)
        record.receipts.append(receipt)
        return receipt

    def get(self, patch_id: str) -> RepairRecord | None:
        return self._records.get(patch_id)

    def all_records(self) -> list[RepairRecord]:
        return list(self._records.values())

    def _refuse(
        self, record: RepairRecord, step: str, reason: GateRefusal, detail: str
    ) -> Receipt:
        """Record a refusal.

        Not every refusal ends the pipeline. Only a *terminal* one marks the record
        BLOCKED. A wrong actor, a stale approval or a failed apply is a property of
        that attempt, not of the proposal — and critically, a failed apply must not
        strand a half-applied patch by making rollback unreachable.
        """
        receipt = self._record(record, step, "REFUSED", detail=f"{reason.value}: {detail}")
        if reason in TERMINAL_REFUSALS:
            record.state = RepairState.BLOCKED
        return receipt

    # ── step 1: propose ────────────────────────────────────────────────────
    def propose(self, proposal: RepairProposal) -> tuple[RepairRecord, Receipt]:
        """Accept a proposal onto the books. Touches no files.

        Refused when the patch is empty, or when it arrives without evidence that
        it was actually run against a test.
        """
        proposal.proposal_id = proposal.proposal_id or self._next_id("patch")
        proposal.proposed_at = proposal.proposed_at or _stamp(_now())

        record = RepairRecord(proposal=proposal)
        self._records[proposal.proposal_id] = record

        if proposal.original_snippet == proposal.replacement_snippet:
            return record, self._refuse(
                record,
                "propose",
                GateRefusal.EMPTY_PATCH,
                "replacement is identical to the original",
            )

        record.tests = TestEvidence.from_evidence(proposal.test_evidence)
        if record.tests is None:
            return record, self._refuse(
                record,
                "propose",
                GateRefusal.NO_TEST_EVIDENCE,
                "proposal arrived without a named test command that passed",
            )

        receipt = self._record(
            record,
            "propose",
            "ACCEPTED",
            detail=f"proposal filed on branch {proposal.branch}",
            evidence={
                "proposed_by": proposal.proposed_by,
                "base_commit": proposal.base_commit,
                "test_command": record.tests.command,
                "files_touched": 0,
            },
        )
        return record, receipt

    # ── step 2: review ─────────────────────────────────────────────────────
    def record_review(
        self,
        patch_id: str,
        reviewer: str,
        verdict: str,
        findings: str = "",
    ) -> Receipt:
        """File Sentinel's review. Required before any approval can exist."""
        record = self._records.get(patch_id)
        if record is None:
            return Receipt(
                step="review",
                outcome="REFUSED",
                at=_stamp(_now()),
                detail=f"{GateRefusal.NOT_PROPOSED.value}: unknown patch {patch_id}",
            )
        if record.state is not RepairState.PROPOSED:
            return self._refuse(
                record, "review", GateRefusal.NOT_PROPOSED, f"state is {record.state.value}"
            )
        if (reviewer or "").lower() != REVIEWER:
            return self._refuse(
                record, "review", GateRefusal.WRONG_REVIEWER, f"reviewer was {reviewer!r}"
            )

        record.review = {
            "reviewer": reviewer,
            "verdict": verdict,
            "findings": findings,
            "reviewed_at": _stamp(_now()),
        }
        if (verdict or "").lower() != "clear":
            return self._refuse(
                record, "review", GateRefusal.REVIEW_REJECTED, f"verdict was {verdict!r}"
            )

        record.state = RepairState.REVIEWED
        return self._record(
            record,
            "review",
            "ACCEPTED",
            detail="sentinel review cleared; awaiting owner decision",
            evidence={"reviewer": reviewer, "verdict": verdict, "findings": findings},
        )

    # ── step 3: owner approval ─────────────────────────────────────────────
    def record_owner_decision(
        self, patch_id: str, approver: str, approve: bool
    ) -> Receipt:
        """Record the owner's decision. Only meaningful after a clear review."""
        record = self._records.get(patch_id)
        if record is None:
            return Receipt(
                step="owner_decision",
                outcome="REFUSED",
                at=_stamp(_now()),
                detail=f"{GateRefusal.NOT_PROPOSED.value}: unknown patch {patch_id}",
            )
        if record.state is not RepairState.REVIEWED:
            return self._refuse(
                record,
                "owner_decision",
                GateRefusal.NOT_REVIEWED,
                f"state is {record.state.value}; an unreviewed patch cannot be approved",
            )
        if (approver or "").strip().lower() in NON_OWNER_ACTORS:
            return self._refuse(
                record,
                "owner_decision",
                GateRefusal.WRONG_APPROVER,
                f"{approver!r} is an agent, not the owner; no agent may approve a repair",
            )

        if not approve:
            record.state = RepairState.REJECTED
            return self._record(
                record,
                "owner_decision",
                "ACCEPTED",
                detail="owner rejected; pipeline halts here by design",
                evidence={"approver": approver, "approved": False},
            )

        record.approval = OwnerApproval(
            patch_fingerprint=record.proposal.fingerprint(),
            approver=approver,
            approval_id=self._next_id("appr"),
        )
        record.state = RepairState.APPROVED
        return self._record(
            record,
            "owner_decision",
            "ACCEPTED",
            detail="owner approved; approval is single-use and expiring",
            evidence={
                "approver": approver,
                "approval_id": record.approval.approval_id,
                "bound_fingerprint": record.approval.patch_fingerprint,
                "expires_at": _stamp(record.approval.expires_at),
            },
        )

    # ── step 4: apply ──────────────────────────────────────────────────────
    def apply(self, patch_id: str) -> Receipt:
        """Apply to a real working tree. Refused unless a valid approval stands.

        Order matters: state, then approver, then expiry, then single-use, then
        fingerprint, then a real checkpoint, and only then the filesystem.
        """
        record = self._records.get(patch_id)
        if record is None:
            return Receipt(
                step="apply",
                outcome="REFUSED",
                at=_stamp(_now()),
                detail=f"{GateRefusal.NOT_PROPOSED.value}: unknown patch {patch_id}",
            )
        # Approval guards run before the state guard so a replayed apply is reported
        # as the replay it is, not lumped in with "never approved".
        if record.approval is None:
            return self._refuse(
                record,
                "apply",
                GateRefusal.NOT_APPROVED,
                f"state is {record.state.value}; nothing may be applied without owner approval",
            )
        if record.approval.is_expired():
            return self._refuse(
                record,
                "apply",
                GateRefusal.APPROVAL_EXPIRED,
                f"expired at {_stamp(record.approval.expires_at)}",
            )
        if record.approval.consumed:
            return self._refuse(
                record, "apply", GateRefusal.APPROVAL_CONSUMED, "approval was already used"
            )
        if record.approval.patch_fingerprint != record.proposal.fingerprint():
            return self._refuse(
                record,
                "apply",
                GateRefusal.FINGERPRINT_MISMATCH,
                "patch changed after approval; the approval no longer covers it",
            )
        if record.state is not RepairState.APPROVED:
            return self._refuse(
                record,
                "apply",
                GateRefusal.NOT_APPROVED,
                f"state is {record.state.value}; an approval alone does not authorise a second apply",
            )
        if self._applier is None:
            return self._refuse(
                record, "apply", GateRefusal.NO_CHECKPOINT, "no applier configured"
            )

        proposal = record.proposal
        try:
            checkpoint = self._applier.current_commit()
            if checkpoint is None:
                return self._refuse(
                    record, "apply", GateRefusal.NO_CHECKPOINT, "repository has no readable HEAD"
                )
            record.checkpoint_commit = checkpoint
            branch_commit = self._applier.create_branch(proposal.base_commit, proposal.branch)
            record.branch_created = proposal.branch
            self._applier.apply_snippet(
                proposal.target_file, proposal.original_snippet, proposal.replacement_snippet
            )
            record.applied_commit = self._applier.commit_all(
                f"repair({record.patch_id}): {proposal.rationale.splitlines()[0][:120]}"
            )
        except (RuntimeError, FileNotFoundError, LookupError, subprocess.SubprocessError) as exc:
            return self._refuse(record, "apply", GateRefusal.GIT_FAILED, str(exc))

        # Burn the approval only once the work is actually done, so a failed apply
        # can be retried deliberately instead of being silently unrecoverable.
        record.approval.consumed = True
        record.state = RepairState.APPLIED
        return self._record(
            record,
            "apply",
            "ACCEPTED",
            detail=f"applied on branch {proposal.branch}",
            evidence={
                "branch": proposal.branch,
                "branch_point": branch_commit,
                "applied_commit": record.applied_commit,
                "rollback_point": record.checkpoint_commit,
                "files_touched": 1,
            },
        )

    # ── step 5: rollback ───────────────────────────────────────────────────
    def rollback(self, patch_id: str) -> Receipt:
        """Undo an applied repair as a real commit, so the reversal is auditable."""
        record = self._records.get(patch_id)
        if record is None:
            return Receipt(
                step="rollback",
                outcome="REFUSED",
                at=_stamp(_now()),
                detail=f"{GateRefusal.NOT_PROPOSED.value}: unknown patch {patch_id}",
            )
        if record.state is not RepairState.APPLIED or not record.applied_commit:
            return self._refuse(
                record, "rollback", GateRefusal.NOTHING_TO_ROLL_BACK, f"state is {record.state.value}"
            )
        if self._applier is None:
            return self._refuse(
                record, "rollback", GateRefusal.NO_CHECKPOINT, "no applier configured"
            )

        try:
            revert_commit = self._applier.revert_head()
        except (RuntimeError, subprocess.SubprocessError) as exc:
            return self._refuse(record, "rollback", GateRefusal.GIT_FAILED, str(exc))

        record.state = RepairState.ROLLED_BACK
        return self._record(
            record,
            "rollback",
            "ACCEPTED",
            detail="repair reverted; the reversal is itself a commit",
            evidence={
                "reverted_commit": record.applied_commit,
                "revert_commit": revert_commit,
                "branch": record.proposal.branch,
            },
        )
