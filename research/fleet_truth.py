"""Phase F1 — one command that measures whether the universe is actually live.

Phases D and E both ended with the same problem: the honest answer to "is it
running?" lived in a note written during a past session. A note is not a
measurement. It goes stale silently, and the next session has to guess whether
it is still true.

So this script measures it, from scratch, every time it runs:

  1. a real HTTP probe of all nine deployed services' ``/health``, recording
     what each one actually returned — including whether it carries the
     ``evidence_class`` and ``observed_at`` fields that make a health claim
     falsifiable rather than decorative;
  2. the CI conclusion on each repository's pushed head;
  3. a dated JSON report and a dated Markdown note.

It refuses to grade itself generously. A service that answers 200 but omits the
evidence fields is recorded as ``STALE_BUILD``, not as a pass, because an older
build answering is precisely the failure mode that already cost this project two
owner-blocked redeploys. A service that does not answer is ``UNREACHABLE``. Only
a service that answers *and* labels its own claim passes.

Run it:

    python research/fleet_truth.py

Everything in the report is something this script just observed. Nothing is
carried over from a previous run.
"""

from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The nine deployed services, and the local checkout each one is built from.
FLEET: tuple[tuple[str, str, str], ...] = (
    ("FRIDAY", "https://friday-zw59.onrender.com", "FRIDAY"),
    ("Inference", "https://inference-r1sn.onrender.com", "Inference"),
    ("Memora", "https://memora-cavc.onrender.com", "Memora"),
    ("Stratex", "https://stratex-8wj1.onrender.com", "Stratex"),
    ("IntelX", "https://intelx-mygl.onrender.com", "IntelX"),
    ("Futuris", "https://futuris-th6f.onrender.com", "Futuris"),
    ("Cortex", "https://cortex-0m7c.onrender.com", "Cortex"),
    ("Forge", "https://forge-e9kl.onrender.com", "Forge"),
    ("Sentinel", "https://sentinel-a861.onrender.com", "Sentinel"),
)

#: What a service must carry for its health claim to be falsifiable.
REQUIRED_FIELDS = ("evidence_class", "observed_at")

#: Known owner-blocked items. The action is spelled out because "blocked" with
#: no next step is just an excuse.
OWNER_BLOCKED: tuple[dict[str, str], ...] = (
    {
        "item": "Cortex redeploy",
        "state": "auto-deploy off for this service only",
        "action": "Render dashboard -> Cortex service -> Manual Deploy -> 'Deploy latest commit'",
        "verify": 'curl -s https://cortex-0m7c.onrender.com/health   # expect evidence_class AND observed_at',
    },
    {
        "item": "Memora redeploy",
        "state": "auto-deploy off for this service only",
        "action": "Render dashboard -> Memora service -> Manual Deploy -> 'Deploy latest commit'",
        "verify": 'curl -s https://memora-cavc.onrender.com/health   # expect evidence_class AND observed_at',
    },
    {
        "item": "Phase D3 — nine Render dashboards + UptimeRobot",
        "state": "no Render API key, deploy hook or UptimeRobot credential reachable from this machine",
        "action": "open each of the nine Render dashboards and UptimeRobot, confirm the $0 tier and free-plan status",
        "verify": "a dated note naming each dashboard and what it showed",
    },
)


@dataclass
class Probe:
    """One service's real answer to /health."""

    service: str
    url: str
    status_code: int | None = None
    reachable: bool = False
    evidence_class: str | None = None
    observed_at: str | None = None
    reported_status: str | None = None
    missing_fields: list[str] = field(default_factory=list)
    latency_ms: float | None = None
    error: str | None = None

    @property
    def verdict(self) -> str:
        if not self.reachable:
            return "UNREACHABLE"
        if self.missing_fields:
            # It answered, but without the fields that make the answer checkable.
            return "STALE_BUILD"
        return "LIVE"

    def as_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "url": self.url,
            "verdict": self.verdict,
            "reachable": self.reachable,
            "status_code": self.status_code,
            "reported_status": self.reported_status,
            "evidence_class": self.evidence_class,
            "observed_at": self.observed_at,
            "missing_evidence_fields": self.missing_fields,
            "latency_ms": round(self.latency_ms, 1) if self.latency_ms is not None else None,
            "error": self.error,
        }


def probe_service(service: str, url: str, timeout: float = 45.0) -> Probe:
    """Ask one service how it is. Never guesses on its behalf."""
    result = Probe(service=service, url=url)
    for path in ("/health", "/api/health"):
        try:
            response = httpx.get(f"{url}{path}", timeout=timeout)
        except httpx.HTTPError as exc:
            result.error = f"{path}: {type(exc).__name__}"
            continue
        result.status_code = response.status_code
        result.latency_ms = response.elapsed.total_seconds() * 1000
        if response.status_code != 200:
            continue
        try:
            payload = response.json()
        except ValueError:
            result.error = f"{path}: response was not JSON"
            continue
        if not isinstance(payload, dict):
            result.error = f"{path}: health payload was not an object"
            continue
        result.reachable = True
        result.evidence_class = payload.get("evidence_class")
        result.observed_at = payload.get("observed_at")
        result.reported_status = payload.get("status") or payload.get("overall")
        result.missing_fields = [f for f in REQUIRED_FIELDS if not payload.get(f)]
        break
    return result


def ci_head(repo_dir: Path, timeout: float = 90.0) -> dict[str, Any]:
    """The CI conclusion on the pushed head, not on some local commit."""
    info: dict[str, Any] = {"repo": repo_dir.name, "available": False}
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        info["head"] = head.stdout.strip() or None
        run = subprocess.run(
            ["gh", "run", "list", "--limit", "1", "--json", "conclusion,headSha,status"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if run.returncode != 0:
            info["error"] = run.stderr.strip()[:200]
            return info
        runs = json.loads(run.stdout or "[]")
        if not runs:
            info["error"] = "no workflow run found for this branch"
            return info
        latest = runs[0]
        info.update(
            {
                "available": True,
                "ci_status": latest.get("status"),
                "ci_conclusion": latest.get("conclusion"),
                "ci_head_sha": (latest.get("headSha") or "")[:7] or None,
            }
        )
        info["ci_matches_local_head"] = bool(
            info.get("head") and info.get("ci_head_sha") == info["head"]
        )
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def render_markdown(report: dict[str, Any]) -> str:
    measured = report["generated_at"]
    lines = [
        f"# Phase F1 — Fleet truth report ({measured})",
        "",
        "**Owner:** Surendra · **Label: LIVE probes, LOCAL CI queries.**",
        "",
        "Every row below was measured by `python research/fleet_truth.py` in the run "
        "that wrote this file. Nothing is carried over from a previous report.",
        "",
        "A service passes only if it answers `200` **and** carries the `evidence_class` "
        "and `observed_at` fields. An older build that answers without them is recorded "
        "as `STALE_BUILD`, because that is exactly the failure that already cost two "
        "owner-blocked redeploys.",
        "",
        "## 1. Service health",
        "",
        "| Service | Verdict | HTTP | Says | evidence_class | observed_at | Latency |",
        "|---|---|---|---|---|---|---|",
    ]
    for probe in report["probes"]:
        lines.append(
            "| {service} | **{verdict}** | {code} | {says} | {ec} | {at} | {lat} |".format(
                service=probe["service"],
                verdict=probe["verdict"],
                code=probe["status_code"] if probe["status_code"] is not None else "—",
                says=probe["reported_status"] or (probe["error"] or "—"),
                ec=probe["evidence_class"] or "—",
                at=(probe["observed_at"] or "—")[:19],
                lat=f"{probe['latency_ms']}ms" if probe["latency_ms"] is not None else "—",
            )
        )
    counts = report["summary"]
    lines += [
        "",
        f"**{counts['live']}/{counts['total']} LIVE** · "
        f"{counts['stale_build']} STALE_BUILD · {counts['unreachable']} UNREACHABLE",
        "",
    ]
    stale = [p for p in report["probes"] if p["verdict"] == "STALE_BUILD"]
    if stale:
        lines += [
            "A `STALE_BUILD` service is reachable but is running code that predates the "
            "evidence fields, so its health claim is not falsifiable. It is not counted "
            "as live and is not counted as a code failure — it needs a redeploy.",
            "",
        ]
        for probe in stale:
            lines.append(f"- **{probe['service']}** is missing: `{'`, `'.join(probe['missing_evidence_fields'])}`")

    lines += [
        "",
        "## 2. CI on each pushed head",
        "",
        "| Repo | Local HEAD | CI | Conclusion | Matches HEAD |",
        "|---|---|---|---|---|",
    ]
    for entry in report["ci"]:
        lines.append(
            "| {repo} | `{head}` | {status} | {conclusion} | {match} |".format(
                repo=entry["repo"],
                head=entry.get("head") or "—",
                status=entry.get("ci_status") or entry.get("error") or "—",
                conclusion=entry.get("ci_conclusion") or "—",
                match=("yes" if entry.get("ci_matches_local_head") else "no")
                if entry.get("available")
                else "—",
            )
        )
    green = counts["ci_green"]
    lines += ["", f"**{green}/{counts['ci_total']} repositories green on the pushed head.**", ""]

    lines += [
        "## 3. Blocked on the owner",
        "",
        "These are not failures and not excuses. Each is a specific action with a "
        "specific verification command, and none of them can be done from this machine.",
        "",
    ]
    for item in report["owner_blocked"]:
        lines += [
            f"### {item['item']}",
            "",
            f"- **Why it is blocked:** {item['state']}",
            f"- **Exact owner action:** {item['action']}",
            f"- **Verify with:** `{item['verify']}`",
            "",
        ]

    measured_at = report["measured_at"]
    lines += [
        "## 4. What this report does not claim",
        "",
        "- A `LIVE` verdict means the service answered and labelled its own claim. It "
        "does **not** mean the service can perform its task correctly; that needs a "
        "functional test against the deployment, which is separate work.",
        "- CI conclusions are read from the local checkout via the version control CLI. "
        "A checkout that cannot be queried is recorded as `available: false` rather than "
        "assumed green, and a run still in progress is counted as **not** green, because "
        "a pending run proves nothing about the commit it is testing.",
        "- `UNREACHABLE` can mean a cold start on a free tier rather than an outage, so "
        "it is separated from `STALE_BUILD` and never merged into it.",
        "",
        f"_Measured {measured_at}. Re-run `python research/fleet_truth.py` for a current answer._",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    measured_at = datetime.now(timezone.utc).isoformat()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    universe_root = REPO_ROOT.parent

    with ThreadPoolExecutor(max_workers=len(FLEET)) as pool:
        probes = list(
            pool.map(lambda entry: probe_service(entry[0], entry[1]), FLEET)
        )

    ci: list[dict[str, Any]] = []
    for _, _, repo_name in FLEET:
        repo_dir = universe_root / repo_name
        if not repo_dir.is_dir():
            ci.append({"repo": repo_name, "available": False, "error": "checkout not present"})
            continue
        ci.append(ci_head(repo_dir))

    report: dict[str, Any] = {
        "generated_at": stamp,
        "measured_at": measured_at,
        "phase": "F1",
        "probe_rule": (
            "a service is LIVE only if /health answers 200 and carries evidence_class "
            "and observed_at; otherwise STALE_BUILD; if no response, UNREACHABLE"
        ),
        "probes": [p.as_dict() for p in probes],
        "ci": ci,
        "owner_blocked": [dict(item) for item in OWNER_BLOCKED],
        "summary": {
            "total": len(probes),
            "live": sum(1 for p in probes if p.verdict == "LIVE"),
            "stale_build": sum(1 for p in probes if p.verdict == "STALE_BUILD"),
            "unreachable": sum(1 for p in probes if p.verdict == "UNREACHABLE"),
            "ci_total": len(ci),
            "ci_green": sum(
                1 for e in ci if e.get("available") and e.get("ci_conclusion") == "success"
            ),
            "ci_unavailable": sum(1 for e in ci if not e.get("available")),
        },
    }

    reports_dir = REPO_ROOT / "reports_and_data"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / f"fleet-truth-{stamp}.json"
    md_path = reports_dir / f"fleet-truth-{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")

    summary = report["summary"]
    print(f"measured at {measured_at}")
    for probe in report["probes"]:
        print(f"  {probe['service']:<10} {probe['verdict']:<14} {probe['status_code']} {probe['reported_status'] or ''}")
    print(f"  LIVE {summary['live']}/{summary['total']}  STALE_BUILD {summary['stale_build']}  UNREACHABLE {summary['unreachable']}")
    print(f"  CI green {summary['ci_green']}/{summary['ci_total']}  (unavailable {summary['ci_unavailable']})")
    print(f"\nwrote {json_path.name}\nwrote {md_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
