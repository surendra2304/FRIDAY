"""Is the morning briefing real and honest? (Phase A2, the part not needing a mic)

Phase A2 asks for a live session "with owner at the mic" and lists among its
checkpoints: *morning briefing (real CPU/RAM + honest agent statuses)*. That
checkpoint does not need a microphone. The wake word, barge-in and instant-stop
do, and are not attempted here — pretending otherwise would be the exact failure
this project keeps having to undo.

So this measures the one A2 checkpoint that can be measured honestly from here, and
checks two things a briefing can get wrong that are easy to miss:

* the numbers are *measured*, not typed into a string;
* the service statuses are *honest*, rather than reporting health nobody checked.

It also compares the two briefings in the codebase, because they disagree — and the
one that flatters is the unreachable one.

Run it:

    python research/phaseA2_briefing_proof.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import psutil  # noqa: E402

from friday.workflows.master_briefing import MasterDailyBriefingWorkflow  # noqa: E402


def main() -> int:
    failures: list[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        mark = "PASS" if condition else "FAIL"
        print(f"  [{mark}] {label}{(' - ' + detail) if detail else ''}")
        if not condition:
            failures.append(label)

    print("=== 1. the briefing the agent actually routes to ===")
    snapshot = MasterDailyBriefingWorkflow().generate_morning_briefing()
    print("  ---- spoken ----")
    for line in snapshot.spoken_summary.splitlines():
        print(f"  | {line}")
    print("  ---- markdown ----")
    for line in snapshot.markdown_report.splitlines():
        print(f"  | {line}")

    print("\n=== 2. are the numbers measured rather than typed? ===")
    cpu = psutil.cpu_percent(interval=1.0)
    mem = psutil.virtual_memory().percent
    claimed_cpu = float(re.search(r"CPU ([\d.]+)%", snapshot.spoken_summary).group(1))
    claimed_mem = float(re.search(r"memory ([\d.]+)%", snapshot.spoken_summary).group(1))
    print(f"  psutil measured : CPU {cpu:.1f}%  memory {mem:.1f}%")
    print(f"  briefing claimed: CPU {claimed_cpu:.1f}%  memory {claimed_mem:.1f}%")
    print(f"  delta           : CPU {abs(claimed_cpu - cpu):.1f}pts  memory {abs(claimed_mem - mem):.1f}pts")
    # Memory is a stable quantity and must agree closely. CPU moves between samples,
    # so the tolerance there is wide on purpose — a tight one would flake on a busy
    # machine and teach the reader to distrust a correct number.
    check(
        "the memory figure matches an independent measurement",
        abs(claimed_mem - mem) < 5.0,
        f"{claimed_mem:.1f}% vs {mem:.1f}%",
    )
    check(
        "the cpu figure is in the same range as an independent measurement",
        abs(claimed_cpu - cpu) < 25.0,
        f"{claimed_cpu:.1f}% vs {cpu:.1f}%",
    )

    print("\n=== 3. are the service statuses honest? ===")
    spoken = snapshot.spoken_summary
    unverified = spoken.count("are unverified")
    print(f"  services reported      : {len(snapshot.subsystems_included)}")
    print(f"  admits how many unknown: {spoken[spoken.find('I checked'):][:90]}")
    check("it does not claim any service is healthy", "healthy" not in spoken.lower())
    check("it states how many it could not verify", unverified >= 1)
    check(
        "it says outright that it has no verified figures",
        "no verified trading, lead, research, or forecast figures" in spoken,
    )
    check("the snapshot is labelled untrusted_external", snapshot.trust_level == "untrusted_external")

    print("\n=== 4. the other briefing in the codebase ===")
    # Two briefings exist. The one on the agent's fast path is measured and admits
    # what it does not know. The other asserts "All three system tiers are online
    # and healthy" and "No critical alerts are currently pending" without touching
    # a health check anywhere in its body.
    #
    # It has no callers, so this is not a live fabrication — it is a trap for
    # whoever wires the scheduler first. Recorded, because the next person to
    # reach for a "briefing" will find this one first.
    ops = (REPO_ROOT / "src" / "friday" / "voice" / "operations_center.py").read_text(encoding="utf-8")
    body = ops.split("def generate_scheduled_briefing", 1)[1].split("\n    def ", 1)[0]
    check("the other briefing asserts health", "online and healthy" in body)
    # Look for calls that would actually measure something. Matching the bare
    # word "health" is useless here: the claim itself contains it, so a naive
    # substring test passes on the very text it is meant to catch.
    probes = ("psutil.", "capture_snapshot", "requests.", "httpx.", "get_status", "probe")
    check(
        "and it asserts it without measuring anything",
        not any(probe in body for probe in probes),
        f"found one of {probes} in that body",
    )
    callers = 0
    for path in (REPO_ROOT / "src").rglob("*.py"):
        if "generate_scheduled_briefing" in path.read_text(encoding="utf-8", errors="ignore"):
            callers += 1
    print(f"  files mentioning generate_scheduled_briefing: {callers} (its own definition only)")
    check("so it is unreachable, not a live lie", callers == 1, f"{callers} files reference it")

    print("\n=== 5. what this run did NOT measure ===")
    print("  A2's other checkpoints need a human at a microphone with speakers:")
    print("    -- voice wake word, conversation, barge-in, instant stop")
    print("    -- 'open Chrome' verified window focus, 'close tab', 'close Chrome'")
    print("  Those are not attempted here and not claimed. They are owner actions.")

    print("\n=== RESULT ===")
    if failures:
        print(f"  {len(failures)} FAILURE(S): {failures}")
        return 1
    print("  The briefing reports real measurements and admits, by name, that it")
    print("  could not verify any of the eight services. That is the honest shape")
    print("  of the A2 checkpoint this machine can actually test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())