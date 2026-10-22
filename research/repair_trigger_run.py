"""Run the Phase F2 trigger against a real gate, real Forge, real Sentinel.

This is the operational proof for the trigger. ``research/self_repair_loop.py``
proves the gate's rules; this proves that the thing which would actually run
unattended reaches ``REVIEWED`` on its own and then stops — without an owner,
without an approval, and without touching a working tree.

It starts the gate as a real ``uvicorn`` process on a real port, wires in the
real Forge proposer and the real Sentinel reviewer from the sibling checkouts,
and drives the trigger over HTTP. The gate is started with ``RENDER=1`` so the
production control-access guard is exercised rather than the loopback bypass.

The trigger itself stops at ``REVIEWED``. The owner decision, the apply commit
and the rollback are made by a *different* caller, so the transcript shows both
halves: the unattended half stops on its own, and the human half is what writes.

What the transcript below is, stated before you read it:

REAL — a real git repository on disk, a real failing test run by a real
subprocess, a real branch, a real commit for the apply and another for the
revert, a real HTTP server in its own OS process, a real HMAC signature verified
by a verifier that never imports the signer, and a real 401 from the production
control-access guard.

LOCAL, NOT LIVE — the gate here is a process on this machine on a random port,
not a deployed service. Nothing in this transcript has touched a deployed
Render instance. The shared review key and the control key are test literals
handed to the gate by this driver, not deployment secrets.

SIMULATED — the owner decision is made by this driver as a named caller over
HTTP ("surendra"), not by a human clicking a button. Forge and Sentinel run
inside this process because they are HTTP libraries, not servers, so only the
gate interactions cross the network boundary. The trigger is invoked directly by
this script; nothing yet schedules it in the running service.

Run it:

    python research/repair_trigger_run.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

UNIVERSE_ROOT = REPO_ROOT.parent
for service in ("Forge", "Sentinel"):
    candidate = UNIVERSE_ROOT / service
    if candidate.is_dir():
        sys.path.insert(0, str(candidate))

from app.selfrepair.proposer import CandidateFix, GitSelfRepairProposer  # noqa: E402
from friday.autonomous.repair_trigger import (  # noqa: E402
    HttpxGateClient,
    RepairTrigger,
    WatchSpec,
    render_summary,
)
from sentinel.core.auth.approvals import ApprovalManager  # noqa: E402
from sentinel.core.selfrepair.reviewer import SelfRepairReviewer  # noqa: E402
from sentinel.storage.persistence.durable_store import SentinelPersistence  # noqa: E402
from self_repair_loop import (  # noqa: E402
    BROKEN_SNIPPET,
    CONTROL_KEY,
    FIXED_SNIPPET,
    SHARED_KEY,
    GateServer,
    build_broken_repo,
    git,
)


class _RecordingClient:
    """Wraps the real HTTP client and remembers every path it was asked for."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.paths: list[str] = []

    async def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.paths.append(path)
        return await self._inner.post(path, body)


async def run() -> int:
    failures: list[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        mark = "PASS" if condition else "FAIL"
        print(f"  [{mark}] {label}{(' - ' + detail) if detail else ''}")
        if not condition:
            failures.append(label)

    print("\n=== 0. a real repository with a real failing test ===")
    repo, base = build_broken_repo()
    print(f"  repo : {repo}")
    print(f"  base : {base}")

    print("\n=== 1. the gate runs as a separate real HTTP process ===")
    server = GateServer(repo)
    server.start()
    server.wait_until_serving()
    print(f"  pid  : {server.proc.pid if server.proc else -1}")
    print(f"  url  : {server.base_url}")
    check("gate is serving real HTTP", server.proc is not None and server.proc.poll() is None)

    print("\n=== 2. the trigger runs unattended, with no owner present ===")
    client = _RecordingClient(HttpxGateClient(server.base_url, CONTROL_KEY))
    # The reviewer's own durable state must never land inside the repository under
    # repair. It is a service concern, it is not part of the patch, and a review
    # audit trail written into a caller's working tree is both noise in their diff
    # and a way for untracked files to accumulate in a repo that is supposed to be
    # untouched. Pointed at ``repo/`` it wrote sentinel.db, -wal and -shm there and
    # made the working tree dirty, which is how this was found.
    reviewer_state = repo.parent / "reviewer-state"
    reviewer_state.mkdir(parents=True, exist_ok=True)
    store = SentinelPersistence(db_path=str(reviewer_state / "sentinel.db"))
    reviewer = SelfRepairReviewer(
        approvals=ApprovalManager(store), signing_key=SHARED_KEY
    )
    trigger = RepairTrigger(
        client,
        proposal_factory=lambda: GitSelfRepairProposer(timeout=180.0),
        reviewer_factory=lambda: reviewer,
        candidate_factory=lambda spec: CandidateFix(
            target_file=spec.target_file,
            original_snippet=spec.original_snippet,
            replacement_snippet=spec.replacement_snippet,
            rationale=spec.rationale,
        ),
    )

    test_cmd = f'"{sys.executable}" -m pytest test_percent_change.py -q'
    good = WatchSpec(
        name="describe-double-scales",
        repo_path=str(repo),
        base_commit=base,
        branch="repair/percent-change",
        target_file="percent_change.py",
        original_snippet=BROKEN_SNIPPET,
        replacement_snippet=FIXED_SNIPPET,
        rationale="describe multiplies by 100 again; percent_change already returns a percentage",
        test_command=test_cmd,
        env={"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_ADDOPTS": "-p no:cacheprovider"},
    )
    # A second spec whose candidate fix is genuinely wrong. The proposer must
    # decline it, and the trigger must report no proposal rather than filing one.
    bad = WatchSpec(
        name="describe-drops-the-percent",
        repo_path=str(repo),
        base_commit=base,
        branch="repair/wrong",
        target_file="percent_change.py",
        original_snippet=BROKEN_SNIPPET,
        replacement_snippet='    return f"{percent_change(old, new):.2f}"\n',
        rationale="removes the percent sign, which the test also rejects",
        test_command=test_cmd,
        env={"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_ADDOPTS": "-p no:cacheprovider"},
    )

    outcomes = await trigger.run_once([good, bad])
    print(render_summary(outcomes))

    check(
        "no spec lost its result to a failed gate call",
        not any(o.call_failed for o in outcomes),
        ", ".join(f"{o.spec}: {o.call_detail}" for o in outcomes if o.call_failed),
    )
    check("the correct repair was proposed", outcomes[0].proposed)
    check("the real test proved it before filing", outcomes[0].test_proved)
    check("the review was accepted with a verified signature", outcomes[0].signature_verified)
    check("the repair is waiting on the owner", outcomes[0].waiting_on_owner)
    check(
        "the wrong candidate fix was declined with no proposal",
        not outcomes[1].proposed,
        outcomes[1].proposal_detail,
    )

    print("\n=== 3. the trigger never approved and never applied ===")
    touched = " ".join(client.paths)
    print(f"  paths: {client.paths}")
    check("no owner-decision call was ever made", "/owner-decision" not in touched)
    check("no apply call was ever made", "/apply" not in touched)
    check("no rollback call was ever made", "/rollback" not in touched)

    print("\n=== 4. the working tree was never touched ===")
    branch_now = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    file_now = (repo / "percent_change.py").read_text(encoding="utf-8")
    check("the repo is still on its original branch", branch_now == "main", branch_now)
    check("no repair branch was created", git(repo, "branch", "--list", "repair/*").strip() == "")
    check("the broken line is still there", BROKEN_SNIPPET.strip() in file_now)
    dirty = git(repo, "status", "--porcelain").strip()
    check("the working tree is clean afterwards", dirty == "", dirty)
    check(
        "the tracked file is byte-identical to the base commit",
        git(repo, "diff", "--stat", base, "--", "percent_change.py").strip() == "",
    )
    check(
        "the reviewer wrote no state into the repo it was auditing",
        not list(repo.glob("*.db*")),
        ", ".join(p.name for p in repo.glob("*.db*")),
    )

    print("\n=== 5. the patch really is waiting, not applied ===")
    record = server.status(outcomes[0].patch_id or "")
    check("the gate says REVIEWED", record.get("state") == "REVIEWED", str(record.get("state")))
    check("nothing was applied yet", record.get("applied_commit") is None)
    check("no owner approval exists yet", record.get("approval") is None)
    print(f"  patch_id: {outcomes[0].patch_id}")

    print("\n=== 6. the owner completes the loop: real approval, real apply commit ===")
    # A different caller entirely. Sections 2-5 proved the trigger stops at
    # REVIEWED; the approval and the write belong to the owner, and the trigger
    # could not have made these calls even if it wanted to — GateClient has no
    # approve and no apply method, which is how the restriction is enforced.
    trigger_paths = list(client.paths)
    patch_id = outcomes[0].patch_id or ""

    owner = server.owner_decision(patch_id, "surendra")
    print(f"  owner receipt : {owner['receipt']['outcome']} {owner['receipt']['detail']}")
    check("owner approval accepted", owner["receipt"]["outcome"] == "ACCEPTED")

    applied = server.apply(patch_id)
    head = git(repo, "rev-parse", "HEAD")
    check("apply accepted", applied["receipt"]["outcome"] == "ACCEPTED", applied["receipt"]["detail"])
    check(
        "the receipt names a commit that really exists",
        applied["receipt"]["evidence"].get("applied_commit") == head,
        f"receipt={applied['receipt']['evidence'].get('applied_commit')} head={head}",
    )
    check(
        "the repo is on the repair branch",
        git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "repair/percent-change",
    )
    check(
        "the applied file really contains the fix",
        "percent_change(old, new):.2f" in (repo / "percent_change.py").read_text(encoding="utf-8"),
    )

    proc = subprocess.run(
        test_cmd,
        cwd=repo,
        shell=True,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, **good.env},
    )
    print("    " + proc.stdout.strip().replace("\n", "\n    ")[:300])
    check("the applied patch makes the real test pass", proc.returncode == 0, f"exit={proc.returncode}")

    rolled = server.rollback(patch_id)
    proc2 = subprocess.run(
        test_cmd,
        cwd=repo,
        shell=True,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, **good.env},
    )
    check("rollback accepted", rolled["receipt"]["outcome"] == "ACCEPTED", rolled["receipt"]["detail"])
    check(
        "the original broken line is back after rollback",
        BROKEN_SNIPPET.strip() in (repo / "percent_change.py").read_text(encoding="utf-8"),
    )
    check("the test fails again after rollback", proc2.returncode != 0, f"exit={proc2.returncode}")
    check(
        "the trigger itself still never called approve or apply",
        list(client.paths) == trigger_paths,
        ", ".join(client.paths),
    )

    print("\n=== summary ===")
    print(f"  failures : {len(failures)}")
    for name in failures:
        print(f"    FAILED: {name}")

    server.stop()
    shutil.rmtree(repo.parent, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
