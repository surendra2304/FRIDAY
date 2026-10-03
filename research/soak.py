"""Run the fleet the way production does, and watch what happens over time.

Every previous check was a single request that finished in seconds. Nothing here
covers the behaviour that actually breaks a service: resource growth, unhandled
exceptions surfacing in background cycles, and how callers behave when a peer dies.

This drives continuous real cross-agent traffic and, on an interval, samples each
agent's resident memory and thread count from the OS and scans its log for new
tracebacks. Results append to JSONL so the run survives across invocations.

    python research/soak.py --duration 900            # detached traffic + sampling
    python research/soak.py --summary                 # analyse what was collected
    python research/soak.py --peer-down memora        # probe caller behaviour
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

FRIDAY = Path(__file__).resolve().parent.parent
LOGS = FRIDAY / "reports_and_data" / "local_fleet"
OUT = FRIDAY / "reports_and_data"

PORTS = {"friday": 8101, "inference": 8102, "memora": 8103, "stratex": 8104,
         "intelx": 8105, "futuris": 8106, "cortex": 8107, "forge": 8108, "sentinel": 8109}

# Process names as they appear in tasklist, per agent.
PROC = {"friday": "python.exe", "inference": "python.exe", "memora": "python.exe",
        "stratex": "python.exe", "intelx": "python.exe", "futuris": "python.exe",
        "cortex": "python.exe", "forge": "python.exe", "sentinel": "python.exe"}


def load_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    for line in (FRIDAY / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if "_API_KEY=" in line:
            k, _, v = line.partition("=")
            if k.strip().endswith("_API_KEY"):
                keys[k.strip()[: -len("_API_KEY")].lower()] = v.strip().strip('"').strip("'")
    return keys


KEYS = load_keys()
STOP = threading.Event()


def creds(agent="friday"):
    key = KEYS.get(agent, "")
    return {"Content-Type": "application/json", "X-Agent-Name": agent, "X-API-Key": key,
            "X-Agent-Key": key, "X-FRIDAY-API-Key": key, "Authorization": f"Bearer {key}"}


def call(agent, path, method="GET", body=None, timeout=60.0):
    url = f"http://127.0.0.1:{PORTS[agent]}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=creds(), method=method)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
        e.read()
    except socket_timeout:
        code = "TIMEOUT"
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        code = "TIMEOUT" if "timed out" in str(reason).lower() else "UNREACHABLE"
    except Exception as e:
        code = f"ERR:{type(e).__name__}"
    return code, int((time.time() - started) * 1000)


socket_timeout = TimeoutError


# Real flows, weighted toward the ones that do real work.
def flows(marker):
    return [
        ("memora", "POST", "/v1/memories",
         {"agent_name": "friday", "content_text": f"soak {marker}", "namespace": "friday", "importance": 0.4}),
        ("memora", "POST", "/v1/memories/query",
         {"agent_name": "friday", "query": "soak", "namespace": "friday", "limit": 5}),
        ("inference", "POST", "/ask", {"question": f"soak probe {marker}", "max_tokens": 24}),
        ("inference", "GET", "/health/providers", None),
        ("intelx", "POST", "/api/v1/friday/research",
         {"friday_request_id": f"soak-{uuid.uuid4().hex[:8]}",
          "query_scope": {"query": f"soak {marker}"}, "max_findings": 1}),
        ("intelx", "GET", "/api/v1/healthz", None),
        ("futuris", "POST", "/api/v1/friday/forecast",
         {"target": "BTCUSDT", "as_agent": "friday", "request_id": f"soak-{uuid.uuid4().hex[:8]}"}),
        ("futuris", "GET", "/health", None),
        ("forge", "GET", "/api/v1/capabilities", None),
        ("cortex", "POST", "/v1/friday/command",
         {"goal": f"soak {marker}", "required_capability": "status_report",
          "requested_action": "report_fleet_status"}),
        ("sentinel", "GET", "/health", None),
        ("stratex", "GET", "/api/status", None),
        ("stratex", "GET", "/api/telemetry/trades?status=CLOSED&limit=50", None),
        ("friday", "GET", "/api/agents/status", None),
        ("friday", "GET", "/api/health", None),
    ]


def traffic_worker(worker_id: int, results_path: Path):
    """One thread of continuous real traffic. Records every outcome, including slow ones."""
    while not STOP.is_set():
        agent, method, path, body = random.choice(flows(uuid.uuid4().hex[:6]))
        code, ms = call(agent, path, method, body)
        record = {"ts": time.time(), "worker": worker_id, "agent": agent, "path": path,
                  "method": method, "code": code, "ms": ms}
        with results_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        time.sleep(random.uniform(0.3, 1.2))


def sample_resources(sample_path: Path, interval: int):
    """Sample memory and threads per agent, and scan logs for new tracebacks."""
    seen_log_lines: dict[str, int] = {}
    while not STOP.is_set():
        snapshot = {"ts": time.time(), "agents": {}}
        for agent in PORTS:
            entry = {"listening": port_open(PORTS[agent])}
            rss = process_rss_for_port(PORTS[agent])
            if rss:
                entry.update(rss)
            log = LOGS / f"{agent}.log"
            if log.exists():
                try:
                    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
                except Exception:
                    lines = []
                prev = seen_log_lines.get(agent, len(lines))
                fresh = lines[prev:] if len(lines) > prev else lines
                entry["log_lines"] = len(lines)
                entry["new_lines"] = len(fresh)
                entry["new_tracebacks"] = sum(1 for l in fresh if "Traceback" in l)
                entry["new_errors"] = sum(1 for l in fresh if " ERROR " in l or "CRITICAL" in l)
                entry["new_warnings"] = sum(1 for l in fresh if "WARNING" in l)
                seen_log_lines[agent] = len(lines)
            snapshot["agents"][agent] = entry
        with sample_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(snapshot) + "\n")
        STOP.wait(interval)


def port_open(port: int) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", port)) == 0


def process_rss_for_port(port: int):
    """Find the PID listening on a port and read its working set from the OS."""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return None
    pid = None
    for line in out.splitlines():
        parts = line.split()
        if f":{port}" in parts[1] if len(parts) > 1 else False:
            if "LISTENING" in line:
                pid = parts[-1]
                break
    if not pid:
        return None
    try:
        tasklist = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                                  capture_output=True, text=True, timeout=20).stdout
        mem_kb = 0
        for line in tasklist.splitlines():
            cols = [c.strip('"') for c in line.split('","')]
            if len(cols) > 4:
                # tasklist reports memory as "12,345 K"; keep the digits only.
                digits = "".join(ch for ch in cols[-1] if ch.isdigit())
                if digits:
                    mem_kb = int(digits)
        return {"pid": pid, "rss_kb": mem_kb}
    except Exception:
        return {"pid": pid}


def soak(duration: int, workers: int):
    stamp = time.strftime("%Y%m%dT%H%M%S")
    results = OUT / f"soak-calls-{stamp}.jsonl"
    samples = OUT / f"soak-samples-{stamp}.jsonl"
    print(f"soak for {duration}s with {workers} workers -> {results.name}, {samples.name}")
    threads = [threading.Thread(target=traffic_worker, args=(i, results), daemon=True)
               for i in range(workers)]
    sampler = threading.Thread(target=sample_resources, args=(samples, 20), daemon=True)
    for t in threads:
        t.start()
    sampler.start()
    try:
        time.sleep(duration)
    except KeyboardInterrupt:
        pass
    finally:
        STOP.set()
        time.sleep(2)
    print("soak complete")


def summarize():
    calls = sorted(OUT.glob("soak-calls-*.jsonl"))
    samples = sorted(OUT.glob("soak-samples-*.jsonl"))
    if not calls:
        print("no soak data collected")
        return
    rows = []
    for f in calls:
        rows += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    snaps = []
    for f in samples:
        snaps += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]

    print(f"=== {len(rows)} calls over {len(calls)} run(s) ===")
    by_agent: dict[str, list] = {}
    for r in rows:
        by_agent.setdefault(r["agent"], []).append(r)
    print(f"{'agent':10} {'calls':>6} {'5xx':>5} {'timeout':>8} {'unreach':>7} {'p50ms':>7} {'p99ms':>7} {'maxms':>7}")
    for agent in sorted(by_agent):
        rs = by_agent[agent]
        lat = sorted(x["ms"] for x in rs)
        p50 = lat[len(lat) // 2]
        p99 = lat[min(len(lat) - 1, int(len(lat) * 0.99))]
        codes = [str(x["code"]) for x in rs]
        print(f"{agent:10} {len(rs):6} {sum(1 for c in codes if c.startswith('5')):5} "
              f"{sum(1 for c in codes if c == 'TIMEOUT'):8} {sum(1 for c in codes if c == 'UNREACHABLE'):7} "
              f"{p50:7} {p99:7} {lat[-1]:7}")

    print("\n=== resource growth (leak signal) ===")
    if snaps:
        for agent in sorted(snaps[0]["agents"]):
            series = [(s["ts"], s["agents"][agent].get("rss_kb")) for s in snaps
                      if s["agents"][agent].get("rss_kb")]
            if len(series) >= 2:
                first, last = series[0][1], series[-1][1]
                delta = last - first
                print(f"{agent:10} rss {first/1024:8.1f}MB -> {last/1024:8.1f}MB  "
                      f"delta {delta/1024:+8.1f}MB over {len(series)} samples")
            tb = sum(s["agents"][agent].get("new_tracebacks", 0) for s in snaps)
            er = sum(s["agents"][agent].get("new_errors", 0) for s in snaps)
            wr = sum(s["agents"][agent].get("new_warnings", 0) for s in snaps)
            if tb or er:
                print(f"{agent:10} log during soak: {tb} tracebacks, {er} errors, {wr} warnings")

    print("\n=== non-2xx detail ===")
    bad: dict[tuple, int] = {}
    for r in rows:
        c = str(r["code"])
        if not c.startswith("2"):
            bad[(r["agent"], r["path"], c)] = bad.get((r["agent"], r["path"], c), 0) + 1
    for (a, p, c), n in sorted(bad.items(), key=lambda kv: -kv[1])[:20]:
        print(f"  {n:5}  {a:10} {c:12} {p}")


def peer_down(peer: str):
    """Measure what a caller does when a peer is unreachable: fail fast, or hang?"""
    print(f"peer={peer} reachable={port_open(PORTS[peer])}")
    callers = [("inference", "/health/ready"), ("futuris", "/api/v1/friday/forecast"),
               ("stratex", "/api/engine-health"), ("intelx", "/api/v1/healthz")]
    for agent, path in callers:
        method = "POST" if path.endswith("forecast") else "GET"
        body = {"target": "BTCUSDT", "as_agent": "friday"} if method == "POST" else None
        code, ms = call(agent, path, method, body, timeout=120)
        verdict = "HANGS BEYOND 120s" if code == "TIMEOUT" else f"degraded in {ms}ms ({code})"
        print(f"  {agent:10} -> {verdict}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=600)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--peer-down")
    args = ap.parse_args()
    if args.summary:
        summarize()
    elif args.peer_down:
        peer_down(args.peer_down)
    else:
        soak(args.duration, args.workers)


if __name__ == "__main__":
    main()
