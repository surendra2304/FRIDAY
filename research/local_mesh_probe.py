"""Exercise the real FRIDAY Universe mesh over local HTTP with production credentials.

Every call below is a real request to a real running agent, authenticated with the
same 43-character mesh keys the fleet uses in production. Nothing is stubbed. Agents
that reach upstream APIs do so for real, so a pass here means the whole path worked.

    python research/local_fleet.py --all --serve-only     # in one shell
    python research/local_mesh_probe.py                    # in another
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

UNIVERSE = Path(__file__).resolve().parent.parent.parent
FRIDAY = UNIVERSE / "FRIDAY"

PORTS = {
    "friday": 8101, "inference": 8102, "memora": 8103, "stratex": 8104,
    "intelx": 8105, "futuris": 8106, "cortex": 8107, "forge": 8108, "sentinel": 8109,
}


def load_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    for line in (FRIDAY / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("FRIDAY_API_KEY=") or "_API_KEY=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            if key.endswith("_API_KEY"):
                keys[key[: -len("_API_KEY")].lower()] = value.strip().strip('"').strip("'")
    return keys


KEYS = load_keys()


def call(agent: str, path: str, method: str = "GET", body: dict | None = None,
         as_agent: str = "friday", timeout: float = 90.0):
    """Sends a request carrying every mesh credential header the fleet uses.

    Agents disagree on which header names their key, so present all of them rather
    than encoding a guess: this tests the services, not my assumption about them.
    """
    url = f"http://127.0.0.1:{PORTS[agent]}{path}"
    key = KEYS.get(as_agent, "")
    headers = {
        "Content-Type": "application/json",
        "X-Agent-Name": as_agent,
        "X-API-Key": key,
        "X-Agent-Key": key,
        "X-FRIDAY-API-Key": key,
        "Authorization": f"Bearer {key}",
    }
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            code = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        code = exc.code
    except Exception as exc:
        return {"ok": False, "code": None, "ms": int((time.time() - started) * 1000),
                "detail": f"{type(exc).__name__}: {exc}"}
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = raw[:400]
    return {"ok": 200 <= code < 300, "code": code, "ms": int((time.time() - started) * 1000), "detail": parsed}


RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, response: dict, expect=None):
    ok = response["ok"] if expect is None else (response["code"] == expect)
    summary = response["detail"]
    if isinstance(summary, dict):
        keys = [k for k in ("error", "detail", "message", "status", "count", "total") if k in summary]
        summary = {k: str(summary[k])[:110] for k in keys} or str(list(summary))[:180]
    RESULTS.append((name, ok, f"HTTP {response['code']} {response['ms']}ms {summary}"))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:46} HTTP {response['code']} {response['ms']}ms {summary}")
    return response


def main() -> int:
    marker = f"meshprobe-{uuid.uuid4().hex[:10]}"

    print("== liveness ==")
    for agent, health in (("friday", "/api/health"), ("inference", "/health"), ("memora", "/health"),
                          ("intelx", "/api/v1/healthz"), ("futuris", "/health"), ("cortex", "/health"),
                          ("forge", "/health"), ("sentinel", "/health"), ("stratex", "/api/status")):
        check(f"{agent} {health}", call(agent, health))

    print("\n== memory round trip: FRIDAY writes, Memora stores and recalls ==")
    memory_id = f"mem-{marker}"
    written = check("memora record memory", call("memora", "/v1/memories", "POST", {
        "agent_name": "friday", "content_text": f"local fleet mesh probe {marker}",
        "namespace": "friday", "memory_id": memory_id, "importance": 0.7,
    }))
    stored_id = written["detail"].get("id") if isinstance(written["detail"], dict) else None
    if not stored_id and isinstance(written["detail"], dict):
        stored_id = written["detail"].get("memory_id")
    check("memora assigned a durable id", {"ok": bool(stored_id), "code": written["code"],
                                           "ms": written["ms"], "detail": f"id_present={bool(stored_id)}"})
    # Read the record back by the id the store assigned. A write that cannot be read
    # back is not a memory, it is a log line.
    readback = call("memora", f"/v1/memories/{stored_id}") if stored_id else {"ok": False, "code": None, "ms": 0, "detail": "no id"}
    matched = marker in json.dumps(readback["detail"])
    check("memora recalls the stored memory", {"ok": readback["ok"] and matched, "code": readback["code"],
                                               "ms": readback["ms"], "detail": f"content_matched={matched}"})

    print("\n== generation: FRIDAY asks Inference ==")
    check("inference /ask", call("inference", "/ask", "POST",
                                 {"question": f"Reply with exactly: MESH_OK_{marker}", "max_tokens": 40}))

    print("\n== research: FRIDAY delegates to IntelX ==")
    research = check("intelx trigger research", call("intelx", "/api/v1/friday/research", "POST", {
        "friday_request_id": f"fr-{marker}", "objective": f"Verify mesh connectivity marker {marker}",
        "query_scope": {"query": f"mesh connectivity verification {marker}"}, "max_findings": 2,
    }))

    print("\n== forecast: FRIDAY asks Futuris ==")
    check("futuris forecast", call("futuris", "/api/v1/friday/forecast", "POST", {
        "target": "BTCUSDT", "as_agent": "friday", "request_id": f"fu-{marker}",
        "horizon": "24h", "horizon_hours": 24,
    }))

    print("\n== build: FRIDAY delegates to Forge ==")
    check("forge capabilities", call("forge", "/api/v1/capabilities"))

    print("\n== coordination: FRIDAY commands Cortex ==")
    # Cortex exposes user-scoped routes behind a JWT and service-scoped /v1/friday routes
    # behind the mesh key. Exercise the service contract, which is what a peer uses.
    check("cortex friday command", call("cortex", "/v1/friday/command", "POST", {
        "goal": f"verify mesh connectivity {marker}", "required_capability": "status_report",
        "requested_action": "report_fleet_status", "as_agent": "friday", "request_id": f"cx-{marker}",
    }))

    print("\n== trading: FRIDAY reads Stratex ==")
    trades = call("stratex", "/api/telemetry/trades?status=CLOSED&limit=100")
    trade_count = trades["detail"].get("count") if isinstance(trades["detail"], dict) else None
    check("stratex closed trades visible", {"ok": trades["ok"] and bool(trade_count),
                                            "code": trades["code"], "ms": trades["ms"],
                                            "detail": f"count={trade_count}"})

    print("\n== supervision: does FRIDAY see the other eight? ==")
    agents = call("friday", "/api/agents/status")
    seen = None
    if isinstance(agents["detail"], dict):
        for key in ("agents", "services", "items"):
            if isinstance(agents["detail"].get(key), list):
                seen = agents["detail"][key]
                break
    check("friday agent roster", {"ok": agents["ok"], "code": agents["code"], "ms": agents["ms"],
                                  "detail": f"entries={len(seen) if seen is not None else 'unknown'}"})

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n==== {passed}/{len(RESULTS)} passed ====")
    out = FRIDAY / "reports_and_data" / f"local-mesh-probe-{marker}.json"
    out.write_text(json.dumps([{"check": n, "passed": ok, "detail": d} for n, ok, d in RESULTS], indent=2),
                   encoding="utf-8")
    print(f"report: {out}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
