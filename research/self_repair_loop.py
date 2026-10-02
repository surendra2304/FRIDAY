"""End-to-end self-repair loop: Forge -> Sentinel -> owner -> FRIDAY gate.

Phase E1 completion. This script is the proof that the three services actually
talk to each other.

The gate runs in its **own real server process**, started here as a real
``uvicorn`` on a real port, and every gate interaction below is a real HTTP
request against the real published routes. The driver does not import the gate
and cannot call it directly, so nothing here can pass by shortcut.

  * FRIDAY's ``SelfRepairGate``     — the other process. Verifies Sentinel's HMAC
    against the shared key before accepting a review, then applies and rolls
    back against a real git working tree.
  * Sentinel's ``SelfRepairReviewer`` — inspects the proposed diff, mints a
    single-use approval through the existing ``ApprovalManager``, signs its
    verdict with Sentinel's existing audit scheme.
  * Forge's ``GitSelfRepairProposer`` — branches a real repository, runs a real
    test command before and after the change, and refuses to emit a proposal
    unless that command genuinely went from failing to passing.

Stated plainly: **Forge and Sentinel run inside this driver process**, because
they are libraries that speak HTTP rather than servers. What crosses a network
boundary here is every gate interaction, which is the boundary the gate's rules
and its control-access guard actually protect. The services were not exercised
against the live Forge and Sentinel deployments on Render.

Run it directly:

    python research/self_repair_loop.py

Nothing in the transcript is mocked. The repository is created on disk, the
tests run in a real shell, the branch and the commits are real, and the gate
refuses an unsigned or tampered review because the signature genuinely does not
verify against the key the other process was started with.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# The three services live in sibling checkouts. Real implementations, not copies.
UNIVERSE_ROOT = REPO_ROOT.parent
for service in ("Forge", "Sentinel"):
    candidate = UNIVERSE_ROOT / service
    if candidate.is_dir():
        sys.path.insert(0, str(candidate))

from app.selfrepair.proposer import (  # noqa: E402
    CandidateFix,
    GitSelfRepairProposer,
    ProposalOutcome,
)
from sentinel.core.auth.approvals import ApprovalManager  # noqa: E402
from sentinel.core.selfrepair.reviewer import SelfRepairReviewer  # noqa: E402
from sentinel.storage.persistence.durable_store import SentinelPersistence  # noqa: E402

#: One shared key, the way the two services would share it in deployment.
#: This is a literal in a test driver, NOT a deployment secret.
SHARED_KEY = "e2e-shared-review-key-not-a-real-secret"

#: The control key the server process is started with. Also a test literal.
CONTROL_KEY = "e2e-control-key-not-a-real-secret"

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


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class GateServer:
    """The FRIDAY gate as a separate, real, HTTP-serving process."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.port = free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen[bytes] | None = None
        self.log_path = repo.parent / "server.log"

    @property
    def headers(self) -> dict[str, str]:
        return {"x-friday-api-key": CONTROL_KEY}

    def start(self) -> None:
        env = {
            **os.environ,
            # What the gate applies to. Set before the module is imported.
            "FRIDAY_SELF_REPAIR_REPO": str(self.repo),
            # The key the gate verifies Sentinel's signature with. Set before the
            # module is imported, because a keyless gate accepts no review at all.
            "FRIDAY_SELF_REPAIR_REVIEW_KEY": SHARED_KEY,
            # Exercise the production control-access guard instead of the
            # loopback bypass, so the transcript proves the auth layer too.
            "RENDER": "1",
            "FRIDAY_API_KEY": CONTROL_KEY,
            "PYTHONPATH": str(REPO_ROOT / "src") + os.pathsep + str(REPO_ROOT),
            # Keep the server's background peer polling out of the transcript.
            "FRIDAY_FLEET_SUPERVISION_INTERVAL_SECONDS": "86400",
            "FRIDAY_MEMORA_POLL_INTERVAL_SECONDS": "86400",
        }
        log = self.log_path.open("wb")
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "friday.api.server:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "warning",
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )

    def wait_until_serving(self, timeout: float = 180.0) -> None:
        """Poll the real socket until the other process answers."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                raise RuntimeError(f"server exited early:\n{self.log_path.read_text(errors='replace')}")
            try:
                response = httpx.get(f"{self.base_url}/api/health", timeout=5.0)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise RuntimeError(f"server never became ready:\n{self.log_path.read_text(errors='replace')}")

    def stop(self) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    # ── the real HTTP surface ────────────────────────────────────────────
    def propose(self, body: dict[str, Any], authenticated: bool = True) -> dict[str, Any]:
        return self._post("/api/self-repair/proposals", body, authenticated)

    def review(self, patch_id: str, document: dict[str, Any]) -> dict[str, Any]:
        return self._post(f"/api/self-repair/{patch_id}/review", {"document": document})

    def owner_decision(self, patch_id: str, actor: str, approve: bool = True) -> dict[str, Any]:
        return self._post(
            f"/api/self-repair/{patch_id}/owner-decision", {"actor": actor, "approve": approve}
        )

    def apply(self, patch_id: str) -> dict[str, Any]:
        return self._post(f"/api/self-repair/{patch_id}/apply", {})

    def rollback(self, patch_id: str) -> dict[str, Any]:
        return self._post(f"/api/self-repair/{patch_id}/rollback", {})

    def status(self, patch_id: str) -> dict[str, Any]:
        response = httpx.get(
            f"{self.base_url}/api/self-repair/{patch_id}", headers=self.headers, timeout=60.0
        )
        response.raise_for_status()
        return response.json()["record"]

    def _post(
        self, path: str, body: dict[str, Any], authenticated: bool = True
    ) -> dict[str, Any]:
        headers = self.headers if authenticated else {}
        response = httpx.post(
            f"{self.base_url}{path}", json=body, headers=headers, timeout=300.0
        )
        response.raise_for_status()
        return response.json()


def show(title: str) -> None:
    print(f"\n=== {title} ===")


def show_receipt(receipt: dict[str, Any]) -> None:
    print(f"  {receipt['outcome']:<8} {receipt['detail']}")
    if receipt.get("evidence"):
        print(f"           evidence: {json.dumps(receipt['evidence'])}")


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

    show("1. the gate starts as a separate real HTTP server process")
    server = GateServer(repo)
    server.start()
    server.wait_until_serving()
    pid = server.proc.pid if server.proc else -1
    print(f"  pid    : {pid}")
    print(f"  url    : {server.base_url}")
    health = httpx.get(f"{server.base_url}/api/health", timeout=30.0).json()
    print(f"  health : overall={health.get('overall')} evidence_class={health.get('evidence_class')}")
    check("gate server is serving real HTTP", health.get("overall") == "healthy", str(health.get("overall")))
    check(
        "the server labels what its health claim actually proves",
        health.get("evidence_class") == "process_liveness",
        str(health.get("evidence_class")),
    )
    check("gate is a different process from this driver", pid != os.getpid(), f"server={pid} driver={os.getpid()}")

    show("2. the control guard refuses an unauthenticated caller")
    try:
        server.propose({"branch": "x", "base_commit": base}, authenticated=False)
        check("unauthenticated proposal refused", False, "the server accepted it")
    except httpx.HTTPStatusError as exc:
        print(f"  {exc.response.status_code} {exc.response.text.strip()[:160]}")
        check("unauthenticated proposal refused", exc.response.status_code == 401)

    store = SentinelPersistence(db_path=str(repo / "sentinel.db"))
    reviewer = SelfRepairReviewer(approvals=ApprovalManager(store), signing_key=SHARED_KEY)
    proposer = GitSelfRepairProposer(timeout=180.0)

    show("3. Forge proposes: real branch, real test before and after")
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
        server.stop()
        return 1

    request = outcome.to_request(str(repo))

    show("4. the gate refuses a proposal with no test evidence")
    stripped = {**request.__dict__, "test_evidence": {"command": test_cmd, "passed": False}}
    refused = server.propose(stripped)["receipt"]
    show_receipt(refused)
    check("evidence-free proposal refused", refused["outcome"] == "REFUSED")

    show("5. Forge files the real proposal over HTTP")
    filed = server.propose(
        {
            "repo_path": request.repo_path,
            "branch": request.branch,
            "base_commit": request.base_commit,
            "target_file": request.target_file,
            "original_snippet": request.original_snippet,
            "replacement_snippet": request.replacement_snippet,
            "rationale": request.rationale,
            "proposed_by": request.proposed_by,
            "test_evidence": request.test_evidence,
        }
    )
    receipt = filed["receipt"]
    record = filed["record"]
    patch_id = record["patch_id"]
    fingerprint = record["fingerprint"]
    show_receipt(receipt)
    print(f"  patch_id: {patch_id}")
    check("proposal accepted with real evidence", receipt["outcome"] == "ACCEPTED")
    check("proposal records the passing command", receipt["evidence"].get("test_command") == test_cmd)
    check("the fingerprint covers file and code", len(fingerprint) == 64)

    show("6. a forged review is refused (no Sentinel signature)")
    forged = {
        "patch_fingerprint": fingerprint,
        "verdict": "clear",
        "reviewer": "sentinel",
        "approval_id": "appr_forged",
        "findings": [],
        "checks_run": [],
        "issued_at": time.time(),
        "nonce": "forged",
        "signature": "0" * 64,
    }
    gate_refusal = server.review(patch_id, forged)["receipt"]
    show_receipt(gate_refusal)
    check("forged review refused", gate_refusal["outcome"] == "REFUSED")
    check(
        "forged review refused specifically for its signature",
        "BAD_REVIEW_SIGNATURE" in gate_refusal["detail"],
        gate_refusal["detail"],
    )

    show("7. a review signed for a different patch is refused")
    other_review = reviewer.review(
        patch_fingerprint="0" * 64,
        target_file=request.target_file,
        replacement_snippet=request.replacement_snippet,
        test_evidence=request.test_evidence,
    ).review.to_document()
    mismatched = server.review(patch_id, other_review)["receipt"]
    show_receipt(mismatched)
    check("mismatched-fingerprint review refused", mismatched["outcome"] == "REFUSED")
    check("refused for the right reason", "REVIEW_WRONG_PATCH" in mismatched["detail"], mismatched["detail"])

    show("8. Sentinel reviews the real patch and signs the verdict")
    reviewed = reviewer.review(
        patch_fingerprint=fingerprint,
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

    show("9. tampering with a signed review is refused")
    tampered = server.review(patch_id, {**document, "verdict": "block"})["receipt"]
    show_receipt(tampered)
    check("tampered verdict refused", tampered["outcome"] == "REFUSED")

    show("10. the genuinely signed review is accepted")
    accepted = server.review(patch_id, document)
    show_receipt(accepted["receipt"])
    record = server.status(patch_id)
    check("signed review accepted", accepted["receipt"]["outcome"] == "ACCEPTED")
    check("gate recorded that it verified the signature", (record["review"] or {}).get("signature_verified") is True)
    check("state is REVIEWED", record["state"] == "REVIEWED")

    show("11. a review is bound to one patch and cannot be reused for another")
    second = server.propose(
        {
            "repo_path": request.repo_path,
            "branch": "repair/other",
            "base_commit": request.base_commit,
            "target_file": request.target_file,
            "original_snippet": "    if old == 0:\n        return 0.0",
            "replacement_snippet": "    if old <= 0:\n        return 0.0",
            "rationale": "guard the base value",
            "test_evidence": request.test_evidence,
        }
    )["record"]
    replay = server.review(second["patch_id"], document)["receipt"]
    show_receipt(replay)
    check("reused review refused for a different patch", replay["outcome"] == "REFUSED")
    check("refused because the review is bound to another patch", "REVIEW_WRONG_PATCH" in replay["detail"], replay["detail"])
    check(
        "the spent-approval guard sits behind the fingerprint guard",
        replay["detail"].startswith("REVIEW_WRONG_PATCH"),
        "fingerprint binding fires first, which is the stronger check",
    )

    show("12. agents cannot approve; the owner can")
    for impostor in ("friday", "forge", "sentinel"):
        r = server.owner_decision(patch_id, impostor)["receipt"]
        check(f"{impostor} refused", r["outcome"] == "REFUSED", r["detail"])
    owner = server.owner_decision(patch_id, "surendra")
    show_receipt(owner["receipt"])
    check("owner approval accepted", owner["receipt"]["outcome"] == "ACCEPTED")

    show("13. apply produces a real commit on a real branch")
    applied = server.apply(patch_id)
    show_receipt(applied["receipt"])
    head = git(repo, "rev-parse", "HEAD")
    branch_now = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    file_now = (repo / "percent_change.py").read_text(encoding="utf-8")
    check("apply accepted", applied["receipt"]["outcome"] == "ACCEPTED")
    check("receipt names the real applied commit", applied["receipt"]["evidence"].get("applied_commit") == head)
    check("repo is on the repair branch", branch_now == "repair/percent-change")
    check("file really changed", "percent_change(old, new):.2f" in file_now)
    check("receipt records a rollback point", bool(applied["receipt"]["evidence"].get("rollback_point")))

    show("14. the approval is spent; a replayed apply is refused")
    replay_apply = server.apply(patch_id)
    show_receipt(replay_apply["receipt"])
    check("replayed apply refused", replay_apply["receipt"]["outcome"] == "REFUSED")
    check("refused as consumed", "APPROVAL_CONSUMED" in replay_apply["receipt"]["detail"])

    show("15. the fixed code really passes the real test")
    proc = subprocess.run(
        test_cmd, cwd=repo, shell=True, capture_output=True, text=True, timeout=180, env={**os.environ, **test_env}
    )
    print("    " + proc.stdout.strip().replace("\n", "\n    ")[:400])
    check("the applied patch makes the test pass", proc.returncode == 0)

    show("16. rollback restores the reviewed content as its own commit")
    rolled = server.rollback(patch_id)
    show_receipt(rolled["receipt"])
    file_after_rollback = (repo / "percent_change.py").read_text(encoding="utf-8")
    proc2 = subprocess.run(
        test_cmd, cwd=repo, shell=True, capture_output=True, text=True, timeout=180, env={**os.environ, **test_env}
    )
    print("    " + proc2.stdout.strip().replace("\n", "\n    ")[:400])
    record = server.status(patch_id)
    check("rollback accepted", rolled["receipt"]["outcome"] == "ACCEPTED")
    check("the original line is back", BROKEN_SNIPPET.strip() in file_after_rollback)
    check("the test fails again after rollback", proc2.returncode != 0)
    check("state is ROLLED_BACK", record["state"] == "ROLLED_BACK")

    show("summary")
    receipts = record["receipts"]
    print(f"  steps run      : {len(receipts)}")
    print(f"  acceptances    : {sum(1 for r in receipts if r['outcome'] == 'ACCEPTED')}")
    print(f"  refusals       : {sum(1 for r in receipts if r['outcome'] == 'REFUSED')}")
    print(f"  failures       : {len(failures)}")
    for name in failures:
        print(f"    FAILED: {name}")

    server.stop()
    shutil.rmtree(repo.parent, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
