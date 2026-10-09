"""Installing a capability FRIDAY has never had — through the same gate as a repair.

The gap this closes, stated plainly: `ToolSynthesiser` could write a brand-new tool
file straight into the working tree. It verified the candidate with a real smoke
test first, and its own report said the tool "reaches the repository through the
same gate as any other change, with test evidence and a review" — but nothing in
the code carried it there. A file that appears in the tree with no commit, no
review, no evidence and no mandate is exactly the ungoverned self-modification the
gate exists to prevent, so this module is the missing half:

    synthesise (unchanged)  →  CapabilityInstaller.install()

`install()` puts the candidate through `SelfRepairGate` with the *same* discipline
as a repair:

1. a proposal, whose test evidence is the smoke test that actually ran, named;
2. a signed review from the configured reviewer, which decides on the real code;
3. authority: a standing mandate covering the path, or the owner's live approval —
   with no mandate the install stops and says so;
4. apply, then verify **on the applied tree** with the same smoke test, and roll
   back automatically if that verification fails.

The review bound is raised for a new file, deliberately and visibly: a repair is
limited to a small diff, while a new tool is a whole file. The reviewer is built
with a larger bound for this one purpose and the raise is recorded in the
proposal's evidence, so nothing about it is hidden.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from friday.cognition.reviewer import MAX_REPLACEMENT_LINES, LocalReviewer
from friday.cognition.tool_paths import ToolPathError, resolve_tool_module_path
from friday.core.logging import get_logger

logger = get_logger("cognition.installation")

#: How large a brand-new tool file may be. Big enough for the tool template plus a
#: real body, small enough that a runaway model cannot install a module of code.
MAX_NEW_TOOL_LINES = 220


@dataclass
class InstallOutcome:
    """What happened to one candidate capability, in a shape a caller can print."""

    tool: str
    capability: str
    path: str
    reachable: bool = False          # did it end up importable from the repository
    gate_step: str = ""              # propose | review | authority | apply | verify
    outcome: str = ""                # COMPLETED | AWAITING_MANDATE | REFUSED | ROLLED_BACK | ...
    patch_id: str = ""
    commit: str | None = None
    branch: str = ""
    verification: dict[str, Any] = field(default_factory=dict)
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "capability": self.capability,
            "path": self.path,
            "reachable": self.reachable,
            "gate_step": self.gate_step,
            "outcome": self.outcome,
            "patch_id": self.patch_id,
            "commit": self.commit,
            "branch": self.branch,
            "verification": self.verification,
            "detail": self.detail,
        }


class CapabilityInstaller:
    """Runs one candidate tool through the repair gate, unattended when allowed."""

    def __init__(
        self,
        repo_root: str | Path,
        *,
        gate: Any | None = None,
        authority: Any | None = None,
        reviewer: Any | None = None,
        python_executable: str | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self._gate = gate
        self._authority = authority
        self._reviewer = reviewer
        self.python = python_executable or sys.executable

    # -- collaborators, built lazily so the module stays importable ---------

    def _gate_or_build(self) -> tuple[Any | None, str]:
        if self._gate is not None:
            return self._gate, ""
        try:
            from friday.autonomous.self_repair import GitRepairApplier, SelfRepairGate
            from friday.cognition.reviewer import build_local_reviewer_from_env

            reviewer_key = None
            probe = build_local_reviewer_from_env()
            if probe is not None:
                reviewer_key = getattr(probe, "_key", None)
            gate = SelfRepairGate(
                GitRepairApplier(str(self.repo_root)), review_verification_key=reviewer_key
            )
            self._gate = gate
            return gate, ""
        except Exception as exc:  # pragma: no cover - configuration dependent
            return None, f"{type(exc).__name__}: {exc}"

    def _reviewer_or_build(self) -> Any | None:
        if self._reviewer is not None:
            return self._reviewer
        try:
            from friday.cognition.reviewer import build_local_reviewer_from_env

            base = build_local_reviewer_from_env()
            if base is None:
                return None
            self._reviewer = LocalReviewer(
                getattr(base, "_key"),
                reviewer_id=getattr(base, "_id", "local"),
                max_replacement_lines=MAX_NEW_TOOL_LINES,
            )
            return self._reviewer
        except Exception as exc:  # pragma: no cover - configuration dependent
            logger.warning("no reviewer could be built for capability installation: %s", exc)
            return None

    def _authority_or_none(self) -> Any | None:
        if self._authority is not None:
            return self._authority
        try:
            from friday.cognition.mandate import MandateAuthority

            self._authority = MandateAuthority()
            return self._authority
        except Exception:  # pragma: no cover - configuration dependent
            return None

    # -- the pipeline ------------------------------------------------------

    def install(
        self,
        *,
        tool_name: str,
        source: str,
        capability: str,
        rationale: str,
        smoke_check: dict[str, Any],
        relative_path: str = "",
        requested_by: str = "friday",
        self_test: dict[str, Any] | None = None,
    ) -> InstallOutcome:
        """Put one candidate tool through propose → review → authority → apply → verify.

        ``self_test`` is the author's stated example, when there is one. It is run
        against the candidate before the gate sees it *and again on the applied tree*,
        where the file that will actually be imported is the one being tested.
        """
        requested_path = relative_path or f"src/friday/tools/builtin/{tool_name}.py"
        try:
            relative, destination = resolve_tool_module_path(
                self.repo_root, requested_path, tool_name=tool_name
            )
        except ToolPathError as exc:
            return InstallOutcome(
                tool=tool_name,
                capability=capability,
                path=requested_path,
                gate_step="propose",
                outcome="REFUSED",
                detail=f"unsafe generated-tool path: {exc}",
            )
        outcome = InstallOutcome(tool=tool_name, capability=capability, path=relative)
        if destination.exists():
            outcome.gate_step = "propose"
            outcome.outcome = "REFUSED"
            outcome.detail = f"{relative} already exists; refusing to overwrite a real file"
            return outcome

        gate, build_error = self._gate_or_build()
        if gate is None:
            outcome.gate_step = "propose"
            outcome.outcome = "NO_GATE"
            outcome.detail = (
                "no repair gate is available in this checkout, so nothing was written at all: "
                f"{build_error or 'no gate configured'}"
            )
            return outcome

        # Evidence: the smoke test that actually ran, quoted as it ran.
        evidence = {
            "command": smoke_check.get("command") or f"smoke test of {tool_name}",
            "passed": bool(smoke_check.get("ok")),
            "summary": str(smoke_check.get("detail") or "")[:300],
            "checks": list(smoke_check.get("checks") or []),
        }
        if not evidence["passed"]:
            outcome.gate_step = "propose"
            outcome.outcome = "REFUSED"
            outcome.detail = "the candidate failed its own smoke test, so it was never proposed"
            outcome.verification = smoke_check
            return outcome

        from friday.autonomous.self_repair import RepairProposal

        base_commit = self._head_commit()
        if base_commit is None:
            outcome.gate_step = "propose"
            outcome.outcome = "NO_CHECKPOINT"
            outcome.detail = "the repository has no readable HEAD, so no change can be checkpointed"
            return outcome

        proposal = RepairProposal(
            repo_path=str(self.repo_root),
            branch=f"capability/{tool_name}",
            base_commit=base_commit,
            target_file=relative,
            original_snippet="",           # creating a file, not editing one
            replacement_snippet=source,
            rationale=rationale or f"install the synthesised capability {capability}",
            proposed_by=requested_by,
            test_evidence=evidence,
        )
        record, receipt = gate.propose(proposal)
        outcome.patch_id = record.patch_id
        outcome.branch = proposal.branch
        outcome.gate_step = "propose"
        if receipt.outcome != "ACCEPTED":
            outcome.outcome = "REFUSED"
            outcome.detail = f"the proposal was refused: {receipt.detail}"
            return outcome

        # Review, on the real candidate, by the configured reviewer.
        reviewer = self._reviewer_or_build()
        if reviewer is None:
            outcome.gate_step = "review"
            outcome.outcome = "AWAITING_REVIEWER"
            outcome.detail = (
                "the candidate is synthesised and proposed, but no reviewer is configured on this "
                "machine (set FRIDAY_SELF_REPAIR_REVIEW_KEY), so no review could be signed and "
                "nothing was installed"
            )
            return outcome
        review = reviewer.review(
            patch_fingerprint=record.proposal.fingerprint(),
            target_file=relative,
            replacement_snippet=source,
            original_snippet="",
            current_source="",
            test_evidence=evidence,
            approval_id=f"install_{tool_name}",
        )
        review_receipt = gate.record_review(record.patch_id, review.document)
        outcome.gate_step = "review"
        if review_receipt.outcome != "ACCEPTED":
            outcome.outcome = "REVIEW_REJECTED"
            outcome.detail = f"the review did not clear the candidate: {review_receipt.detail}"
            outcome.verification = {"review": review.document.get("findings", [])}
            return outcome
        reviewed_record = gate.get(record.patch_id)
        outcome.verification = {
            "checks_run": list(getattr(reviewed_record, "review", {}).get("checks_run", []))
            if isinstance(getattr(reviewed_record, "review", None), dict)
            else [],
            "replacement_line_bound": MAX_NEW_TOOL_LINES,
            "default_repair_line_bound": MAX_REPLACEMENT_LINES,
        }

        # Authority: a standing mandate for this path, or nothing.
        authority = self._authority_or_none()
        if authority is None:
            outcome.gate_step = "authority"
            outcome.outcome = "AWAITING_MANDATE"
            outcome.detail = (
                "no autonomy authority is configured, so the reviewed candidate waits for the "
                "owner: `friday --grant-autonomy` or `friday --approve-repair "
                f"{record.patch_id}`"
            )
            return outcome
        verdict = authority.evaluate("source_repair", paths=(relative,), has_test_evidence=True)
        if not getattr(verdict, "allowed", False):
            outcome.gate_step = "authority"
            outcome.outcome = "AWAITING_MANDATE"
            outcome.detail = (
                f"{getattr(verdict, 'refusal', 'NO_MANDATE')}: {getattr(verdict, 'reason', '')} "
                f"— the candidate is reviewed and one command from installed: "
                f"`friday --approve-repair {record.patch_id}`"
            )
            return outcome

        approval = authority.approve_repair(gate, record.patch_id, scope="source_repair")
        outcome.gate_step = "authority"
        if approval is None or getattr(approval, "outcome", "REFUSED") != "ACCEPTED":
            outcome.outcome = "REFUSED"
            outcome.detail = f"approval was refused: {getattr(approval, 'detail', '')}"
            return outcome

        applied = gate.apply(record.patch_id)
        outcome.gate_step = "apply"
        if applied.outcome != "ACCEPTED":
            outcome.outcome = "REFUSED"
            outcome.detail = f"apply was refused: {applied.detail}"
            return outcome
        outcome.commit = getattr(gate.get(record.patch_id), "applied_commit", None)

        # Verify on the applied tree, with the same smoke test, then decide.
        verification = self.smoke_test(destination, tool_name, self_test=self_test)
        outcome.verification["applied_tree"] = verification
        outcome.gate_step = "verify"
        if not verification.get("ok"):
            rolled = gate.rollback(record.patch_id)
            outcome.outcome = "ROLLED_BACK"
            outcome.detail = (
                "the tool passed its smoke test before installation and failed it on the applied "
                f"tree, so it was rolled back automatically ({rolled.outcome})"
            )
            return outcome

        outcome.reachable = True
        outcome.outcome = "COMPLETED"
        outcome.detail = (
            f"{relative} was reviewed, authorised by the standing mandate, installed and verified "
            "on the real tree"
        )
        return outcome

    # -- helpers -----------------------------------------------------------

    def _head_commit(self) -> str | None:
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return proc.stdout.strip() if proc.returncode == 0 else None

    def smoke_test(
        self, path: Path, tool_name: str, self_test: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Import the candidate in a fresh interpreter and call it once.

        Reuses the synthesiser's driver so the check that admitted the candidate is
        exactly the check that verifies it landed. When the author stated an example,
        the driver runs it here too: "the file that landed behaves as claimed" is a
        stronger statement than "a file with this source once did".
        """
        from friday.cognition.capability import ToolSynthesiser

        driver = ToolSynthesiser._SMOKE_DRIVER
        try:
            proc = subprocess.run(
                [
                    self.python,
                    "-c",
                    driver,
                    str(path),
                    f"friday_capability_{tool_name}",
                    tool_name,
                    json.dumps(self_test) if self_test else "",
                ],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "checks": [], "detail": f"{type(exc).__name__}: {exc}"}
        payload = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
        try:
            verdict = json.loads(payload)
        except (ValueError, IndexError):
            return {
                "ok": False,
                "checks": [],
                "detail": f"the smoke test produced no verdict (exit {proc.returncode})",
            }
        verdict.setdefault("command", "smoke test in a fresh interpreter")
        return verdict
