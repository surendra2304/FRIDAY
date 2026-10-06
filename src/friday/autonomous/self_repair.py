"""Gated self-repair pipeline for the FRIDAY Universe.

Phase E1. Forge proposes a repair, Sentinel reviews it, the owner approves it, and
only then does anything touch a working tree. Every step leaves a receipt, and
every receipt says what it actually proves.

The design assumption is adversarial: the pipeline must be safe when a proposal is
wrong, a review is sloppy, an approval is stale, or a caller replays a request.
So the rules are all *fail-closed*:

1. A proposal without test evidence is refused. "It probably works" is not evidence.
2. A review must be a **signed document**, not a claimed identity. The gate
   verifies an HMAC over the reviewer's own verdict, and refuses a review it
   cannot verify, cannot bind to this patch, or cannot match to an unspent
   single-use approval. The proposer cannot review its own patch, and neither can
   anyone who merely claims to be the reviewer.
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
import hmac
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from friday.core.logging import get_logger

logger = get_logger("autonomous.self_repair")

#: Only this actor may file a review. The proposer never reviews itself.
REVIEWER = "sentinel"

#: Agents in the universe. None of them may authorize a repair — least of all
#: FRIDAY, which is the component that would carry the repair out. This set is the
#: *second* refusal: `friday.cognition.identity.is_owner_identity` decides whether
#: the approver is the owner at all, positively. The name list alone could only
#: refuse names somebody had remembered to add, which is not a security property.
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

#: How old a signed review may be and still be honoured. A review of code that has
#: since changed is not a review of this code, and the fingerprint check would
#: usually catch that — this catches the case where nothing changed but the
#: reviewer stopped standing behind the verdict.
REVIEW_MAX_AGE_SECONDS = 900.0

#: Signing scheme shared with Sentinel's audit logger:
#:     hash      = sha256(canonical_json(document minus "signature"))
#:     signature = hmac_sha256(key, hash)
#: Reimplemented here on purpose. The gate must be able to verify a review
#: without executing the code that produced it.
_REVIEW_SIGNING_ENV = ("FRIDAY_SELF_REPAIR_REVIEW_KEY", "SENTINEL_AUDIT_HMAC_KEY", "SENTINEL_AUDIT_SIGNING_KEY")

#: Where the gate's ledger is written, so a restart does not lose the pipeline.
#:
#: Opt-in. With this unset the gate keeps its records in memory exactly as it
#: always has, which is the safe default for a build that has not yet chosen a
#: durable location. Set it to a path and every recorded transition is written
#: there and reloaded on the next start.
#:
#: The bound is the filesystem, and that is stated rather than implied: this
#: survives a process crash, a restart and a free-tier spin-down, but not a
#: redeploy onto a fresh container. Surviving a redeploy needs a fleet store,
#: which is separate work and is not claimed here.
STATE_ENV = "FRIDAY_SELF_REPAIR_STATE"

#: Bumped when the on-disk shape changes. A ledger written by another version is
#: not loaded: guessing at a missing field would restore a repair record that was
#: never fully written.
STATE_VERSION = 1


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def verify_review_document(document: dict[str, Any], key: bytes) -> bool:
    """Verify a review's HMAC in constant time.

    Any field other than the signature participates in the hash, so flipping a
    verdict or a fingerprint after signing invalidates the signature.
    """
    signature = str(document.get("signature", ""))
    if not signature:
        return False
    body = {k: v for k, v in document.items() if k != "signature"}
    digest = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
    expected = hmac.new(key, digest.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.isoformat()


def _iso_from_epoch(epoch: float) -> str:
    """Render a mandate expiry (a POSIX timestamp) the same way as every other stamp."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


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
    MALFORMED_REVIEW = "MALFORMED_REVIEW"
    BAD_REVIEW_SIGNATURE = "BAD_REVIEW_SIGNATURE"
    REVIEW_WRONG_PATCH = "REVIEW_WRONG_PATCH"
    REVIEW_APPROVAL_REPLAYED = "REVIEW_APPROVAL_REPLAYED"
    REVIEW_EXPIRED = "REVIEW_EXPIRED"
    NO_REVIEW_KEY = "NO_REVIEW_KEY"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    APPROVAL_CONSUMED = "APPROVAL_CONSUMED"
    FINGERPRINT_MISMATCH = "FINGERPRINT_MISMATCH"
    CONTENT_DRIFTED = "CONTENT_DRIFTED"
    NO_CHECKPOINT = "NO_CHECKPOINT"
    NOTHING_TO_ROLL_BACK = "NOTHING_TO_ROLL_BACK"
    GIT_FAILED = "GIT_FAILED"
    # Standing-mandate refusals. An agent still cannot approve a repair; these
    # record whether the *owner's* pre-signed delegation covers it.
    MALFORMED_MANDATE = "MALFORMED_MANDATE"
    BAD_MANDATE_SIGNATURE = "BAD_MANDATE_SIGNATURE"
    MANDATE_EXPIRED = "MANDATE_EXPIRED"
    MANDATE_SCOPE = "MANDATE_SCOPE"
    MANDATE_PATH = "MANDATE_PATH"


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


def _record_to_dict(record: RepairRecord) -> dict[str, Any]:
    """Everything about a repair, losslessly, so a restart can restore it.

    Deliberately *not* ``RepairRecord.as_dict``. That is the endpoint's summary
    shape and it omits fields the ledger must keep: the approval's bound
    fingerprint, the branch that was created, and the submitted evidence. Sharing
    one shape between the API and the ledger is how one of them quietly stops
    carrying a field, and here the field that would be lost is the one that binds
    an approval to a patch.
    """
    proposal = record.proposal
    approval = record.approval
    evidence = proposal.test_evidence
    if isinstance(evidence, TestEvidence):
        evidence = {
            "command": evidence.command,
            "passed": evidence.passed,
            "summary": evidence.summary,
            "ran_at": evidence.ran_at,
        }
    return {
        "proposal": {
            "repo_path": proposal.repo_path,
            "branch": proposal.branch,
            "base_commit": proposal.base_commit,
            "target_file": proposal.target_file,
            "original_snippet": proposal.original_snippet,
            "replacement_snippet": proposal.replacement_snippet,
            "rationale": proposal.rationale,
            "proposed_by": proposal.proposed_by,
            "proposal_id": proposal.proposal_id,
            "proposed_at": proposal.proposed_at,
            "test_evidence": evidence,
        },
        "state": record.state.value,
        "review": record.review,
        "approval": None if approval is None else {
            "patch_fingerprint": approval.patch_fingerprint,
            "approver": approval.approver,
            "approval_id": approval.approval_id,
            "approved_at": approval.approved_at.isoformat(),
            "expires_at": approval.expires_at.isoformat(),
            "consumed": approval.consumed,
        },
        "tests": None if record.tests is None else {
            "command": record.tests.command,
            "passed": record.tests.passed,
            "summary": record.tests.summary,
            "ran_at": record.tests.ran_at,
        },
        "applied_commit": record.applied_commit,
        "checkpoint_commit": record.checkpoint_commit,
        "branch_created": record.branch_created,
        "receipts": [r.as_dict() for r in record.receipts],
    }


def _record_from_dict(raw: dict[str, Any]) -> RepairRecord:
    """Rebuild a record from the ledger. Raises rather than half-restoring."""
    p = raw["proposal"]
    proposal = RepairProposal(
        repo_path=str(p["repo_path"]),
        branch=str(p["branch"]),
        base_commit=str(p["base_commit"]),
        target_file=str(p["target_file"]),
        original_snippet=str(p["original_snippet"]),
        replacement_snippet=str(p["replacement_snippet"]),
        rationale=str(p["rationale"]),
        proposed_by=str(p.get("proposed_by", "forge")),
        proposal_id=str(p.get("proposal_id", "")),
        proposed_at=str(p.get("proposed_at", "")),
        test_evidence=p.get("test_evidence"),
    )
    approval_raw = raw.get("approval")
    approval = None
    if approval_raw:
        approval = OwnerApproval(
            patch_fingerprint=str(approval_raw["patch_fingerprint"]),
            approver=str(approval_raw["approver"]),
            approval_id=str(approval_raw.get("approval_id", "")),
            approved_at=datetime.fromisoformat(str(approval_raw["approved_at"])),
            expires_at=datetime.fromisoformat(str(approval_raw["expires_at"])),
            consumed=bool(approval_raw.get("consumed", False)),
        )
    tests_raw = raw.get("tests")
    tests = None
    if tests_raw:
        tests = TestEvidence(
            command=str(tests_raw["command"]),
            passed=bool(tests_raw["passed"]),
            summary=str(tests_raw.get("summary", "")),
            ran_at=str(tests_raw.get("ran_at", "")),
        )
    return RepairRecord(
        proposal=proposal,
        # An unrecognised state raises, and the caller drops that one record
        # rather than restoring a patch into a lifecycle state we cannot name.
        state=RepairState(str(raw.get("state", RepairState.PROPOSED.value))),
        review=raw.get("review"),
        approval=approval,
        tests=tests,
        applied_commit=raw.get("applied_commit"),
        checkpoint_commit=raw.get("checkpoint_commit"),
        branch_created=raw.get("branch_created"),
        receipts=[
            Receipt(
                step=str(x["step"]),
                outcome=x["outcome"],
                at=str(x["at"]),
                detail=str(x.get("detail", "")),
                evidence_class=str(x.get("evidence_class", "pipeline_transition")),
                evidence=dict(x.get("evidence") or {}),
            )
            for x in raw.get("receipts") or []
        ],
    )


class GitRepairApplier:
    """Applies and rolls back one repair against a real git working tree.

    Uses the real ``git`` binary. Every invocation is captured, and a non-zero exit
    is an error rather than a silently swallowed exception.
    """

    def __init__(self, repo_path: str, timeout: float = 30.0) -> None:
        #: Every path this applier has actually rewritten, so a commit stages
        #: exactly those and nothing else. See `commit_touched`.
        self.touched: set[str] = set()
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

    def branch_exists(self, branch: str) -> bool:
        code, _, _ = self._git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
        return code == 0

    def is_ancestor(self, maybe_ancestor: str, of_commit: str) -> bool:
        code, _, _ = self._git("merge-base", "--is-ancestor", maybe_ancestor, of_commit)
        return code == 0

    def branch_name_for(self, base_commit: str, branch: str) -> tuple[str, bool]:
        """The branch to use, and whether it already exists and may be moved.

        A repair branch left behind by an earlier attempt must not make the next
        attempt impossible, and it must never be quietly destroyed. So:

        * a free name is used as it is;
        * a branch whose tip is already contained in the base commit holds nothing
          that would be lost by moving it, and is reused;
        * anything else is left exactly where it is, and the repair takes the next
          free name (``-2``, ``-3``, ...), because a previous attempt's commits are
          still evidence even after its work was rolled back.
        """
        if not self.branch_exists(branch):
            return branch, False
        tip = self._git("rev-parse", f"refs/heads/{branch}")[1]
        if tip and self.is_ancestor(tip, base_commit):
            return branch, True
        for suffix in range(2, 21):
            candidate = f"{branch}-{suffix}"
            if not self.branch_exists(candidate):
                return candidate, False
        raise RuntimeError(
            f"branches {branch} and {branch}-2..20 all exist and none is contained in "
            f"{base_commit[:12]}; nothing was moved and nothing was written"
        )

    def create_branch(self, base_commit: str, branch: str) -> tuple[str, str]:
        """Branch from a known commit, and say which branch name was actually used.

        Returns ``(branch_used, commit)``. The name differs from the one asked for
        only when a previous attempt's branch is in the way - see
        :meth:`branch_name_for`, which is where the "never quietly destroy an earlier
        attempt" rule lives.
        """
        name, reuse = self.branch_name_for(base_commit, branch)
        flag = "-B" if reuse else "-b"
        code, out, err = self._git("checkout", flag, name, base_commit)
        if code != 0:
            raise RuntimeError(f"git checkout {flag} failed: {err or out}")
        code, out, _ = self._git("rev-parse", "HEAD")
        if code != 0:
            raise RuntimeError("branch created but HEAD is unreadable")
        return name, out

    def apply_snippet(self, relative_path: str, original: str, replacement: str) -> None:
        """Write the replacement, but only if the file still holds the original.

        This is the drift guard: a patch reviewed against one revision of a file
        must not silently land on a different revision.
        """
        path = Path(self.repo_path) / relative_path
        if not path.is_file():
            # Creating a file is the one case where "the reviewed content is no
            # longer present" has no meaning: there is nothing to compare against.
            # It is allowed only when the proposal asked for exactly that — an
            # empty original — and only when the path is genuinely new, so a
            # proposal can never overwrite a file that has appeared meanwhile.
            if original == "" and replacement.strip():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(replacement, encoding="utf-8")
                self.touched.add(Path(relative_path).as_posix())
                return
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
        self.touched.add(Path(relative_path).as_posix())

    def commit_touched(self, message: str) -> str:
        """Commit exactly the files this applier rewrote, and nothing else.

        This method used to run ``git add -A``, which swept *whatever happened to
        be dirty* into an autonomous repair commit: the owner's work in progress,
        runtime state files, ``__pycache__``. A real repair run on a real
        repository committed the reflex brain's own state file and a ``.pyc``
        alongside the fix, and said nothing about it. An unattended agent has no
        business committing files it was not asked to change, so this stages the
        paths it touched and refuses when there are none.
        """
        if not self.touched:
            raise RuntimeError(
                "this applier has not rewritten any file, so there is nothing of its own to "
                "commit; refusing rather than staging the rest of the working tree"
            )
        code, out, err = self._git("add", "--", *sorted(self.touched))
        if code != 0:
            raise RuntimeError(f"git add failed: {err or out}")
        code, out, err = self._git("commit", "-m", message, "--", *sorted(self.touched))
        if code != 0:
            raise RuntimeError(f"git commit failed: {err or out}")
        code, out, _ = self._git("rev-parse", "HEAD")
        if code != 0:
            raise RuntimeError("commit created but HEAD is unreadable")
        return out

    def commit_all(self, message: str) -> str:
        """Deprecated name for :meth:`commit_touched`. Stages only repaired files."""
        return self.commit_touched(message)

    def _commit_everything_for_tests(self, message: str) -> str:
        """The old sweep-everything commit. Kept for tests that prove it is gone."""
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

    def __init__(
        self,
        applier: GitRepairApplier | None = None,
        review_verification_key: bytes | None = None,
        state_path: str | None = None,
    ) -> None:
        self._applier = applier
        self._records: dict[str, RepairRecord] = {}
        self._seq = 0
        self._spent_review_approvals: set[str] = set()
        self._verifier = review_verification_key or self._load_review_key()
        # Explicit argument wins, then the environment, then in-memory only.
        self._state_path = (
            str(state_path or os.environ.get(STATE_ENV, "").strip()) or None
        )
        self._restore()

    @staticmethod
    def _load_review_key() -> bytes | None:
        """Load the shared review key, or None so reviews are refused rather than trusted."""
        for name in _REVIEW_SIGNING_ENV:
            value = os.environ.get(name)
            if value:
                return value.encode("utf-8")
        return None

    # ── durability ─────────────────────────────────────────────────────────
    # Every state change in this class ends at `_record`, including every
    # refusal, because `_refuse` goes through it. One call there is therefore
    # one place that has to be right, rather than a write sprinkled across five
    # methods that would eventually be missed in one of them.
    def _restore(self) -> None:
        """Reload records written by an earlier process. Invents nothing.

        A ledger that cannot be read is logged and left alone rather than raised:
        this runs at construction, and a corrupt file must not take the whole
        service down with it. The cost of that choice is stated plainly — the
        pipeline comes back empty, so previously approved patches are unknown
        again and will be refused rather than wrongly applied.
        """
        if not self._state_path:
            return
        path = Path(self._state_path)
        if not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.error("repair ledger at %s is unreadable, starting empty: %s", path, exc)
            return
        if not isinstance(raw, dict) or raw.get("version") != STATE_VERSION:
            logger.error(
                "repair ledger at %s has version %r, expected %d; not loading it",
                path,
                (raw or {}).get("version") if isinstance(raw, dict) else None,
                STATE_VERSION,
            )
            return
        for item in raw.get("records") or []:
            try:
                record = _record_from_dict(item)
            except (KeyError, TypeError, ValueError) as exc:
                logger.error("dropping an unreadable repair record: %s", exc)
                continue
            self._records[record.patch_id] = record
        self._spent_review_approvals = {
            str(x) for x in raw.get("spent_review_approvals") or []
        }
        # Never hand out an id that already names a restored record: a fresh
        # patch_0001 would silently overwrite the one written before the restart.
        self._seq = max(self._seq, int(raw.get("seq") or 0))
        logger.info(
            "restored %d repair record(s) from %s", len(self._records), path
        )

    def _persist(self) -> None:
        """Write the whole ledger, atomically.

        A failure here is logged, never raised. The commit may already exist in
        the working tree, and turning a successful apply into an error because the
        ledger could not be written would leave the patch applied *and*
        unrecorded — strictly worse than a durability guarantee that lapsed.
        """
        if not self._state_path:
            return
        path = Path(self._state_path)
        tmp = path.with_name(path.name + ".tmp")
        payload = {
            "version": STATE_VERSION,
            "seq": self._seq,
            "spent_review_approvals": sorted(self._spent_review_approvals),
            "records": [_record_to_dict(r) for r in self._records.values()],
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(payload, indent=2, sort_keys=True, default=str),
                encoding="utf-8",
            )
            # Replace rather than write in place: a crash mid-write then leaves
            # the previous ledger, never a half-written one.
            os.replace(tmp, path)
        except (OSError, TypeError, ValueError) as exc:
            logger.error("could not write the repair ledger to %s: %s", path, exc)

    # ── helpers ────────────────────────────────────────────────────────────
    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}_{self._seq:04d}"

    def _record(self, record: RepairRecord, step: str, outcome: str, **kw: Any) -> Receipt:
        receipt = Receipt(step=step, outcome=outcome, at=_stamp(_now()), **kw)
        record.receipts.append(receipt)
        self._persist()
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

    # ── the checkpoint a proposal should branch from ───────────────────────
    def head_commit(self) -> str | None:
        """The commit a proposal should be based on, or ``None`` if unknowable.

        Public because every caller that builds a proposal needs it: a proposal
        with an empty ``base_commit`` reaches ``git checkout -b`` as an empty
        pathspec and fails with a message that names git rather than the real
        problem. Asking the gate for its own checkpoint is the honest way to fill
        the field.
        """
        if self._applier is None:
            return None
        return self._applier.current_commit()

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
    def record_review(self, patch_id: str, review: dict[str, Any]) -> Receipt:
        """File Sentinel's review. Required before any approval can exist.

        The review is now a *signed document*, not a claimed identity. An earlier
        version took ``reviewer="sentinel"`` on trust, which meant anyone who could
        reach the endpoint could assert that the security agent had cleared their
        patch. The reviewer is no longer asked whether it approves: it is asked to
        prove it, by producing an HMAC over its own verdict that this gate can
        check against a shared key.

        Refusals, in the order they are checked:
          * the patch must exist and still be awaiting review
          * the document must be well formed and carry the reviewer's identity
          * the signature must verify under the configured key
          * the review must be bound to *this* patch's current fingerprint
          * the underlying single-use approval must not already have been spent
          * the verdict must be "clear"

        Verification is implemented here, locally, rather than by importing the
        signer. A verifier that calls the signer's own code is not independent.
        """
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
        if not isinstance(review, dict):
            return self._refuse(
                record, "review", GateRefusal.MALFORMED_REVIEW, "review is not a document"
            )
        if str(review.get("reviewer", "")).lower() != REVIEWER:
            return self._refuse(
                record,
                "review",
                GateRefusal.WRONG_REVIEWER,
                f"reviewer was {review.get('reviewer')!r}",
            )
        if not self._verifier:
            return self._refuse(
                record,
                "review",
                GateRefusal.NO_REVIEW_KEY,
                "no review verification key configured; an unverifiable review cannot be accepted",
            )
        if not verify_review_document(review, self._verifier):
            return self._refuse(
                record,
                "review",
                GateRefusal.BAD_REVIEW_SIGNATURE,
                "signature does not verify against the configured key",
            )

        expected_fingerprint = record.proposal.fingerprint()
        if str(review.get("patch_fingerprint", "")) != expected_fingerprint:
            return self._refuse(
                record,
                "review",
                GateRefusal.REVIEW_WRONG_PATCH,
                f"review covers fingerprint {str(review.get('patch_fingerprint'))[:12]}..., "
                f"patch is {expected_fingerprint[:12]}...",
            )

        approval_id = str(review.get("approval_id", ""))
        if not approval_id:
            return self._refuse(
                record, "review", GateRefusal.MALFORMED_REVIEW, "review carries no approval id"
            )
        if approval_id in self._spent_review_approvals:
            return self._refuse(
                record,
                "review",
                GateRefusal.REVIEW_APPROVAL_REPLAYED,
                f"approval {approval_id} was already spent on another review",
            )
        if self._is_review_stale(review):
            return self._refuse(
                record,
                "review",
                GateRefusal.REVIEW_EXPIRED,
                f"review issued at {review.get('issued_at')} is older than the review window",
            )

        verdict = str(review.get("verdict", ""))
        record.review = {
            "reviewer": REVIEWER,
            "verdict": verdict,
            "findings": list(review.get("findings", ())),
            "checks_run": list(review.get("checks_run", ())),
            "approval_id": approval_id,
            "reviewed_at": _stamp(_now()),
            "signature_verified": True,
        }

        if verdict.lower() != "clear":
            self._spent_review_approvals.add(approval_id)
            return self._refuse(
                record, "review", GateRefusal.REVIEW_REJECTED, f"verdict was {verdict!r}"
            )

        self._spent_review_approvals.add(approval_id)
        record.state = RepairState.REVIEWED
        return self._record(
            record,
            "review",
            "ACCEPTED",
            detail="sentinel review signature verified; awaiting owner decision",
            evidence={
                "reviewer": REVIEWER,
                "verdict": verdict,
                "signature_verified": True,
                "approval_id": approval_id,
                "bound_fingerprint": expected_fingerprint,
                "findings": list(review.get("findings", ())),
            },
        )

    def _is_review_stale(self, review: dict[str, Any]) -> bool:
        """Refuse a review that is too old to act on, whatever it signs."""
        try:
            issued_at = float(review.get("issued_at", 0.0))
        except (TypeError, ValueError):
            return True
        if issued_at <= 0.0:
            return True
        age = (_now() - datetime.fromtimestamp(issued_at, tz=timezone.utc)).total_seconds()
        # A small clock skew tolerance, then a hard stop.
        return age > REVIEW_MAX_AGE_SECONDS + 60.0

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
        from friday.cognition.identity import is_agent_namespace, is_owner_identity

        if not is_owner_identity(approver):
            # Two different refusals, because they mean different things: an agent
            # trying to approve its own work, versus a name nobody recognises.
            detail = (
                f"{approver!r} is an agent, not the owner; no agent may approve a repair"
                if is_agent_namespace(approver)
                else (
                    f"{approver!r} is not an identified owner; approval is the owner's own act. "
                    "Set FRIDAY_USER_NAME to the owner's name, or approve from the CLI."
                )
            )
            return self._refuse(record, "owner_decision", GateRefusal.WRONG_APPROVER, detail)

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

    # ── step 3b: owner's standing mandate ──────────────────────────────────
    def record_mandate_decision(
        self,
        patch_id: str,
        document: dict[str, Any],
        verification_key: bytes,
    ) -> Receipt:
        """Approve a repair under the owner's signed standing mandate.

        This is the owner's authority exercised in advance, not an agent
        approving itself. The difference is that the authority is *proven*, not
        asserted: the mandate is a signed document issued by the owner, bound to
        an expiry, a set of scopes and a set of permitted paths, and this method
        verifies all of it before the state machine advances.

        An agent still cannot approve anything. `record_owner_decision` continues
        to refuse every agent name, and this path refuses an issuer from the same
        set — a delegate cannot redelegate.

        The downstream property is unchanged and is the point: the approval is
        single-use, expires, and is bound to the patch fingerprint, so `apply`
        still refuses a replayed approval or a patch edited after consent.
        """
        record = self._records.get(patch_id)
        if record is None:
            return Receipt(
                step="mandate_decision",
                outcome="REFUSED",
                at=_stamp(_now()),
                detail=f"{GateRefusal.NOT_PROPOSED.value}: unknown patch {patch_id}",
            )
        if record.state is not RepairState.REVIEWED:
            return self._refuse(
                record,
                "mandate_decision",
                GateRefusal.NOT_REVIEWED,
                f"state is {record.state.value}; a mandate does not replace the review step",
            )
        if not isinstance(document, dict) or not document:
            return self._refuse(
                record,
                "mandate_decision",
                GateRefusal.MALFORMED_MANDATE,
                "no mandate document was supplied",
            )

        # Imported lazily so the gate stays loadable without the cognition
        # package, and so a verifier never executes the issuer's code.
        from friday.cognition.identity import is_owner_identity
        from friday.cognition.mandate import (
            SCOPE_CONFIG_REPAIR,
            SCOPE_SOURCE_REPAIR,
            AutonomyMandate,
            verify_mandate,
        )

        if not verification_key:
            return self._refuse(
                record,
                "mandate_decision",
                GateRefusal.BAD_MANDATE_SIGNATURE,
                "no verification key is configured, so no mandate can be trusted",
            )
        if not verify_mandate(document, verification_key):
            return self._refuse(
                record,
                "mandate_decision",
                GateRefusal.BAD_MANDATE_SIGNATURE,
                "the mandate's signature does not verify; it was altered or signed with another key",
            )

        mandate = AutonomyMandate.from_document(document)
        if not is_owner_identity(mandate.issued_by):
            # The wording distinguishes the two cases on purpose: an agent that
            # signed a mandate is attempting to widen its own authority, while an
            # unrecognised name is most likely a configuration mistake.
            from friday.cognition.identity import is_agent_namespace

            detail = (
                f"{mandate.issued_by!r} is an agent, not the owner; a delegate cannot redelegate"
                if is_agent_namespace(mandate.issued_by)
                else f"{mandate.issued_by!r} is not an identified owner; a delegate cannot redelegate"
            )
            return self._refuse(
                record,
                "mandate_decision",
                GateRefusal.WRONG_APPROVER,
                detail,
            )
        if mandate.is_expired():
            return self._refuse(
                record,
                "mandate_decision",
                GateRefusal.MANDATE_EXPIRED,
                f"mandate {mandate.mandate_id} expired at {_iso_from_epoch(mandate.expires_at)}",
            )
        if not mandate.grants(SCOPE_SOURCE_REPAIR) and not mandate.grants(SCOPE_CONFIG_REPAIR):
            return self._refuse(
                record,
                "mandate_decision",
                GateRefusal.MANDATE_SCOPE,
                "the mandate grants neither source_repair nor config_repair",
            )
        if not mandate.permits_path(record.proposal.target_file):
            return self._refuse(
                record,
                "mandate_decision",
                GateRefusal.MANDATE_PATH,
                f"the mandate does not permit changes to {record.proposal.target_file!r}",
            )

        record.approval = OwnerApproval(
            patch_fingerprint=record.proposal.fingerprint(),
            approver=f"{mandate.issued_by} (standing mandate {mandate.mandate_id})",
            approval_id=self._next_id("appr"),
        )
        record.state = RepairState.APPROVED
        return self._record(
            record,
            "mandate_decision",
            "ACCEPTED",
            detail=(
                f"approved under standing mandate {mandate.mandate_id}; "
                "approval is single-use, expiring and fingerprint-bound"
            ),
            evidence={
                "approver": mandate.issued_by,
                "mandate_id": mandate.mandate_id,
                "mandate_expires_at": _iso_from_epoch(mandate.expires_at),
                "scopes": list(mandate.scopes),
                "allowed_paths": list(mandate.allowed_paths),
                "signature_verified": True,
                "approval_id": record.approval.approval_id,
                "bound_fingerprint": record.approval.patch_fingerprint,
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
            branch_used, branch_commit = self._applier.create_branch(
                proposal.base_commit, proposal.branch
            )
            record.branch_created = branch_used
            self._applier.apply_snippet(
                proposal.target_file, proposal.original_snippet, proposal.replacement_snippet
            )
            record.applied_commit = self._applier.commit_touched(
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
            detail=f"applied on branch {record.branch_created}",
            evidence={
                "branch": record.branch_created,
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
