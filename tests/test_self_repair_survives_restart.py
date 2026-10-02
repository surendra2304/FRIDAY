"""The gate's records must outlive the process that wrote them.

Every other self-repair proof in this repository runs a single process. That is
the blind spot this file exists to close: with the ledger in memory, a proposal
made before a restart comes back as ``unknown patch`` and refuses apply, and — far
worse — a patch that was *already applied* becomes unrollbackable with the record
of the apply gone. On a host that sleeps and redeploys, that is not a theoretical
window between propose and apply; it is the normal case.

So this test does not re-instantiate an object in this interpreter. It starts the
real application with a real ``uvicorn`` subprocess, kills it, and waits for the
process to actually be gone. Then it starts a *second, different* process against
the same repository and the same ledger and finishes the lifecycle there. The
lifecycle is split across three process generations on purpose:

    process 1:  propose
    process 2:  review, owner approval, apply
    process 3:  rollback

The last step is the one that matters. A gate that can apply but cannot roll back
after a restart is worse than one that cannot apply at all.

The review signature is computed here from the documented scheme rather than by
importing the gate's own verifier, so this file does not pass by sharing a bug
with the code under test. Nothing else in this file imports ``self_repair``: the
gate is only ever reached over HTTP.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Test literals. They are not deployment secrets and prove nothing about how a
#: real key is distributed; they exist so the gate has something to verify against.
REVIEW_KEY = "restart-proof-review-key"
CONTROL_KEY = "restart-proof-control-key"

BROKEN = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"

#: One process generation costs a few seconds of import time. Generous, because a
#: loaded Windows CI runner is the slow case, not the exception.
STARTUP_TIMEOUT = 180.0


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True, timeout=60
    )
    return proc.stdout.strip()


def _fingerprint(target_file: str, original: str, replacement: str) -> str:
    """The gate's patch fingerprint, recomputed here from its documented inputs."""
    payload = json.dumps(
        {"target_file": target_file, "original_snippet": original,
         "replacement_snippet": replacement},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _review(fingerprint: str) -> dict[str, Any]:
    """A clear, freshly issued review spending a known single-use approval."""
    return {
        "reviewer": "sentinel",
        "verdict": "clear",
        "patch_fingerprint": fingerprint,
        "approval_id": "appr_restart_1",
        "issued_at": time.time(),
        "findings": ["touches one file"],
        "checks_run": ["test evidence present"],
    }


def _signed_review(document: dict[str, Any], key: str = REVIEW_KEY) -> dict[str, Any]:
    """Sign a review the way Sentinel's audit logger does, without importing it.

    hash = sha256(canonical_json(document minus "signature"));
    signature = hmac_sha256(key, hash).
    """
    body = json.dumps(document, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    signature = hmac.new(key.encode("utf-8"), digest.encode("utf-8"), hashlib.sha256).hexdigest()
    return {**document, "signature": signature}


class Gate:
    """The real application, in its own OS process, killed and restarted for real."""

    def __init__(self, repo: Path, ledger: Path) -> None:
        self.repo = repo
        self.ledger = ledger
        self.port = self._free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.log_path = ledger.with_name(f"gate-{self.port}.log")
        self.proc: subprocess.Popen[bytes] | None = None
        self.starts = 0

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def start(self) -> "Gate":
        self.port = self._free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        env = {
            **os.environ,
            # What the gate applies to.
            "FRIDAY_SELF_REPAIR_REPO": str(self.repo),
            # The ledger that has to outlive this process.
            "FRIDAY_SELF_REPAIR_STATE": str(self.ledger),
            # The key the gate verifies Sentinel's signature with. Without it the
            # gate accepts no review at all, and this test would prove nothing.
            "FRIDAY_SELF_REPAIR_REVIEW_KEY": REVIEW_KEY,
            # Exercise the production control-access guard, not the loopback bypass.
            "RENDER": "1",
            "FRIDAY_API_KEY": CONTROL_KEY,
            "PYTHONPATH": str(REPO_ROOT / "src") + os.pathsep + str(REPO_ROOT),
            # Keep background peer polling out of the transcript and the wall clock.
            "FRIDAY_FLEET_SUPERVISION_INTERVAL_SECONDS": "86400",
            "FRIDAY_MEMORA_POLL_INTERVAL_SECONDS": "86400",
        }
        log = self.log_path.open("wb")
        self.proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn", "friday.api.server:app",
                "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning",
            ],
            cwd=REPO_ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        self.starts += 1
        self.wait_until_serving()
        return self

    def wait_until_serving(self) -> None:
        deadline = time.monotonic() + STARTUP_TIMEOUT
        last = ""
        while time.monotonic() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                raise AssertionError(
                    f"the gate exited during startup: {self.log_path.read_text(errors='replace')[-2000:]}"
                )
            try:
                response = httpx.get(f"{self.base_url}/health", timeout=5.0)
                if response.status_code == 200:
                    return
                last = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                last = str(exc)
            time.sleep(0.4)
        raise AssertionError(f"the gate never answered on {self.base_url}: {last}")

    def stop(self) -> int:
        """Terminate and wait. Returns the exit code, so 'it really died' is provable."""
        assert self.proc is not None, "no process was started"
        self.proc.terminate()
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=30)
        code = self.proc.returncode
        self.proc = None
        return int(code or 0)

    @property
    def headers(self) -> dict[str, str]:
        return {"x-friday-api-key": CONTROL_KEY}

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(
            f"{self.base_url}{path}", json=body, headers=self.headers, timeout=60.0
        )
        response.raise_for_status()
        return response.json()

    def get(self, path: str) -> dict[str, Any]:
        response = httpx.get(f"{self.base_url}{path}", headers=self.headers, timeout=60.0)
        response.raise_for_status()
        return response.json()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real repository with one real file and one real commit."""
    root = tmp_path / "target"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "restart@localhost")
    _git(root, "config", "user.name", "Restart")
    (root / "calc.py").write_text(BROKEN, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "a calculator that subtracts")
    return root


def _proposal_body(base: str, branch: str = "repair/add") -> dict[str, Any]:
    return {
        "repo_path": "",
        "branch": branch,
        "base_commit": base,
        "target_file": "calc.py",
        "original_snippet": "    return a - b\n",
        "replacement_snippet": "    return a + b\n",
        "rationale": "add subtracts",
        "proposed_by": "forge",
        "test_evidence": {
            "command": "pytest -q",
            "passed": True,
            "summary": "1 passed",
            "returncode": 0,
        },
    }


def test_the_whole_lifecycle_survives_two_real_process_restarts(repo: Path) -> None:
    """Propose, kill, review+approve+apply, kill, roll back. Three processes."""
    base = _git(repo, "rev-parse", "HEAD")
    ledger = repo.parent / "repair-ledger.json"
    fingerprint = _fingerprint("calc.py", "    return a - b\n", "    return a + b\n")

    gate = Gate(repo, ledger)
    try:
        # ── process 1: the proposal, then the review that spends its approval ──
        first = gate.start()
        pid_one = first.proc.pid if first.proc else -1
        filed = first.post("/api/self-repair/proposals", _proposal_body(base))
        assert filed["receipt"]["outcome"] == "ACCEPTED", filed["receipt"]
        patch_id = filed["record"]["patch_id"]
        assert filed["record"]["state"] == "PROPOSED"

        reviewed = first.post(
            f"/api/self-repair/{patch_id}/review", {"document": _signed_review(_review(fingerprint))}
        )
        assert reviewed["receipt"]["outcome"] == "ACCEPTED", reviewed["receipt"]
        assert reviewed["record"]["review"]["signature_verified"] is True

        exit_code = first.stop()
        assert first.proc is None, "the first gate process was not actually stopped"

        # ── process 2: everything that needs the record to still be there ──
        second = Gate(repo, ledger).start()
        pid_two = second.proc.pid if second.proc else -1
        assert pid_two != pid_one, "the restart reused a process; nothing was proved"

        restored = second.get(f"/api/self-repair/{patch_id}")["record"]
        assert restored["state"] == "REVIEWED", (
            f"the proposal and its signed review did not survive the restart; "
            f"process 1 exited {exit_code}"
        )
        assert restored["fingerprint"] == fingerprint
        assert [r["step"] for r in restored["receipts"]] == ["propose", "review"]

        # The single-use rule must survive the restart too, and this is the only
        # way to show it: a *different* patch, in a *fresh* process, spending the
        # approval the previous process already spent. This process's own memory
        # has never heard of that approval id, so only the ledger can refuse it.
        other = second.post("/api/self-repair/proposals", _proposal_body(base, branch="repair/other"))
        assert other["receipt"]["outcome"] == "ACCEPTED", other["receipt"]
        other_id = other["record"]["patch_id"]
        assert other_id != patch_id, "the id sequence was reused after the restart"

        replay = second.post(
            f"/api/self-repair/{other_id}/review", {"document": _signed_review(_review(fingerprint))}
        )
        assert replay["receipt"]["outcome"] == "REFUSED", replay["receipt"]
        assert "REVIEW_APPROVAL_REPLAYED" in replay["receipt"]["detail"], (
            "an approval spent by a previous process was accepted again; the "
            "single-use rule does not outlive a restart"
        )

        approved = second.post(
            f"/api/self-repair/{patch_id}/owner-decision",
            {"actor": "surendra", "approve": True},
        )
        assert approved["receipt"]["outcome"] == "ACCEPTED", approved["receipt"]

        applied = second.post(f"/api/self-repair/{patch_id}/apply", {})
        assert applied["receipt"]["outcome"] == "ACCEPTED", applied["receipt"]
        applied_commit = applied["receipt"]["evidence"]["applied_commit"]
        assert applied_commit == _git(repo, "rev-parse", "HEAD"), (
            "the receipt names a commit that is not the repository head"
        )
        assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "repair/add"
        assert "a + b" in (repo / "calc.py").read_text(encoding="utf-8")

        second.stop()

        # ── process 3: the step that must never be lost ───────────────────
        third = Gate(repo, ledger).start()
        pid_three = third.proc.pid if third.proc else -1
        assert pid_three not in (pid_one, pid_two)

        still_applied = third.get(f"/api/self-repair/{patch_id}")["record"]
        assert still_applied["state"] == "APPLIED", (
            "the applied patch was forgotten by the restart; it can no longer be rolled back"
        )
        assert still_applied["applied_commit"] == applied_commit
        assert still_applied["approval"]["consumed"] is True

        rolled = third.post(f"/api/self-repair/{patch_id}/rollback", {})
        assert rolled["receipt"]["outcome"] == "ACCEPTED", rolled["receipt"]
        assert "a - b" in (repo / "calc.py").read_text(encoding="utf-8"), (
            "the rollback reported success but the file still holds the fix"
        )
        assert _git(repo, "rev-parse", "HEAD") != applied_commit, (
            "the reversal was reported as a commit but is not one"
        )

        final = third.get(f"/api/self-repair/{patch_id}")["record"]
        assert final["state"] == "ROLLED_BACK"
        steps = [r["step"] for r in final["receipts"]]
        assert steps == ["propose", "review", "owner_decision", "apply", "rollback"], (
            f"the ledger did not carry the whole lifecycle across restarts: {steps}"
        )
        third.stop()
    finally:
        if gate.proc is not None:
            gate.stop()


def test_the_ledger_refuses_to_guess_at_a_version_it_does_not_know(repo: Path) -> None:
    """A half-written or future ledger must not restore a repair it cannot describe."""
    from friday.autonomous.self_repair import SelfRepairGate

    ledger = repo.parent / "repair-ledger.json"
    ledger.write_text(json.dumps({"version": 999, "records": ["nonsense"]}), encoding="utf-8")
    gate = SelfRepairGate(state_path=str(ledger))
    assert gate.all_records() == [], "a ledger of an unknown version was loaded anyway"

    ledger.write_text("{ not json", encoding="utf-8")
    assert SelfRepairGate(state_path=str(ledger)).all_records() == [], (
        "a corrupt ledger was loaded instead of being refused"
    )


def test_no_ledger_path_means_no_ledger_written(repo: Path) -> None:
    """With nothing configured the gate behaves exactly as it always has."""
    from friday.autonomous.self_repair import RepairProposal, SelfRepairGate

    gate = SelfRepairGate()
    record, receipt = gate.propose(
        RepairProposal(
            repo_path=str(repo),
            branch="repair/add",
            base_commit="abc",
            target_file="calc.py",
            original_snippet="    return a - b\n",
            replacement_snippet="    return a + b\n",
            rationale="add subtracts",
            test_evidence={"command": "pytest -q", "passed": True},
        )
    )
    assert receipt.outcome == "ACCEPTED"
    assert record.patch_id == "patch_0001"
    assert not list(repo.parent.glob("*.json")), "an unconfigured gate wrote a ledger"
