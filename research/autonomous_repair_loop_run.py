"""Does the unattended repair loop actually fire? (Phase F2 operational proof)

``research/repair_trigger_run.py`` proves the trigger works when a driver calls
it. It says so itself, in its own docstring: *"The trigger is invoked directly by
this script; nothing yet schedules it in the running service."* That gap is now
closed by ``friday.autonomous.repair_loop``, and this driver is the proof of the
other half - that the thing the service schedules can do the real work when it is
configured the way a deployment configures it.

So this driver does not build the loop by hand and hand it a trigger. It starts a
real gate in its own OS process, writes a real watchlist to disk, sets the real
environment variables the loop reads, and calls the loop the way the service
calls it. If the env contract and the loop disagree, this fails.

What the transcript below is, stated before you read it:

REAL - a real git repository on disk with a real failing test, a real branch, a
real ``pytest`` run in a real subprocess by the real Forge proposer, a real
Sentinel review signed with a real HMAC, a real HTTP gate in its own process, and
a real 401 from the production control-access guard.

LOCAL, NOT LIVE - the gate is a process on this machine on a random port, not a
deployed Render instance. The review and control keys are literals handed to the
gate by the harness, not deployment secrets. Nothing here has touched a deployed
service.

What this is NOT - this does not claim the deployed loop has ever fired. On
Render the loop reports ``NOT_CONFIGURED`` and names the four keys it is missing,
because they are unset. Turning it on there is an owner action, listed in the
Phase F3 checklist.

Run it:

    python research/autonomous_repair_loop_run.py
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

UNIVERSE_ROOT = REPO_ROOT.parent

from self_repair_loop import (  # noqa: E402
    BROKEN_SNIPPET,
    CONTROL_KEY,
    FIXED_SNIPPET,
    SHARED_KEY,
    GateServer,
    build_broken_repo,
    git,
)

from friday.autonomous.repair_loop import LoopConfig, AutonomousRepairLoop  # noqa: E402


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
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "test_percent_change.py", "-q"],
        cwd=repo, capture_output=True, text=True, timeout=180,
    )
    print(f"  the test really fails: exit={proc.returncode}")
    check("the repository starts genuinely broken", proc.returncode != 0)

    print("\n=== 1. the gate runs as a separate real HTTP process ===")
    server = GateServer(repo)
    server.start()
    server.wait_until_serving()
    print(f"  pid  : {server.proc.pid if server.proc else -1}")
    print(f"  url  : {server.base_url}")
    check("gate is serving real HTTP", server.proc is not None and server.proc.poll() is None)

    print("\n=== 2. a watchlist on disk, and the real env vars the loop reads ===")
    workspace = Path(tempfile.mkdtemp(prefix="f2-watchlist-"))
    watchlist = workspace / "watchlist.json"
    test_cmd = f'"{sys.executable}" -m pytest test_percent_change.py -q'
    watchlist.write_text(
        json.dumps(
            [
                {
                    "name": "describe-double-scales",
                    "repo_path": str(repo),
                    "base_commit": base,
                    "branch": "repair/percent-change",
                    "target_file": "percent_change.py",
                    "original_snippet": BROKEN_SNIPPET,
                    "replacement_snippet": FIXED_SNIPPET,
                    "rationale": "describe multiplies by 100 again; percent_change already returns a percentage",
                    "test_command": test_cmd,
                    "env": {
                        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                        "PYTEST_ADDOPTS": "-p no:cacheprovider",
                    },
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  watchlist : {watchlist}")

    # Set exactly the keys LoopConfig.from_env reads. No private attributes, no
    # hand-built config object: if this contract drifts, this driver fails.
    os.environ["FRIDAY_SELF_REPAIR_TRIGGER_ENABLED"] = "1"
    os.environ["FRIDAY_SELF_REPAIR_WATCHLIST"] = str(watchlist)
    os.environ["FRIDAY_SELF_REPAIR_GATE_URL"] = server.base_url
    os.environ["FRIDAY_SELF_REPAIR_GATE_KEY"] = CONTROL_KEY
    # The review key is a different secret from the control key. Sentinel signs
    # with this; the gate verifies the signature against the same value it was
    # started with. Setting it to the control key makes every review REFUSED.
    os.environ["FRIDAY_SELF_REPAIR_REVIEW_KEY"] = SHARED_KEY
    os.environ["FRIDAY_UNIVERSE_ROOT"] = str(UNIVERSE_ROOT)
    os.environ["FRIDAY_SELF_REPAIR_REVIEWER_STATE"] = str(workspace / "reviewer-state")

    loop = AutonomousRepairLoop(LoopConfig.from_env())
    check("the loop reports itself configured", loop.status()["missing"] == [], str(loop.status()["missing"]))

    print("\n=== 3. the loop runs unattended, with no owner present ===")
    result = await loop.run_once()
    print(f"  status : {result.get('status')}")
    print(f"  detail : {result.get('detail')}")
    for outcome in result.get("outcomes", []):
        print(f"    - {outcome['spec']}: proposed={outcome['proposed']} "
              f"patch={outcome['patch_id']} test_proved={outcome['test_proved']} "
              f"review={outcome['review_outcome']} sig={outcome['signature_verified']} "
              f"waiting_on_owner={outcome['waiting_on_owner']}")

    outcomes = result.get("outcomes", [])
    check("the pass completed", result.get("status") == "COMPLETED", str(result.get("status")))
    check("it reached exactly one spec", len(outcomes) == 1, str(len(outcomes)))
    if outcomes:
        o = outcomes[0]
        check("the proposer really ran the test", o["proposed"] is True, o["proposal_detail"][:80])
        check("the fix was proved by a real test run", o["test_proved"] is True)
        check("a patch id was filed at the gate", bool(o["patch_id"]), str(o["patch_id"]))
        check("Sentinel's signature verified", o["signature_verified"] is True)
        check("it stopped at the owner gate", o["waiting_on_owner"] is True)
        check("it never reached an apply", not o.get("applied"), "this trigger has no apply")
    check("no spec lost its result to a failure", not any(o["call_failed"] for o in outcomes))

    print("\n=== 4. it never wrote anything ===")
    tracked = git(repo, "status", "--porcelain")
    print(f"  working tree: {tracked!r}")
    check("the repository under repair is untouched", tracked == "", tracked)
    check("no sentinel.db landed inside the repo", not (repo / "sentinel.db").exists())
    check("reviewer state went outside the repo", (workspace / "reviewer-state").exists())

    print("\n=== 5. the gate refused an unauthenticated caller ===")
    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        anon = await client.post(
            f"{server.base_url}/api/self-repair/proposals",
            json={"branch": "x", "base_commit": "y", "target_file": "z",
                  "original_snippet": "a", "replacement_snippet": "b", "rationale": "c"},
        )
        bad = await client.post(
            f"{server.base_url}/api/self-repair/proposals",
            headers={"x-friday-api-key": "not-the-key"},
            json={"branch": "x", "base_commit": "y", "target_file": "z",
                  "original_snippet": "a", "replacement_snippet": "b", "rationale": "c"},
        )
    print(f"  no key   -> {anon.status_code}")
    print(f"  bad key  -> {bad.status_code}")
    check("the control guard is real, not bypassed", anon.status_code == 401 and bad.status_code == 401)

    print("\n=== 6. what the loop now reports about itself ===")
    snapshot = loop.status()
    print(f"  status={snapshot['status']} specs={snapshot['specs']} "
          f"waiting_on_owner={snapshot['waiting_on_owner']}")
    check("the last run is retained, not reset", snapshot["last_completed_at"] is not None)
    check("its outcome is retained", snapshot["specs"] == 1, str(snapshot["specs"]))

    server.stop()

    print("\n=== RESULT ===")
    if failures:
        print(f"  {len(failures)} FAILURE(S): {failures}")
        return 1
    print("  All checks passed. The unattended loop fired a real repair, proved it")
    print("  with a real test run, got a real signature verified, and stopped at")
    print("  the owner gate without writing to the repository.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))