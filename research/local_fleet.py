"""Boot the whole FRIDAY Universe locally and exercise the real mesh.

Every agent runs as a real process on a loopback port with the same credentials it
uses in production, and every peer URL is pointed at the local fleet instead of
onrender.com. Nothing is stubbed: the mesh calls here are real HTTP requests against
real processes, which in turn reach real upstream APIs.

    python research/local_fleet.py --agents memora,intelx,futuris
    python research/local_fleet.py --all --serve-only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

UNIVERSE = Path(__file__).resolve().parent.parent.parent

# agent -> (repo dir, base port offset, health path, launch argv)
AGENTS = {
    "friday":   ("FRIDAY",   8101, "/health",  ["-m", "uvicorn", "friday.api.server:app", "--host", "127.0.0.1", "--port", "{port}"]),
    "inference": ("Inference", 8102, "/health", ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "{port}"]),
    "memora":   ("Memora",   8103, "/health",  ["-m", "uvicorn", "apps.api.main:app", "--host", "127.0.0.1", "--port", "{port}"]),
    "stratex":  ("Stratex",  8104, "/health",  ["dashboard.py"]),
    "intelx":   ("IntelX",   8105, "/healthz", ["-m", "intelx.cli.main", "serve", "--host", "127.0.0.1", "--port", "{port}"]),
    "futuris":  ("Futuris",  8106, "/health",  ["-m", "futuris.cli", "serve", "--host", "127.0.0.1", "--port", "{port}"]),
    "cortex":   ("Cortex",   8107, "/health",  ["-m", "uvicorn", "cortex_api.main:app", "--host", "127.0.0.1", "--port", "{port}"]),
    "forge":    ("Forge",    8108, "/health",  ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "{port}"]),
    "sentinel": ("Sentinel", 8109, "/health",  ["-m", "uvicorn", "sentinel.apps.api.main:app", "--host", "127.0.0.1", "--port", "{port}"]),
}

PORTS = {name: spec[1] for name, spec in AGENTS.items()}
HEALTH = {name: spec[2] for name, spec in AGENTS.items()}
REPOS = {name: UNIVERSE / spec[0] for name, spec in AGENTS.items()}

# Each repo needs its own interpreter: Memora ships a venv with its drivers.
INTERPRETERS = {"memora": ".venv/Scripts/python.exe"}


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def port_is_free(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def assert_env_clean(agent: str, env: dict[str, str]) -> None:
    """Refuse to launch with control characters in the environment.

    Windows raises an opaque "embedded null character" from CreateProcess when any
    environment value carries a NUL, which says nothing about the real cause. A
    truncated or binary-contaminated .env value should be named, not guessed at.
    """
    dirty = sorted(k for k, v in env.items() if isinstance(v, str) and any(ord(c) < 32 for c in v))
    if dirty:
        raise ValueError(f"{agent}: environment values contain control characters: {dirty}")


def build_env(agent: str, source_env: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    env.update(source_env)
    # Point every peer at the local fleet. The env var wins over the repo .env,
    # because each service loads dotenv without overriding existing variables.
    for peer, peer_port in PORTS.items():
        env[f"{peer.upper()}_URL"] = f"http://127.0.0.1:{peer_port}"
    env["PORT"] = str(PORTS[agent])
    env["HOST"] = "127.0.0.1"
    # Keep the universe off production credentials for anything that can spend.
    env.setdefault("TRADING_MODE", env.get("TRADING_MODE", "TESTNET"))
    return env


def wait_for_health(agent: str, timeout: float) -> tuple[bool, str]:
    url = f"http://127.0.0.1:{PORTS[agent]}{HEALTH[agent]}"
    deadline = time.time() + timeout
    last = "no response"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=4) as response:
                return True, f"HTTP {response.status}"
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code} {exc.read()[:200].decode('utf-8', 'replace')}"
        except Exception as exc:  # not up yet
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(1.5)
    return False, last


def launch(agent: str, log_dir: Path) -> subprocess.Popen | None:
    repo = REPOS[agent]
    source_env = read_dotenv(repo / ".env")
    env = build_env(agent, source_env)
    assert_env_clean(agent, env)
    # Windows resolves the executable against the parent's cwd, not the child's,
    # so an interpreter path must be absolute before Popen is handed a cwd.
    interpreter = INTERPRETERS.get(agent)
    if interpreter:
        resolved = (repo / interpreter).resolve()
        if not resolved.exists():
            print(f"  {agent}: interpreter missing at {resolved}")
            return None
        argv = [str(resolved)]
    else:
        argv = [sys.executable]
    argv = argv + [a.format(port=PORTS[agent]) for a in AGENTS[agent][3]]
    log_dir.mkdir(parents=True, exist_ok=True)
    handle = open(log_dir / f"{agent}.log", "w", encoding="utf-8")
    return subprocess.Popen(argv, cwd=repo, env=env, stdout=handle, stderr=subprocess.STDOUT)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agents", default="memora")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--serve-only", action="store_true")
    parser.add_argument("--boot-timeout", type=float, default=150.0)
    args = parser.parse_args()

    selected = list(AGENTS) if args.all else [a.strip().lower() for a in args.agents.split(",") if a.strip()]
    unknown = [a for a in selected if a not in AGENTS]
    if unknown:
        print(f"unknown agents: {unknown}")
        return 2

    log_dir = UNIVERSE / "FRIDAY" / "reports_and_data" / "local_fleet"
    blocked = [a for a in selected if not port_is_free(PORTS[a])]
    if blocked:
        print(f"ports already in use for: {blocked}")
        return 2

    print(f"booting {selected}")
    procs = {}
    for agent in selected:
        try:
            proc = launch(agent, log_dir)
        except Exception as exc:
            print(f"  {agent:10} LAUNCH ERROR  {exc}")
            results[agent] = (False, str(exc))
            continue
        if proc is None:
            print(f"  {agent:10} LAUNCH ERROR  interpreter missing")
            results[agent] = (False, "interpreter missing")
        else:
            procs[agent] = proc
        time.sleep(1.0)

    results = {}
    for agent in selected:
        if agent not in procs:
            results.setdefault(agent, (False, "did not launch"))
            continue
        ok, detail = wait_for_health(agent, args.boot_timeout)
        results[agent] = (ok, detail)
        print(f"  {agent:10} {'UP  ' if ok else 'DOWN'} {detail}")

    if args.serve_only:
        print("serve-only: leaving processes up; Ctrl-C to stop")
        try:
            while True:
                time.sleep(5)
        except KeyboardInterrupt:
            pass

    for proc in procs.values():
        proc.terminate()
    out = log_dir / "boot_report.json"
    out.write_text(json.dumps({k: {"up": v[0], "detail": v[1]} for k, v in results.items()}, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0 if all(v[0] for v in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
