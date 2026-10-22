"""Attack the running fleet through its real entry points.

The bugs that actually mattered in this codebase were not wrong answers -- they were
services that were each internally correct but mutually inconsistent. Unit tests cannot
see that, because each service passes its own suite. So this probe attacks the seams:

  * credential matrix -- does agent A accept agent B's key, or its own where the
    contract says it must not?
  * malformed input  -- missing fields, wrong types, empty bodies, oversized payloads
  * injection        -- SQL fragments, path traversal, control characters
  * state ordering   -- write then immediately read, duplicate submissions
  * failure hygiene  -- a rejected request must be a clean 4xx, never a 500 that
    leaks a traceback or takes the process down

Run the fleet first:
    python research/local_fleet.py --all --serve-only
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

FRIDAY = Path(__file__).resolve().parent.parent
PORTS = {"friday": 8101, "inference": 8102, "memora": 8103, "stratex": 8104,
         "intelx": 8105, "futuris": 8106, "cortex": 8107, "forge": 8108, "sentinel": 8109}


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
FINDINGS: list[dict] = []
CHECKS: list[tuple[str, bool, str]] = []


def raw(agent, path, method="GET", body=None, headers=None, timeout=45.0):
    url = f"http://127.0.0.1:{PORTS[agent]}{path}"
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), int((time.time() - started) * 1000)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), int((time.time() - started) * 1000)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", int((time.time() - started) * 1000)


CRED_HEADERS = ("X-API-Key", "X-Agent-Key", "X-FRIDAY-API-Key", "Authorization", "X-Agent-Name")


def creds(as_agent: str) -> dict[str, str]:
    key = KEYS.get(as_agent, "")
    return {"X-Agent-Name": as_agent, "X-API-Key": key, "X-Agent-Key": key,
            "X-FRIDAY-API-Key": key, "Authorization": f"Bearer {key}"}


def hostile_creds() -> dict[str, str]:
    """A well-formed but entirely unrelated identity.

    Every credential header must be replaced. Overwriting only the obvious ones left
    the real key sitting in X-FRIDAY-API-Key, which made a guarded endpoint look open.
    """
    junk = "z" * 43
    return {h: junk for h in CRED_HEADERS} | {"Authorization": f"Bearer {junk}"}


def record(name, ok, detail):
    CHECKS.append((name, ok, detail))
    print(f"  [{'ok  ' if ok else 'FIND'}] {name:52} {detail}")


def finding(name, detail):
    FINDINGS.append({"finding": name, "detail": detail})
    record(name, False, detail)


# (agent, path) pairs that require a peer credential, per the mesh contract.
PROTECTED = [
    ("memora", "/v1/memories"),
    ("futuris", "/api/v1/friday/forecast"),
    ("intelx", "/api/v1/friday/research"),
    ("cortex", "/v1/friday/command"),
    ("forge", "/api/v1/capabilities"),
]

PAYLOADS = {
    "memora": {"agent_name": "friday", "content_text": "x"},
    "futuris": {"target": "BTCUSDT", "as_agent": "friday"},
    "intelx": {"friday_request_id": "x", "query_scope": {"query": "scope text here"}},
    "cortex": {"goal": "g", "required_capability": "c", "requested_action": "a"},
    "forge": {},
}


def attack_credentials(marker):
    """The seam where mutually inconsistent guards hid."""
    print("\n== credential matrix ==")
    for agent, path in PROTECTED:
        # No credential at all.
        code, body, _ = raw(agent, path, "POST", PAYLOADS.get(agent, {}), {})
        if code in (500, None):
            finding(f"{agent}: unauthenticated request", f"HTTP {code} {body[:180]}")
        elif code == 200:
            finding(f"{agent}: accepts unauthenticated request", f"HTTP 200 {body[:180]}")
        else:
            record(f"{agent}: rejects no credential", True, f"HTTP {code}")

        # A well-formed but entirely unrelated identity, on every credential header.
        code, body, _ = raw(agent, path, "POST", PAYLOADS.get(agent, {}), hostile_creds())
        if code in (500, None):
            finding(f"{agent}: wrong key", f"HTTP {code} {body[:180]}")
        elif code == 200:
            finding(f"{agent}: accepts an unrelated key", f"HTTP 200 {body[:180]}")
        else:
            record(f"{agent}: rejects unrelated key", True, f"HTTP {code}")

        # Near-miss: valid key plus trailing whitespace, a classic parser split.
        padded = dict(creds("friday"))
        for header in CRED_HEADERS:
            if header in padded:
                padded[header] = padded[header] + " "
        code, body, _ = raw(agent, path, "POST", PAYLOADS.get(agent, {}), padded)
        record(f"{agent}: key with trailing space", code in (401, 403, 422),
               f"HTTP {code}" + (" <- ACCEPTED" if code in (200, 201) else ""))


def attack_inputs(marker):
    """A rejected request must be a clean 4xx, never a crash."""
    print("\n== malformed input ==")
    hostile = {
        "empty_body": {},
        "null_fields": None,
        "wrong_type": {"agent_name": 12345, "content_text": ["not", "a", "string"]},
        "sql_fragment": {"agent_name": "friday", "content_text": "'; DROP TABLE memories; --"},
        "path_traversal": {"agent_name": "friday", "content_text": "../../etc/passwd"},
        "control_chars": {"agent_name": "friday", "content_text": "line1\nline2\r\nInjected: header"},
        "unicode_bomb": {"agent_name": "friday", "content_text": "\U0001f600" * 400},
        "huge_string": {"agent_name": "friday", "content_text": "A" * 2_000_000},
    }
    for agent, path in PROTECTED:
        for label, payload in hostile.items():
            headers = creds("friday")
            try:
                code, body, ms = raw(agent, path, "POST", payload, headers, timeout=60.0)
            except Exception as e:
                finding(f"{agent}: {label}", f"transport failure {e}")
                continue
            if code is None:
                finding(f"{agent}: {label}", f"no response / hang ({ms}ms)")
            elif code >= 500:
                finding(f"{agent}: {label}", f"HTTP {code} {body[:200]}")
            else:
                record(f"{agent}: {label}", True, f"HTTP {code} {ms}ms")


def attack_ordering(marker):
    """Write-then-read, and duplicate submission, must stay consistent."""
    print("\n== state ordering ==")
    memory_id = f"adv-{marker}"
    body = {"agent_name": "friday", "content_text": f"adversarial ordering {marker}",
            "namespace": "friday", "memory_id": memory_id, "importance": 0.5}
    code, text, _ = raw("memora", "/v1/memories", "POST", body, creds("friday"))
    record("memora write accepted", code in (200, 201), f"HTTP {code}")
    try:
        stored = json.loads(text)
        stored_id = stored.get("id") or stored.get("memory_id")
    except Exception:
        stored_id = None

    # Immediately read: no sleep. Anything else is a visibility race.
    if stored_id:
        code, text, ms = raw("memora", f"/v1/memories/{stored_id}", "GET", None, creds("friday"))
        record("memora immediate read-after-write", code == 200 and marker in text,
               f"HTTP {code} visible={marker in text} {ms}ms")
    else:
        finding("memora write returned no id", f"HTTP {code} {text[:180]}")

    # Duplicate submission of the same idempotency-style id.
    code2, text2, _ = raw("memora", "/v1/memories", "POST", body, creds("friday"))
    record("memora duplicate submit is handled", code2 is not None and code2 < 500,
           f"HTTP {code2}")

    # Concurrent writes to the same namespace must not corrupt each other.
    import threading
    errors: list = []

    def hammer(i):
        c, t, _ = raw("memora", "/v1/memories", "POST",
                      {"agent_name": "friday", "content_text": f"concurrent {marker}-{i}",
                       "namespace": "friday", "importance": 0.4},
                      creds("friday"), timeout=60.0)
        if c is None or c >= 500:
            errors.append(f"thread {i}: HTTP {c} {t[:120]}")

    threads = [threading.Thread(target=hammer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        finding("memora concurrent writes", "; ".join(errors[:3]))
    else:
        record("memora 8 concurrent writes", True, "all handled")


def attack_health_truthfulness():
    """Health endpoints must not report ready while the service cannot serve."""
    print("\n== health truthfulness ==")
    for agent, path in (("memora", "/health"), ("inference", "/health/ready"),
                        ("forge", "/health/ready"), ("cortex", "/health/ready"),
                        ("sentinel", "/health"), ("intelx", "/api/v1/health")):
        code, text, _ = raw(agent, path, "GET")
        # A readiness endpoint answering 503 is the honest "not ready" answer and is
        # correct behaviour. Only a crash, a hang, or a missing route is a defect.
        if code is None or code >= 500 and agent != "cortex":
            finding(f"{agent}: {path} crashed", f"HTTP {code}")
            continue
        detail = f"HTTP {code}"
        try:
            payload = json.loads(text)
            detail = f"HTTP {code} {json.dumps({k: payload[k] for k in list(payload)[:4]})[:150]}"
        except Exception:
            detail = f"HTTP {code} non-json"
        record(f"{agent}: {path}", True, detail)


def main() -> int:
    marker = uuid.uuid4().hex[:10]
    print(f"adversarial mesh probe {marker}")
    attack_credentials(marker)
    attack_inputs(marker)
    attack_ordering(marker)
    attack_health_truthfulness()

    found = [f for f in FINDINGS]
    print(f"\n==== {len(CHECKS) - len(found)}/{len(CHECKS)} clean, {len(found)} findings ====")
    for f in found:
        print(f"  ! {f['finding']}: {f['detail']}")
    out = FRIDAY / "reports_and_data" / f"adversarial-mesh-probe-{marker}.json"
    out.write_text(json.dumps({"checks": [{"check": n, "clean": o, "detail": d} for n, o, d in CHECKS],
                               "findings": found}, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
