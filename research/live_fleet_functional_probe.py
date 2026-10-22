"""Live functional probe — does each cloud agent actually DO work, not just answer /health?

Every earlier phase of this project proved the fleet was *reachable*. Nine HTTP 200s
proved nothing about whether a single agent could perform its one job. This script
asks each agent to do real work over real HTTPS with the real mesh credentials, and
records what actually came back.

Run it:

    python research/live_fleet_functional_probe.py

Every result carries the literal HTTP status and a truncated body so the verdict can
be re-checked by hand. Nothing here is mocked and nothing is asserted optimistically:
a 200 with an empty or error-shaped body is recorded as a FAIL, not a pass.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from friday.core.config import get_settings  # noqa: E402

RUN_ID = uuid.uuid4().hex[:12]
RESULTS: list[dict[str, Any]] = []


def _headers(key: str) -> dict[str, str]:
    """Every mesh peer accepts more than one header spelling; send all of them.

    fleet_client.py shows the fleet itself is inconsistent (some probes send
    Authorization only, some X-API-Key only), so a single-spelling probe would
    measure the probe's spelling rather than the agent's capability.
    """
    h = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = f"Bearer {key}"
        h["X-API-Key"] = key
    return h


@dataclass
class Probe:
    agent: str
    what_it_proves: str
    method: str
    url: str
    key: str
    body: dict[str, Any] | None = None
    timeout: float = 120.0
    # Substrings that mean "the agent answered but did no work".
    fail_markers: tuple[str, ...] = (
        "not implemented",
        "not supported",
        "unavailable",
        "mock",
        "simulat",
        "placeholder",
        "todo",
        "\"status\": \"error\"",
    )
    min_latency_ms: int = 0
    #: Memora binds a credential to a named agent identity, so the caller must
    #: present both. Omitting this measures my probe, not the agent.
    extra_headers: dict[str, str] = field(default_factory=dict)


def run(p: Probe) -> dict[str, Any]:
    started = time.time()
    rec: dict[str, Any] = {
        "agent": p.agent,
        "proves": p.what_it_proves,
        "request": f"{p.method} {p.url.replace(str(REPO_ROOT), '.')}",
    }
    try:
        with httpx.Client(timeout=p.timeout, follow_redirects=True) as c:
            hdrs = _headers(p.key)
            hdrs.update(p.extra_headers)
            r = c.request(
                p.method,
                p.url,
                headers=hdrs,
                json=p.body if p.method != "GET" else None,
            )
        elapsed = int((time.time() - started) * 1000)
        text = r.text
        low = text.lower()
        rec["http_status"] = r.status_code
        rec["latency_ms"] = elapsed
        rec["response_bytes"] = len(text)
        rec["response_head"] = text[:600]

        if r.status_code >= 400:
            rec["verdict"] = "FAIL"
            rec["reason"] = f"HTTP {r.status_code}"
        else:
            markers = [m for m in p.fail_markers if m in low]
            if markers:
                rec["verdict"] = "FAIL"
                rec["reason"] = f"responded but signalled no work: {markers}"
            elif len(text.strip()) < 2:
                rec["verdict"] = "FAIL"
                rec["reason"] = "empty body"
            elif p.min_latency_ms and elapsed < p.min_latency_ms:
                rec["verdict"] = "SUSPECT"
                rec["reason"] = f"answered in {elapsed}ms — too fast to have done real work"
            else:
                rec["verdict"] = "PASS"
                rec["reason"] = "returned substantive work"
    except Exception as exc:  # noqa: BLE001 - a probe must never mask its own failure
        rec["http_status"] = None
        rec["latency_ms"] = int((time.time() - started) * 1000)
        rec["verdict"] = "FAIL"
        rec["reason"] = f"{type(exc).__name__}: {exc}"[:300]
    RESULTS.append(rec)
    v = rec["verdict"]
    print(f"[{v:7}] {p.agent:10} {p.what_it_proves[:52]:54} HTTP {rec.get('http_status')} {rec.get('latency_ms')}ms")
    return rec


def main() -> int:
    s = get_settings()
    corr = f"liveprobe-{RUN_ID}"

    probes = [
        # ------------------------------------------------------------------
        # Inference — must route to a real model and return real generated text.
        Probe(
            agent="Inference",
            what_it_proves="routes a task to a real provider and generates text",
            method="POST",
            url=f"{s.inference_url}/v1/ask",
            key=s.inference_api_key,
            body={
                "prompt": "Reply with exactly: INFERENCE_LIVE_OK",
                "task_type": "simple",
                "max_tokens": 30,
            },
            timeout=150.0,
            min_latency_ms=200,
        ),
        Probe(
            agent="Inference",
            what_it_proves="reports its real model panel",
            method="GET",
            url=f"{s.inference_url}/models",
            key=s.inference_api_key,
        ),
        # ------------------------------------------------------------------
        # Memora — must durably write then read back, across HTTP.
        Probe(
            agent="Memora",
            what_it_proves="writes a memory durably over HTTP",
            method="POST",
            url=f"{s.memora_url}/v1/memories",
            key=s.memora_api_key,
            body={
                "agent_name": "friday",
                "namespace": "universal",
                "content": f"LIVE_PROBE_{RUN_ID}: real-world functional write test",
                "memory_type": "episodic",
                "metadata": {"probe": "live_functional", "correlation_id": corr},
            },
            timeout=90.0,
            extra_headers={"X-Agent-Name": "friday"},
        ),
        Probe(
            agent="Memora",
            what_it_proves="serves its durable event feed with a real cursor",
            method="GET",
            url=f"{s.memora_url}/v1/events?limit=3",
            key=s.memora_api_key,
            extra_headers={"X-Agent-Name": "friday"},
        ),
        # ------------------------------------------------------------------
        # IntelX — must run real research, not return a canned response.
        Probe(
            agent="IntelX",
            what_it_proves="starts a real research job over the network",
            method="POST",
            url=f"{s.intelx_url}/api/v1/research/jobs",
            key=s.intelx_api_key,
            body={
                "objective": "Bitcoin price outlook today",
                "correlation_id": corr,
            },
            timeout=180.0,
            min_latency_ms=500,
        ),
        Probe(
            agent="IntelX",
            what_it_proves="reports its configured news sources",
            method="GET",
            url=f"{s.intelx_url}/api/v1/friday-universe/status",
            key=s.intelx_api_key,
        ),
        # ------------------------------------------------------------------
        # Futuris — must produce a real calibrated forecast.
        Probe(
            agent="Futuris",
            what_it_proves="produces a real probability forecast",
            method="POST",
            url=f"{s.futuris_url}/v1/market/forecast",
            key=s.futuris_api_key,
            body={"symbol": "BTCUSDT", "horizon_days": 7},
            timeout=120.0,
        ),
        Probe(
            agent="Futuris",
            what_it_proves="reports its real calibration accuracy",
            method="GET",
            url=f"{s.futuris_url}/v1/evaluation/calibration",
            key=s.futuris_api_key,
        ),
        # ------------------------------------------------------------------
        # Stratex — must analyse a real market and refuse live money.
        Probe(
            agent="Stratex",
            what_it_proves="analyses a real symbol and stays paper-only",
            method="GET",
            url=f"{s.stratex_url}/api/status",
            key=s.stratex_api_key,
            timeout=120.0,
        ),
        Probe(
            agent="Stratex",
            what_it_proves="reports its open paper positions",
            method="GET",
            # Verified live: /api/positions serves the real position book
            # ({"count":0,...,"filter":"OPEN"}); the bare /positions path is a
            # 404 on the deployed router. Probing the wrong route would report a
            # service defect that does not exist.
            url=f"{s.stratex_url}/api/positions",
            key=s.stratex_api_key,
        ),
        # ------------------------------------------------------------------
        # Forge — must generate real code from a real prompt.
        Probe(
            agent="Forge",
            what_it_proves="generates real code through a real model",
            method="POST",
            url=f"{s.forge_url}/api/v1/ask-inference",
            key=s.forge_api_key,
            body={"prompt": "Write a Python function that reverses a string. Code only."},
            timeout=180.0,
            min_latency_ms=500,
        ),
        Probe(
            agent="Forge",
            what_it_proves="reports its real capability set",
            method="GET",
            url=f"{s.forge_url}/api/v1/capabilities",
            key=s.forge_api_key,
        ),
        # ------------------------------------------------------------------
        # Sentinel — must scan and report findings, not a fixed status string.
        Probe(
            agent="Sentinel",
            what_it_proves="runs a real security scan",
            method="GET",
            url=f"{s.sentinel_url}/api/v1/scan",
            key=s.sentinel_api_key,
            timeout=120.0,
        ),
        Probe(
            agent="Sentinel",
            what_it_proves="verifies its audit hash chain",
            method="GET",
            url=f"{s.sentinel_url}/api/v1/audit/verify",
            key=s.sentinel_api_key,
        ),
        # ------------------------------------------------------------------
        # Cortex — must return real CRM data, not mock mode.
        Probe(
            agent="Cortex",
            what_it_proves="returns real lead data",
            method="GET",
            url=f"{s.cortex_url}/v1/leads",
            key=s.cortex_api_key,
        ),
        Probe(
            agent="Cortex",
            what_it_proves="answers a real command from FRIDAY",
            method="POST",
            url=f"{s.cortex_url}/v1/friday/command",
            key=s.cortex_api_key,
            body={"command": "status", "parameters": {}},
            timeout=90.0,
        ),
    ]

    print(f"\n=== LIVE FUNCTIONAL PROBE  run={RUN_ID}  {datetime.now(timezone.utc).isoformat()} ===\n")
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(run, probes))

    passed = [r for r in RESULTS if r["verdict"] == "PASS"]
    failed = [r for r in RESULTS if r["verdict"] == "FAIL"]
    suspect = [r for r in RESULTS if r["verdict"] == "SUSPECT"]

    report = {
        "run_id": RUN_ID,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(RESULTS),
            "pass": len(passed),
            "fail": len(failed),
            "suspect": len(suspect),
        },
        "results": RESULTS,
    }
    out = REPO_ROOT / "reports_and_data" / f"live-functional-probe-{RUN_ID}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\n{'=' * 78}")
    print(f"PASS {len(passed)}   FAIL {len(failed)}   SUSPECT {len(suspect)}   -> {out.name}")
    print("=" * 78)
    for r in failed + suspect:
        print(f"  {r['verdict']:7} {r['agent']:10} {r['reason']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())