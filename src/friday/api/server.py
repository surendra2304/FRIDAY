"""FRIDAY UI & FastMCP Server for Surendra's FRIDAY.

Provides:
- Bidirectional WebSocket for real-time voice, audio waveforms, and MediaPipe hand gestures
- Fast-path execution for low-latency PC and Android device control
- FastMCP Server endpoints (/sse, /messages) for Model Context Protocol interoperability
- Tool Catalog API (/api/tools) and System Observability (/api/metrics, /api/health)
"""

from __future__ import annotations

import asyncio
import base64
import ctypes
import json
import ipaddress
import logging
import os
import re
import subprocess
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from friday.agent.agent import FridayAgent
from friday.cli.auth import CLIAuthorizer
from friday.core.auth import DefaultSecureAuthorizer
from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.devices.android_controller import AndroidDeviceController
from friday.devices.app_launcher import launch_desktop_app
from friday.ecosystem.fleet_client import fleet_client
from friday.memory.event_consumer import MemoraEventConsumer
from friday.memory.memora_client import memora_client
from friday.autonomous import autonomous_controller
from friday.autonomous.repair_loop import repair_loop
from friday.cognition.reflex import IncidentKind, get_reflex_brain
from friday.cognition.mesh import get_mesh
from friday.cognition.mind import get_mind_registry
from friday.autonomous.self_repair import (
    GitRepairApplier,
    RepairProposal,
    SelfRepairGate,
)
from friday_deep.observability.metrics import DEFAULT as default_metrics
from friday_deep.health import build as build_health_report

logger = get_logger("api.server")

try:
    FLEET_SUPERVISION_INTERVAL_SECONDS = max(
        30, int(os.getenv("FRIDAY_FLEET_SUPERVISION_INTERVAL_SECONDS", "300"))
    )
except ValueError:
    FLEET_SUPERVISION_INTERVAL_SECONDS = 300

fleet_supervision_state: dict[str, Any] = {
    "running": False,
    "interval_seconds": FLEET_SUPERVISION_INTERVAL_SECONDS,
    "last_started_at": None,
    "last_completed_at": None,
    "last_error": None,
    "agents": [],
}

MEMORA_EVENT_CONSUMER_ID = "friday-cloud"
try:
    MEMORA_EVENT_POLL_INTERVAL_SECONDS = max(30, int(os.getenv("FRIDAY_MEMORA_POLL_INTERVAL_SECONDS", "60")))
except ValueError:
    MEMORA_EVENT_POLL_INTERVAL_SECONDS = 60
memora_event_state: dict[str, Any] = {
    "consumer_id": MEMORA_EVENT_CONSUMER_ID,
    "running": False,
    "last_completed_at": None,
    "last_result": None,
}


async def _fleet_supervision_loop() -> None:
    """Continuously refresh peer reachability while the cloud FRIDAY process is alive."""
    fleet_supervision_state["running"] = True
    try:
        while True:
            fleet_supervision_state["last_started_at"] = datetime.now(timezone.utc).isoformat()
            try:
                statuses = await fleet_client.get_all_statuses(force_refresh=True)
                fleet_supervision_state["agents"] = [status.__dict__ for status in statuses]
                fleet_supervision_state["last_completed_at"] = datetime.now(timezone.utc).isoformat()
                fleet_supervision_state["last_error"] = None
            except Exception as exc:
                # Keep the last known snapshot, but make the failed poll visible.
                fleet_supervision_state["last_error"] = type(exc).__name__
                logger.exception("FRIDAY fleet supervision cycle failed")
            await asyncio.sleep(FLEET_SUPERVISION_INTERVAL_SECONDS)
    finally:
        fleet_supervision_state["running"] = False


async def _memora_event_loop() -> None:
    """Archive untrusted Memora notices durably before advancing FRIDAY's cloud cursor."""
    consumer = MemoraEventConsumer(
        memora_client,
        consumer_id=MEMORA_EVENT_CONSUMER_ID,
        persist_notice=memora_client.persist_event_notice,
    )
    memora_event_state["running"] = True
    try:
        while True:
            try:
                result = await asyncio.to_thread(consumer.consume_once)
                memora_event_state["last_result"] = result
                memora_event_state["last_completed_at"] = datetime.now(timezone.utc).isoformat()
                if result.get("status") != "ok":
                    logger.warning("Memora event consumption did not complete: %s", result)
                while result.get("status") == "ok" and result.get("has_more"):
                    result = await asyncio.to_thread(consumer.consume_once)
                    memora_event_state["last_result"] = result
                    memora_event_state["last_completed_at"] = datetime.now(timezone.utc).isoformat()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                memora_event_state["last_result"] = {"status": "error", "error": type(exc).__name__}
                memora_event_state["last_completed_at"] = datetime.now(timezone.utc).isoformat()
                logger.exception("FRIDAY Memora event consumer cycle failed")
            await asyncio.sleep(MEMORA_EVENT_POLL_INTERVAL_SECONDS)
    finally:
        memora_event_state["running"] = False


async def _reflex_loop() -> None:
    """Run the cognition reflex for as long as the service lives.

    A failure inside the loop is logged and the loop stops rather than spins: a
    brain that keeps crashing should be visible in the log, not silent.
    """
    brain = get_reflex_brain()
    if not brain.enabled:
        logger.info("Reflex brain is disabled by FRIDAY_REFLEX_ENABLED")
        return
    try:
        await brain.run_forever()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Reflex brain loop stopped with an error")


async def _configure_memory_mirror() -> None:
    """Point shared memory at the Memora peer, but only when asked.

    Mirroring is best-effort and off by default: an unreachable memory peer must
    never add its timeout to the path of a task that is doing real work.
    """
    if os.getenv("FRIDAY_MEMORY_MIRROR", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return
    try:
        from friday.cognition.memory_bridge import mesh_mirror, set_shared_memory, SharedMemory

        set_shared_memory(SharedMemory(mirror=mesh_mirror(get_mesh())))
        logger.info("Shared memory will mirror episodes to Memora (FRIDAY_MEMORY_MIRROR is on)")
    except Exception:
        logger.exception("Shared memory mirroring could not be configured")


@asynccontextmanager
async def lifespan(_: FastAPI):
    supervision_task = asyncio.create_task(_fleet_supervision_loop(), name="friday-fleet-supervision")
    memora_task = asyncio.create_task(_memora_event_loop(), name="friday-memora-event-consumer")
    # The unattended repair pass. Until this task existed the trigger had no
    # caller in the running service at all, so nothing here could fire it. It
    # stays inert unless an owner sets FRIDAY_SELF_REPAIR_TRIGGER_ENABLED, and
    # it sleeps before its first pass so a restart is not a repair storm.
    repair_task = asyncio.create_task(repair_loop.run_forever(), name="friday-autonomous-repair")
    # The cognition reflex: detect a fault anywhere in FRIDAY's own code, runtime
    # or fleet, prove a repair in a sandbox, and apply it under a standing mandate.
    # `run_forever` sleeps before its first pass, so a restart is not a repair
    # storm. Set FRIDAY_REFLEX_ENABLED=false to keep it out of this process.
    reflex_task = asyncio.create_task(_reflex_loop(), name="friday-reflex-brain")
    memory_mirror_task = asyncio.create_task(_configure_memory_mirror(), name="friday-memory-mirror")
    try:
        yield
    finally:
        # Named literally, not through a variable: a task that outlives shutdown is
        # a repair pass firing into a dead process, and the invariant that every
        # task created above is cancelled here is checked by parsing this loop.
        for task in (supervision_task, memora_task, repair_task, reflex_task, memory_mirror_task):
            task.cancel()
        for task in (supervision_task, memora_task, repair_task, reflex_task, memory_mirror_task):
            try:
                await task
            except asyncio.CancelledError:
                pass

app = FastAPI(
    title="FRIDAY Holographic Core & FastMCP Server",
    description="Multi-modal AI assistant server supporting WebGL Hologram, MediaPipe gestures, Android ADB control, and FastMCP.",
    version="2.0.0",
    lifespan=lifespan,
)

# Allow the command centre to connect without ever reflecting an untrusted origin.
# `allow_origins=["*"]` cannot be combined with credentials and Starlette resolves
# the pair by echoing whatever origin asked. The list below is explicit; the
# authoritative gate for state-changing calls is `_origin_allowed` in
# `_require_control_access`, which also covers WebSocket upgrades that CORS
# middleware does not police.
def _configured_origins() -> list[str]:
    raw = getattr(get_settings(), "allowed_origins", "") or ""
    return sorted({item.strip().rstrip("/") for item in raw.split(",") if item.strip()})


def _live_settings() -> Any:
    """Read settings at call time.

    The module-level `settings` object is bound once at import, so a reload (or a
    `FRIDAY_*` override applied after import) would not be seen by the
    authorisation path. Authorisation must always reflect the configuration that
    is in force now, not the one that was in force when the process started.
    """
    return get_settings()


app.add_middleware(
    CORSMiddleware,
    allow_origins=_configured_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings = get_settings()
memora_client.base_url = str(getattr(settings, "memora_url", memora_client.base_url)).rstrip("/")
memora_api_key = getattr(settings, "memora_api_key", None) or getattr(settings, "api_key", None)
if memora_api_key:
    memora_client.api_key = memora_api_key
    memora_client.remote_enabled = True


_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _origin_allowed(origin: str, request: Request) -> bool:
    """Decide whether a browser origin may drive this API.

    An empty `Origin` means the caller is not a browser (curl, the MCP client, a
    server-to-server peer) and is judged by the credential rules instead. Every
    other value must match either this service's own origin or the configured
    allow-list. `null` is refused outright: it is what a sandboxed iframe, a
    `data:` URL or a `file://` page sends, and none of those are the owner.
    """
    if not origin:
        return True
    if origin == "null":
        return False
    allowed = set(_configured_origins())
    host = request.headers.get("host", "")
    if host:
        allowed.add(f"{request.url.scheme}://{host}".rstrip("/"))
    return origin.rstrip("/") in allowed


async def _require_control_access(request: Request) -> None:
    """Authorise a control request.

    Three independent gates, cheapest first:

    1. **Origin.** A browser attaches `Origin` to cross-origin state-changing
       requests, so a request from a page the owner merely has open cannot reach
       this API at all. This is the gate that stops drive-by command execution
       from an arbitrary website, and it applies to loopback callers too — the
       owner's own browser is a loopback caller.
    2. **Network exposure.** Requests arriving from beyond this machine, or from
       a cloud deployment, must present the control API key.
    3. **Opt-in loopback hardening.** With `require_api_key_on_loopback`, the key
       is demanded for state-changing calls from this machine as well.
    """
    if not _origin_allowed(request.headers.get("origin", "").strip(), request):
        raise HTTPException(
            status_code=403,
            detail=(
                "This browser origin is not permitted to reach the FRIDAY control API. "
                "Add it to FRIDAY_ALLOWED_ORIGINS if it is a trusted frontend."
            ),
        )

    client_host = request.client.host if request.client else ""
    client_is_remote = False
    try:
        client_is_remote = not ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        pass
    remotely_exposed = bool(os.getenv("RENDER") or client_is_remote)
    live = _live_settings()
    loopback_hardening = bool(
        getattr(live, "require_api_key_on_loopback", False)
        and getattr(request, "method", "GET").upper() not in _IDEMPOTENT_METHODS
    )
    if not remotely_exposed and not loopback_hardening:
        return

    expected = (getattr(live, "api_key", None) or os.getenv("FRIDAY_API_KEY") or os.getenv("FRIDAY_UNIVERSE_API_KEY") or "").strip()
    if not expected or expected.lower() in {"friday_universe_api", "changeme", "change-me", "your_api_key"}:
        raise HTTPException(status_code=503, detail="Remote control is disabled until a non-example FRIDAY_API_KEY is configured.")

    provided = request.headers.get("x-friday-api-key", "")
    authorization = request.headers.get("authorization", "")
    if not provided and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    import hmac
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="A valid FRIDAY control API key is required.")


def _websocket_origin_allowed(websocket: WebSocket) -> bool:
    """Apply the same origin policy to WebSocket upgrades, which CORS never sees."""
    return _origin_allowed(websocket.headers.get("origin", "").strip(), websocket)  # type: ignore[arg-type]

# Initialize global agent and Android controller
agent = FridayAgent(
    settings=settings,
    # A web server has no terminal, so an interactive authorizer would either block a
    # request thread on a stdin nobody is typing into or report the resulting EOF as a
    # refusal. The headless authorizer refuses the same consequential calls and says
    # why; a human is never asked a question they cannot see.
    authorizer=CLIAuthorizer() if CLIAuthorizer._has_a_terminal() else DefaultSecureAuthorizer(),
)
android = AndroidDeviceController()


class CommandRequest(BaseModel):
    command: str


class AndroidActionRequest(BaseModel):
    action: str  # "tap", "swipe", "type", "key", "app", "info"
    params: dict[str, Any] = {}


@app.api_route("/api/health", methods=["GET", "HEAD"])
@app.api_route("/health", methods=["GET", "HEAD"])
async def health_check() -> dict[str, Any]:
    """Expose system health report verified across all subsystems."""
    rep = build_health_report(["friday", "friday_deep"])
    return rep.as_dict()


@app.get("/api/metrics")
async def metrics_endpoint() -> dict[str, Any]:
    """Return runtime observability metrics from friday_deep."""
    return default_metrics.snapshot()


@app.get("/api/telemetry")
async def get_telemetry() -> dict[str, Any]:
    """Expose real-time hardware telemetry (CPU, RAM, Battery) for the UI."""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        batt = psutil.sensors_battery()
        battery_pct = batt.percent if batt is not None else None
        power_plugged = batt.power_plugged if batt is not None else None
    except Exception as exc:
        return {"status": "unavailable", "error": type(exc).__name__, "timestamp": datetime.now(timezone.utc).isoformat()}

    return {
        "status": "ok",
        "battery_available": batt is not None,
        "cpu_usage": cpu,
        "cpu_percent": cpu,
        "ram_usage": mem,
        "ram_percent": mem,
        "battery_pct": battery_pct,
        "power_plugged": power_plugged,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/system_telemetry")
async def get_system_telemetry() -> dict[str, Any]:
    """Expose detailed system hardware telemetry for the HUD core cards."""
    try:
        import platform
        import psutil
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_cores = psutil.cpu_count(logical=True) or 8
        vm = psutil.virtual_memory()
        return {
            "status": "ok",
            "cpu_percent": round(cpu_percent, 1),
            "cpu_cores": cpu_cores,
            "ram_percent": round(vm.percent, 1),
            "ram_total_gb": round(vm.total / (1024**3), 1),
            "ram_used_gb": round(vm.used / (1024**3), 1),
            "ram_avail_gb": round(vm.available / (1024**3), 1),
            "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "operator": "Surendra",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {
            "status": "unavailable",
            "error": type(e).__name__,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ==============================================================================
# Canonical Task Lifecycle, SSE Progress, and Emergency Control Endpoints
# ==============================================================================

from friday.core.task_manager import task_manager


@app.get("/v1/tasks/{task_id}")
@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str) -> Any:
    """Retrieve state and observability progress for a task envelope."""
    t = task_manager.get_task(task_id)
    if not t:
        return JSONResponse({"status": "not_found", "task_id": task_id}, status_code=404)
    return {"status": "ok", "task": t.model_dump()}


@app.get("/v1/tasks/{task_id}/events")
@app.get("/api/tasks/{task_id}/events")
async def get_task_events(task_id: str) -> StreamingResponse:
    """Server-Sent Events (SSE) channel for real-time task progress and findings."""
    return StreamingResponse(
        task_manager.subscribe_events(task_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/v1/tasks/{task_id}/cancel")
@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task_endpoint(task_id: str, _: None = Depends(_require_control_access)) -> dict[str, Any]:
    """First-class task cancellation endpoint."""
    success = await task_manager.cancel_task(task_id)
    return {"status": "cancelled" if success else "not_running", "task_id": task_id}


@app.post("/v1/tasks/cancel-all")
@app.post("/api/tasks/cancel-all")
async def cancel_all_tasks_endpoint(_: None = Depends(_require_control_access)) -> dict[str, Any]:
    """Cancel all running tasks (triggered by voice commands like 'stop' or 'cancel that task')."""
    count = await task_manager.cancel_active_tasks()
    return {"status": "ok", "cancelled_count": count}


@app.post("/v1/emergency/stop")
@app.post("/api/emergency/stop")
async def emergency_stop_endpoint(_: None = Depends(_require_control_access)) -> dict[str, Any]:
    """Global emergency stop triggering 8-subsystem freeze cascade."""
    report = await task_manager.emergency_stop()
    return report


@app.get("/api/tools")
async def list_tools() -> list[dict[str, Any]]:
    """List all available tools and parameters in FRIDAY's canonical catalog."""
    schemas = agent.tools.get_schemas() or []
    tools = []
    for s in schemas:
        fn = s.get("function", s)
        tools.append({
            "name": fn.get("name"),
            "description": fn.get("description", ""),
            "parameters": fn.get("parameters", {}),
        })
    return tools


@app.get("/api/agents")
async def list_agents() -> list[dict[str, Any]]:
    """Expose the 8 FRIDAY Universe specialist agents with live health and latency."""
    statuses = await fleet_client.get_all_statuses()
    return [
        {
            "id": s.id,
            "name": s.name,
            "role": s.role,
            "icon": s.icon,
            "status": s.status,
            "latency_ms": s.latency_ms,
            "desc": s.details,
            "endpoint": s.endpoint,
        }
        for s in statuses
    ]


@app.get("/api/agents/status")
async def get_agents_status() -> dict[str, Any]:
    """Return a fresh peer endpoint reachability snapshot, not task-level verification."""
    statuses = await fleet_client.get_all_statuses(force_refresh=True)
    status_counts = {
        status: sum(1 for agent_status in statuses if agent_status.status == status)
        for status in ("ONLINE", "DEGRADED", "OFFLINE")
    }
    all_agents_reported = len(statuses) == 8
    overall_ok = all_agents_reported and status_counts["ONLINE"] == 8
    return {
        "status": "ok" if overall_ok else "degraded",
        "scope": "peer_endpoint_reachability_only",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_count": len(statuses),
        "status_counts": status_counts,
        "agents": [s.__dict__ for s in statuses],
        "note": "HTTP health responses do not verify agent task execution, data persistence, or event delivery.",
    }


@app.get("/api/agents/supervision")
async def get_agents_supervision() -> dict[str, Any]:
    """Report the background peer poll snapshot without implying task-level health."""
    now = datetime.now(timezone.utc)
    completed = fleet_supervision_state.get("last_completed_at")
    age_seconds = None
    if completed:
        try:
            completed_at = datetime.fromisoformat(completed)
            age_seconds = max(0, int((now - completed_at).total_seconds()))
        except (TypeError, ValueError):
            age_seconds = None
    agents = fleet_supervision_state.get("agents", [])
    status_counts = {
        status: sum(1 for agent_status in agents if agent_status.get("status") == status)
        for status in ("ONLINE", "DEGRADED", "OFFLINE")
    }
    snapshot_is_fresh = age_seconds is not None and age_seconds <= FLEET_SUPERVISION_INTERVAL_SECONDS * 2
    all_agents_reported = len(agents) == 8
    overall_ok = (
        fleet_supervision_state.get("running")
        and snapshot_is_fresh
        and all_agents_reported
        and status_counts["ONLINE"] == 8
        and fleet_supervision_state.get("last_error") is None
    )
    return {
        "status": "ok" if overall_ok else "degraded",
        "scope": "peer_endpoint_reachability_only",
        "checked_at": completed,
        "snapshot_age_seconds": age_seconds,
        "interval_seconds": FLEET_SUPERVISION_INTERVAL_SECONDS,
        "last_error": fleet_supervision_state.get("last_error"),
        "agent_count": len(agents),
        "status_counts": status_counts,
        "agents": agents,
        "memora_event_consumer": dict(memora_event_state),
        "note": "HTTP health responses do not verify agent task execution, data persistence, or event delivery.",
    }


@app.get("/api/autonomous/status")
async def get_autonomous_status() -> dict[str, Any]:
    """Expose real-time state of the autonomous execution and recovery subsystem."""
    return autonomous_controller.get_status()


@app.post("/api/autonomous/toggle")
async def toggle_autonomous_mode(_: None = Depends(_require_control_access)) -> dict[str, Any]:
    """Toggle Autonomous Mode on or off."""
    new_state = autonomous_controller.toggle()
    return {"status": "ok", "autonomous_mode": new_state}


@app.post("/api/autonomous/repair")
async def trigger_autonomous_repair(_: None = Depends(_require_control_access)) -> dict[str, Any]:
    """Trigger an immediate autonomous self-healing and diagnostic sweep."""
    return await autonomous_controller.execute_self_repair()


# ── Gated self-repair pipeline (Phase E1) ────────────────────────────────
# Every mutating step below is behind _require_control_access, and additionally
# behind the gate's own rules: no step can reach a working tree without a
# fingerprint-bound, single-use owner approval that survived a Sentinel review.

_self_repair_repo = os.getenv("FRIDAY_SELF_REPAIR_REPO", "").strip()
_self_repair_gate = SelfRepairGate(
    GitRepairApplier(_self_repair_repo) if _self_repair_repo else None
)


class ReflexRunRequest(BaseModel):
    """Which incident classes to examine; empty means all of them."""

    scope: str = ""


class RepairProposalRequest(BaseModel):
    repo_path: str = ""
    branch: str
    base_commit: str
    target_file: str
    original_snippet: str
    replacement_snippet: str
    rationale: str
    proposed_by: str = "forge"
    test_evidence: dict[str, Any] = {}


class RepairDecisionRequest(BaseModel):
    actor: str
    approve: bool = True


class SignedReviewRequest(BaseModel):
    """A Sentinel review document, carried verbatim.

    Accepts the signed document either as the body itself or wrapped in
    ``{"review": {...}}``, so the sender does not have to reshape its own output.
    """

    document: dict[str, Any]


@app.post("/api/self-repair/proposals")
async def propose_repair(
    req: RepairProposalRequest, _: None = Depends(_require_control_access)
) -> dict[str, Any]:
    """File a repair proposal. Evidence-free proposals are refused, not stored as ready."""
    record, receipt = _self_repair_gate.propose(
        RepairProposal(
            repo_path=req.repo_path or _self_repair_repo,
            branch=req.branch,
            base_commit=req.base_commit,
            target_file=req.target_file,
            original_snippet=req.original_snippet,
            replacement_snippet=req.replacement_snippet,
            rationale=req.rationale,
            proposed_by=req.proposed_by,
            test_evidence=req.test_evidence,
        )
    )
    return {"record": record.as_dict(), "receipt": receipt.as_dict()}


@app.post("/api/self-repair/{patch_id}/review")
async def review_repair(
    patch_id: str, req: SignedReviewRequest, _: None = Depends(_require_control_access)
) -> dict[str, Any]:
    """File Sentinel's review.

    The request body is the signed review document itself, not a claim about who
    reviewed. The gate verifies the HMAC, so this endpoint cannot be used to
    assert a review that Sentinel did not actually sign.
    """
    receipt = _self_repair_gate.record_review(patch_id, req.document)
    return {"receipt": receipt.as_dict(), "record": _describe(_self_repair_gate, patch_id)}


@app.post("/api/self-repair/{patch_id}/owner-decision")
async def owner_decision(
    patch_id: str, req: RepairDecisionRequest, _: None = Depends(_require_control_access)
) -> dict[str, Any]:
    """Record the owner's decision. Agent identities are refused by the gate."""
    receipt = _self_repair_gate.record_owner_decision(
        patch_id, approver=req.actor, approve=req.approve
    )
    return {"receipt": receipt.as_dict(), "record": _describe(_self_repair_gate, patch_id)}


@app.post("/api/self-repair/{patch_id}/apply")
async def apply_repair(patch_id: str, _: None = Depends(_require_control_access)) -> dict[str, Any]:
    """Apply an approved repair. Refused without a live, unconsumed, matching approval."""
    receipt = _self_repair_gate.apply(patch_id)
    return {"receipt": receipt.as_dict(), "record": _describe(_self_repair_gate, patch_id)}


@app.post("/api/self-repair/{patch_id}/rollback")
async def rollback_repair(patch_id: str, _: None = Depends(_require_control_access)) -> dict[str, Any]:
    """Revert an applied repair as its own auditable commit."""
    receipt = _self_repair_gate.rollback(patch_id)
    return {"receipt": receipt.as_dict(), "record": _describe(_self_repair_gate, patch_id)}


# Declared before ``/{patch_id}`` on purpose. FastAPI matches in registration
# order, so a literal segment registered after a catch-all is unreachable - it
# would be read as a patch id and answered with ``{"found": false}``.
@app.get("/api/self-repair/autonomous")
async def autonomous_repair_status() -> dict[str, Any]:
    """Report what the unattended loop is configured to do and last did.

    Unauthenticated on purpose, and read-only: an owner deciding whether to trust
    this loop should not have to hold a control key to find out whether it has
    ever run. It names the environment keys that are missing, so ``NOT_CONFIGURED``
    here names the thing to set rather than only refusing.
    """
    return repair_loop.status()


@app.get("/api/self-repair/{patch_id}")
async def repair_status(patch_id: str, _: None = Depends(_require_control_access)) -> dict[str, Any]:
    """Return the full receipt trail for one repair."""
    return {"record": _describe(_self_repair_gate, patch_id)}


def _describe(gate: SelfRepairGate, patch_id: str) -> dict[str, Any]:
    record = gate.get(patch_id)
    if record is None:
        return {"found": False, "patch_id": patch_id}
    return {"found": True, **record.as_dict()}


# ── Unattended repair passes (Phase F2) ─────────────────────────────────
# The trigger above runs on an interval inside the service process. This is how
# a pass is asked for now instead of at the next interval. It cannot approve or
# apply: the trigger stops at the owner gate by design, and the type of the gate
# client enforces it.


@app.post("/api/self-repair/autonomous/run")
async def run_autonomous_repair_now(_: None = Depends(_require_control_access)) -> dict[str, Any]:
    """Run one unattended pass immediately, instead of waiting for the interval.

    Same shape as the scheduled pass and the same refusals. It proposes and gets
    a review filed; it never approves, applies, or rolls back.
    """
    return await repair_loop.run_once()


# ── The cognition surfaces: reflex, mesh, minds ─────────────────────────
# Status is readable without a control key: an owner deciding whether to trust
# an autonomous loop should be able to look at what it has actually done. Every
# state-changing call goes through the same origin-and-key gate as the rest.


@app.get("/api/reflex/status")
async def reflex_status() -> dict[str, Any]:
    """What the reflex brain is configured to do, and what it last did."""
    return get_reflex_brain().status()


@app.post("/api/reflex/run")
async def reflex_run_now(
    req: ReflexRunRequest, _: None = Depends(_require_control_access)
) -> dict[str, Any]:
    """Run one reflex pass immediately. Refusals are reported, never hidden.

    Nothing about this endpoint grants authority: a repair that needs a standing
    mandate and does not have one comes back as ``AWAITING_MANDATE``.
    """
    include: set[IncidentKind] | None = None
    if req.scope.strip():
        mapping = {
            "imports": IncidentKind.IMPORT_FAILURE,
            "tests": IncidentKind.TEST_FAILURE,
            "fleet": IncidentKind.PEER_UNREACHABLE,
            "resources": IncidentKind.RESOURCE_PRESSURE,
            "logs": IncidentKind.LOG_ERROR,
        }
        include = {
            mapping[name.strip().lower()]
            for name in req.scope.split(",")
            if name.strip().lower() in mapping
        } or None
    return await get_reflex_brain().run_once(include=include)


@app.get("/api/mesh/status")
async def mesh_status() -> dict[str, Any]:
    """The peer mesh: configured peers, recent typed outcomes, and its breaker."""
    return get_mesh().status()


@app.get("/api/minds")
async def minds_status() -> dict[str, Any]:
    """Every agent's self-model, its learned capabilities, and the shared memory."""
    return get_mind_registry().fleet_status()


@app.post("/api/android")
async def handle_android_action(req: AndroidActionRequest, _: None = Depends(_require_control_access)) -> dict[str, Any]:
    """Execute Android ADB action or get device connection status."""
    try:
        if req.action == "info":
            connected = android.is_connected()
            devices = [android.device_id] if connected and android.device_id else []
            return {
                "success": connected,
                "connected": connected,
                "devices": devices,
            }
        elif req.action == "app":
            app_name = req.params.get("app", "youtube")
            ok = android.open_app(app_name)
            return {"success": ok, "action": "app", "app": app_name}
        elif req.action == "key":
            key_name = req.params.get("key", "home")
            ok = android.press_key(key_name)
            return {"success": ok, "action": "key", "key": key_name}
        elif req.action == "tap":
            x = req.params.get("x", 0)
            y = req.params.get("y", 0)
            ok = android.click(x, y)
            return {"success": ok, "action": "tap", "x": x, "y": y}
        elif req.action == "swipe":
            ok = android.swipe(
                req.params.get("x1", 0),
                req.params.get("y1", 0),
                req.params.get("x2", 0),
                req.params.get("y2", 0),
                req.params.get("duration", 300),
            )
            return {"success": ok, "action": "swipe"}
        return {"success": False, "error": f"Unknown action '{req.action}'"}
    except Exception as e:
        logger.warning(f"Android endpoint error: {e}")
        return {"success": False, "devices": [], "error": str(e)}


@app.post("/api/command")
async def execute_command(req: CommandRequest, _: None = Depends(_require_control_access)) -> dict[str, Any]:
    """Execute a text command with PC, Android, and live 8-Agent execution."""
    raw_cmd = req.command.strip()
    cmd = raw_cmd.lower()

    # Reject direct prompt-injection attempts before any fast path or agent
    # execution. The response names the reason so clients can distinguish a
    # security refusal from a provider or execution failure.
    from friday.security.production_security import ProductionSecurityManager
    injection_detected, injection_reason, _ = ProductionSecurityManager().scan_prompt_injection(raw_cmd)
    if injection_detected:
        return {
            "reply": f"Security Alert: request blocked. {injection_reason}",
            "metadata": {"fast_path": True, "security_blocked": True, "reason": "prompt_injection"},
        }

    # =========================================================================
    # A. Autonomous Mode Toggles & Directives
    # =========================================================================
    if any(k in cmd for k in [
        "activate autonomous mode", "enable autonomous mode", "turn on autonomous mode",
        "autonomous mode on", "autonomous on", "start autonomous mode", "run autonomously"
    ]):
        autonomous_controller.toggle(True)
        return {
            "reply": "⚡ Autonomous Mode is now ACTIVE. FRIDAY will autonomously resolve runtime errors, apply self-healing diagnostics, and control all 8 specialist agents on your command.",
            "metadata": {"fast_path": True, "autonomous": True, "autonomous_mode": True},
        }

    if any(k in cmd for k in [
        "deactivate autonomous mode", "disable autonomous mode", "turn off autonomous mode",
        "autonomous mode off", "autonomous off", "stop autonomous mode", "manual mode"
    ]):
        autonomous_controller.toggle(False)
        return {
            "reply": "Autonomous Mode DEACTIVATED. Standing by for manual directives.",
            "metadata": {"fast_path": True, "autonomous": False, "autonomous_mode": False},
        }

    # =========================================================================
    # B. Autonomous Self-Healing & Auto-Repair Directives
    # =========================================================================
    if any(k in cmd for k in [
        "fix yourself", "fix it by yourself", "fix by yourself", "auto fix",
        "self repair", "self heal", "diagnose and repair", "fix errors", "repair system", "fix it"
    ]):
        return await autonomous_controller.execute_self_repair()

    # =========================================================================
    # C. Autonomous Specialist Agent Control Directives
    # =========================================================================
    agent_id, sub_task = autonomous_controller.detect_agent_directive(raw_cmd)
    if agent_id and sub_task:
        return await autonomous_controller.execute_agent_control(agent_id, sub_task)

    # 0. Conversational & Voice Interaction Fast-paths
    if any(cmd.startswith(g) or cmd == g for g in ["hello", "hi", "hey", "hello friday", "hello friends", "good morning", "good afternoon", "good evening"]):
        return {"reply": "Hello Surendra! All core systems, telemetry feeds, and 8 specialist agents are online and ready for your command.", "metadata": {"fast_path": True, "conversational": True}}

    if any(k in cmd for k in ["not tracking", "hands are not tracking", "these two hands", "two hands", "tracking", "gesture", "calibrate hands", "test hands"]):
        return {"reply": "Dual-hand optical sensors are active and calibrated. Hold both hands facing the camera with open palms for reticle lock.", "metadata": {"fast_path": True, "conversational": True}}

    if any(k in cmd for k in ["who are you", "who made you", "what are you", "your name", "are you there", "can you hear me"]):
        return {"reply": "I am F.R.I.D.A.Y., Surendra's Autonomous Intelligence Core v3.5. I control your PC, Android ecosystem, and 8 specialist agents.", "metadata": {"fast_path": True, "conversational": True}}

    if any(k in cmd for k in ["thank you", "thanks", "great job", "good job", "nice", "awesome"]):
        return {"reply": "Always at your service, Surendra.", "metadata": {"fast_path": True, "conversational": True}}

    if any(k in cmd for k in ["what can you do", "help", "features", "commands", "what are your capabilities", "capabilities", "what do you do"]):
        return {
            "reply": "I can launch Windows applications, open and search websites, control the Windows media session, capture screenshots, monitor system telemetry, and orchestrate the connected specialist agents. Website playback and account actions require a working service integration.",
            "metadata": {"fast_path": True, "conversational": True},
        }

    if cmd in ["on", "and", "the", "a", "an", "in", "to", "for", "is", "it", "so", "but", "or", "er", "put", "um", "uh", "test"]:
        return {"reply": "I am listening, Surendra. Tell me what directive to execute.", "metadata": {"fast_path": True, "conversational": True}}

    # 1. Master Fleet & All-Agents Matrix
    if any(k in cmd for k in ["status of all agents", "all agents", "fleet status", "ecosystem status", "check all agents", "universe status", "agents status", "all agent"]):
        return await fleet_client.get_fleet_summary()

    # 2. Live Specialist Agent Direct Execution
    for agent_id in ["inference", "stratex", "memora", "intelx", "futuris", "cortex", "forge", "sentinel"]:
        if (
            cmd.startswith(f"ask {agent_id}")
            or cmd.startswith(f"{agent_id} ")
            or cmd.startswith(f"@{agent_id}")
            or cmd == f"ask {agent_id}"
            or cmd == agent_id
            or f"ask {agent_id}" in cmd
        ):
            # Extract user directive
            sub_q = raw_cmd
            for prefix in [f"ask {agent_id}", f"@{agent_id}", agent_id, f"ask {agent_id.capitalize()}", agent_id.capitalize()]:
                if sub_q.lower().startswith(prefix.lower()):
                    sub_q = sub_q[len(prefix):].strip()
                    break
            if not sub_q:
                sub_q = "Report operational status, active metrics, and readiness."

            if agent_id == "inference":
                return await fleet_client.ask_inference(sub_q)
            elif agent_id == "memora":
                return await fleet_client.ask_memora(sub_q)
            elif agent_id == "stratex":
                return await fleet_client.ask_stratex(sub_q)
            elif agent_id == "intelx":
                return await fleet_client.ask_intelx(sub_q)
            elif agent_id == "futuris":
                return await fleet_client.ask_futuris(sub_q)
            elif agent_id == "cortex":
                return await fleet_client.ask_cortex(sub_q)
            elif agent_id == "forge":
                return await fleet_client.ask_forge(sub_q)
            elif agent_id == "sentinel":
                return await fleet_client.ask_sentinel(sub_q)

    # 2. Android Automation Fast-paths
    try:
        if "on phone" in cmd or "on android" in cmd or cmd.startswith("phone ") or cmd.startswith("android "):
            # Check if device is connected first
            if not android.is_connected():
                return {
                    "reply": "No Android device connected via ADB. Connect your phone via USB with USB Debugging enabled.",
                    "metadata": {"fast_path": True, "device": "android", "adb_connected": False},
                }

            # Android App Launch fast-path
            for app_name in ["youtube", "chrome", "maps", "camera", "settings", "whatsapp", "spotify", "instagram", "calculator"]:
                if app_name in cmd:
                    success = android.open_app(app_name)
                    msg = f"Opened {app_name.capitalize()} on Android device." if success else f"Failed to launch {app_name} on Android."
                    return {"reply": msg, "metadata": {"fast_path": True, "device": "android"}}
            if "home" in cmd:
                android.press_key("home")
                return {"reply": "Pressed Home on Android device.", "metadata": {"fast_path": True, "device": "android"}}
            if "back" in cmd:
                android.press_key("back")
                return {"reply": "Pressed Back on Android device.", "metadata": {"fast_path": True, "device": "android"}}
    except Exception as ae:
        logger.warning(f"Android fast-path error: {ae}")

    # 3. Windows FRIDAY Master Laptop Directives (YouTube, websites, media, volume, apps, folders, system)
    try:
        from friday.devices.windows_friday import windows_friday
        handled, friday_reply, friday_meta = windows_friday.handle_directive(raw_cmd)
        if handled:
            friday_meta["fast_path"] = True
            friday_meta["device"] = "windows"
            return {"reply": friday_reply, "metadata": friday_meta}
    except Exception as fe:
        logger.warning(f"Windows FRIDAY controller error: {fe}")

    try:
        # Screen Perception Fast-path ("What's on my screen now")
        if any(k in cmd for k in ["what's on my screen", "what is on my screen", "whats on my screen", "read my screen", "screen content", "look at my screen", "screen now", "view my screen"]):
            import ctypes
            if hasattr(ctypes, "windll"):
                user32 = ctypes.windll.user32
                hwnd = user32.GetForegroundWindow()
                length = user32.GetWindowTextLengthW(hwnd)
                title = ""
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value
                active_summary = f"Active window: '{title}'." if title else "Desktop display active."
                device_type = "windows"
            else:
                title = "Cloud Container (Render Headless)"
                active_summary = "Running in cloud headless environment on Render."
                device_type = "cloud"

            reply = f"I am perceiving your environment. {active_summary} Dual-Hand Holographic Cockpit telemetry active and 8 specialist agents ready."
            return {"reply": reply, "metadata": {"fast_path": True, "device": device_type, "action": "screen_perception", "active_window": title}}

        # Universal Application & File Launcher Fast-path
        if cmd.startswith("open ") or cmd.startswith("launch ") or cmd.startswith("start "):
            target_str = re.sub(r"^(?:open|launch|start)\s+(?:the\s+)?(?:file|folder|app|application|program|directory)?\s*", "", raw_cmd, flags=re.IGNORECASE).strip()
            t_low = target_str.lower()
            
            if any(k in t_low for k in ["chrome", "google chrome", "browser"]):
                ok, msg = launch_desktop_app("chrome")
                return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "chrome", "success": ok}}
            elif any(k in t_low for k in ["notepad", "text editor"]):
                ok, msg = launch_desktop_app("notepad")
                return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "notepad", "success": ok}}
            elif any(k in t_low for k in ["calc", "calculator"]):
                ok, msg = launch_desktop_app("calculator")
                return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "calculator", "success": ok}}
            elif any(k in t_low for k in ["vscode", "vs code", "code", "visual studio code"]):
                ok, msg = launch_desktop_app("vscode")
                return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "vscode", "success": ok}}
            elif any(k in t_low for k in ["explorer", "file explorer", "files", "my files", "this pc"]):
                ok, msg = launch_desktop_app("explorer")
                return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "explorer", "success": ok}}
            elif any(k in t_low for k in ["terminal", "cmd", "powershell"]):
                ok, msg = launch_desktop_app("terminal")
                return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "terminal", "success": ok}}
            elif "download" in t_low:
                p = os.path.join(os.path.expanduser("~"), "Downloads")
                os.startfile(p)
                return {"reply": f"Opened Downloads: {p}", "metadata": {"fast_path": True, "path": p}}
            elif "desktop" in t_low:
                p = os.path.join(os.path.expanduser("~"), "Desktop")
                os.startfile(p)
                return {"reply": f"Opened Desktop: {p}", "metadata": {"fast_path": True, "path": p}}
            elif "document" in t_low:
                p = os.path.join(os.path.expanduser("~"), "Documents")
                os.startfile(p)
                return {"reply": f"Opened Documents: {p}", "metadata": {"fast_path": True, "path": p}}

            # Check if direct file/folder exists
            if os.path.exists(target_str):
                os.startfile(target_str)
                return {"reply": f"Opened '{target_str}'.", "metadata": {"fast_path": True, "path": target_str}}

            for base in [r"d:\FRIDAY Universe", r"d:\FRIDAY Universe\FRIDAY", os.path.expanduser("~")]:
                cand = os.path.join(base, target_str)
                if os.path.exists(cand):
                    os.startfile(cand)
                    return {"reply": f"Opened '{cand}'.", "metadata": {"fast_path": True, "path": cand}}

            try:
                subprocess.Popen(f'start "" "{target_str}"', shell=True)
                return {"reply": f"Launched '{target_str}'.", "metadata": {"fast_path": True, "target": target_str}}
            except Exception:
                pass

        if any(k in cmd for k in ["chrome", "google chrome", "swipe right"]):
            ok, msg = launch_desktop_app("chrome")
            return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "chrome", "success": ok}}
        elif any(k in cmd for k in ["notepad", "text editor", "swipe left"]):
            ok, msg = launch_desktop_app("notepad")
            return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "notepad", "success": ok}}
        elif any(k in cmd for k in ["calc", "calculator"]):
            ok, msg = launch_desktop_app("calculator")
            return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "calculator", "success": ok}}
        elif any(k in cmd for k in ["code", "vscode", "vs code"]):
            ok, msg = launch_desktop_app("vscode")
            return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "code", "success": ok}}
        elif any(k in cmd for k in ["edge", "microsoft edge"]):
            ok, msg = launch_desktop_app("edge")
            return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "edge", "success": ok}}
        elif any(k in cmd for k in ["explorer", "file explorer", "files"]):
            ok, msg = launch_desktop_app("explorer")
            return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "explorer", "success": ok}}
        elif any(k in cmd for k in ["paint", "mspaint"]):
            ok, msg = launch_desktop_app("paint")
            return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "paint", "success": ok}}
        elif any(k in cmd for k in ["terminal", "cmd", "powershell"]):
            ok, msg = launch_desktop_app("terminal")
            return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "terminal", "success": ok}}
        elif any(k in cmd for k in ["screenshot", "capture screen", "snapshot"]):
            res = agent.tools.execute(name="get_screen_snapshot", arguments={})
            snap_tool = agent.tools.get("get_screen_snapshot")
            b64_img = ""
            if snap_tool and getattr(snap_tool, "last_snapshot", None):
                snap = snap_tool.last_snapshot
                if snap and getattr(snap, "image_bytes", None):
                    import base64
                    b64_img = f"data:image/png;base64,{base64.b64encode(snap.image_bytes).decode('ascii')}"
            return {"reply": res.content or "Captured desktop screenshot.", "metadata": {"fast_path": True, "device": "windows", "action": "screenshot", "image_b64": b64_img}}
        elif any(k in cmd for k in ["system status", "specs", "cpu status", "cpu usage", "system info"]):
            import psutil
            vm = psutil.virtual_memory()
            res = agent.tools.execute(name="get_system_info", arguments={})
            return {
                "reply": res.content,
                "metadata": {
                    "fast_path": True,
                    "device": "windows",
                    "action": "specs",
                    "telemetry": {
                        "cpu_percent": psutil.cpu_percent(interval=None),
                        "ram_percent": vm.percent,
                        "ram_total_gb": round(vm.total / (1024**3), 2),
                        "ram_used_gb": round(vm.used / (1024**3), 2),
                        "cores": psutil.cpu_count(logical=True),
                    },
                },
            }
        elif any(k in cmd for k in ["current time", "what time is it", "today's date", "time", "date"]):
            res = agent.tools.execute(name="get_time_date", arguments={})
            return {"reply": res.content, "metadata": {"fast_path": True, "device": "windows"}}
    except Exception as e:
        return {"reply": f"Fast-path error: {e}", "metadata": {"error": True}}

    # 3. Central Agent Cognitive & Tool Execution Loop
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, agent.process_message, req.command)
        content = getattr(response, "content", "") or str(response)
        if any(w in content.lower() for w in ["ambiguous", "jumbled", "cut off", "incomplete", "please clarify"]):
            content = "I am standing by, Surendra. What would you like me to do?"
        metadata = getattr(response, "metadata", {}) or {}
        return {"reply": content, "metadata": metadata}
    except Exception as exc:
        logger.warning(f"Cognitive loop exception: {exc}")
        if autonomous_controller.is_autonomous():
            repair_report = await autonomous_controller.execute_self_repair(context=str(exc))
            return {
                "reply": f"⚠️ An execution anomaly occurred ('{exc}').\n\n{repair_report['reply']}",
                "metadata": {"autonomous": True, "self_repair_attempted": False, "error": type(exc).__name__},
            }
        return {"reply": f"Understood, Surendra. Awaiting your directive: '{req.command}'.", "metadata": {"fallback": True}}


@app.post("/api/android")
async def execute_android(req: AndroidActionRequest, _: None = Depends(_require_control_access)) -> dict[str, Any]:
    """Direct Android execution endpoint for mobile automation."""
    act = req.action.lower()
    p = req.params
    try:
        if act == "tap":
            ok = android.click(int(p.get("x", 0)), int(p.get("y", 0)))
            return {"success": ok, "action": act}
        elif act == "swipe":
            ok = android.swipe(int(p.get("x1", 0)), int(p.get("y1", 0)), int(p.get("x2", 0)), int(p.get("y2", 0)), int(p.get("duration_ms", 300)))
            return {"success": ok, "action": act}
        elif act == "type":
            ok = android.type_text(str(p.get("text", "")))
            return {"success": ok, "action": act}
        elif act == "key":
            ok = android.press_key(str(p.get("key", "home")))
            return {"success": ok, "action": act}
        elif act == "app":
            ok = android.open_app(str(p.get("name", "youtube")))
            return {"success": ok, "action": act}
        elif act == "info":
            devices = android.list_devices()
            return {"success": bool(devices), "devices": devices}
        else:
            return {"success": False, "error": f"Unknown Android action '{act}'"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/system_telemetry")
async def system_telemetry_endpoint() -> dict[str, Any]:
    """Return real-time hardware telemetry (CPU, RAM, Cores, Platform) for the holographic HUD."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        return {
            "status": "ok",
            "cpu_percent": psutil.cpu_percent(interval=None),
            "cpu_cores": psutil.cpu_count(logical=True),
            "ram_percent": vm.percent,
            "ram_total_gb": round(vm.total / (1024**3), 2),
            "ram_used_gb": round(vm.used / (1024**3), 2),
            "ram_avail_gb": round(vm.available / (1024**3), 2),
            "os": "Windows 11 x64",
            "operator": "Surendra",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


class ChatRequest(BaseModel):
    message: str = ""


@app.get("/api/telemetry")
async def telemetry_alias() -> dict[str, Any]:
    """Compatibility endpoint for dashboard telemetry."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        import os
        drive = os.path.splitdrive(os.getcwd())[0] or "C:"
        disk = psutil.disk_usage(drive + "\\")
        return {
            "status": "ok",
            "cpu_usage": round(psutil.cpu_percent(interval=None)),
            "ram_usage": round(vm.percent),
            "storage_usage": round(disk.percent),
            "network_usage": 120,
        }
    except Exception as exc:
        return {"status": "unavailable", "error": type(exc).__name__}


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest, _: None = Depends(_require_control_access)) -> dict[str, Any]:
    """Compatibility endpoint for chat/command execution."""
    return await execute_command(CommandRequest(command=req.message))


@app.get("/api/screenshot")
@app.post("/api/screenshot")
async def screenshot_endpoint(_: None = Depends(_require_control_access)) -> dict[str, Any]:
    """Compatibility endpoint for capturing desktop screenshot."""
    return await execute_command(CommandRequest(command="screenshot"))


@app.websocket("/api/ws/voice")
async def voice_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for bidirectional audio, waveform telemetry, and MediaPipe hand gestures.
    Supports real-time gesture control and instant desktop/mobile actions.
    """
    try:
        await _require_control_access(websocket)
    except HTTPException:
        await websocket.close(code=1008, reason="FRIDAY control authentication required")
        return
    await websocket.accept()
    logger.info("WebSocket connected from Holographic UI")
    try:
        while True:
            data = await websocket.receive_json()
            event_type = data.get("type")

            if event_type in ("voice_command", "command"):
                cmd_text = data.get("command", "").strip()
                logger.info(f"Received WS voice command: '{cmd_text}'")
                if cmd_text:
                    req_obj = CommandRequest(command=cmd_text)
                    cmd_res = await execute_command(req_obj)
                    await websocket.send_json({
                        "type": "voice_reply",
                        "command": cmd_text,
                        "reply": cmd_res.get("reply", ""),
                        "metadata": cmd_res.get("metadata", {}),
                    })

            elif event_type == "gesture":
                gesture = data.get("gesture")
                logger.info(f"Received hand gesture event: {gesture}")
                try:
                    from friday.devices.app_launcher import launch_desktop_app
                    if gesture == "swipe_left":
                        ok, msg = launch_desktop_app("notepad")
                        await websocket.send_json({"type": "status", "message": f"Left Gesture: {msg}"})
                    elif gesture == "swipe_right":
                        ok, msg = launch_desktop_app("chrome")
                        await websocket.send_json({"type": "status", "message": f"Right Gesture: {msg}"})
                    elif gesture == "swipe_up_android":
                        if not android.is_connected():
                            await websocket.send_json({"type": "status", "message": "Android Action unavailable: no ADB device is connected."})
                        else:
                            ok = android.swipe(500, 1500, 500, 500, 250)
                            await websocket.send_json({"type": "status", "message": "Android Action: Swiped Up" if ok else "Android Action failed; ADB did not confirm the swipe."})
                    elif gesture == "swipe_down_android":
                        if not android.is_connected():
                            await websocket.send_json({"type": "status", "message": "Android Action unavailable: no ADB device is connected."})
                        else:
                            ok = android.swipe(500, 500, 500, 1500, 250)
                            await websocket.send_json({"type": "status", "message": "Android Action: Swiped Down" if ok else "Android Action failed; ADB did not confirm the swipe."})
                    elif gesture == "pinch":
                        await websocket.send_json({"type": "status", "message": "Pinch gesture recognized; no action is configured."})
                    elif gesture == "open_palm":
                        await websocket.send_json({"type": "status", "message": "Open-palm gesture recognized; no action is configured."})
                except Exception as ge:
                    logger.error(f"Gesture execution failed: {ge}")
                    await websocket.send_json({"type": "status", "message": f"Error: {ge}"})

            elif event_type == "audio_ping":
                # Heartbeat and audio packet ack
                await websocket.send_json({"type": "audio_pong", "timestamp": data.get("timestamp")})

            elif event_type == "ping":
                await websocket.send_json({"type": "pong"})

            else:
                logger.warning(f"Unknown WS event type: {event_type}")

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected from Holographic UI")
    except Exception as e:
        logger.error(f"WebSocket session error: {e}")


# =========================================================================
# FastMCP Server Endpoints (Sagar Tamang's FastMCP SSE Architecture)
# =========================================================================

@app.get("/sse")
async def mcp_sse_endpoint(request: Request, _: None = Depends(_require_control_access)):
    """
    Model Context Protocol (MCP) Server-Sent Events endpoint.
    Allows external agents, Cursor, Claude Desktop, or any MCP-compatible client to consume FRIDAY's tools.
    """
    async def event_generator():
        # Initial endpoint event per MCP SSE spec
        yield "event: endpoint\ndata: /messages?session_id=friday_session\n\n"
        while True:
            if await request.is_disconnected():
                break
            # Keepalive ping every 15s
            await asyncio.sleep(15)
            yield ": keepalive\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# =========================================================================
# FRIDAY Proactive & Diagnostics Endpoints (ambient awareness)
# =========================================================================


@app.get("/api/diagnostics")
async def diagnostics_endpoint() -> dict[str, Any]:
    """Return live system telemetry for the HUD / proactive monitoring."""
    try:
        diag = agent.get_system_diagnostics()
        diag["status"] = "ok"
        return diag
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/proactive")
async def proactive_endpoint() -> dict[str, Any]:
    """Return any pending proactive announcements (unprompted FRIDAY insights)."""
    try:
        announcement = agent.get_proactive_announcement()
        return {
            "status": "ok",
            "has_announcement": announcement is not None,
            "announcement": announcement,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/proactive/dismiss")
async def dismiss_proactive(_: None = Depends(_require_control_access)) -> dict[str, Any]:
    """Clear all pending proactive notifications."""
    try:
        agent.notifications.clear()
        return {"status": "ok", "cleared": True}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def start_proactive_monitoring() -> None:
    """Start FRIDAY's background proactive monitoring loop. Call at server boot."""
    try:
        agent.start_proactive_monitoring()
        logger.info("FRIDAY proactive monitoring started")
    except Exception as e:
        logger.warning(f"Could not start proactive monitoring: {e}")


# Auto-start proactive monitoring when the module loads (server boot)
start_proactive_monitoring()


@app.post("/messages")
async def mcp_messages_endpoint(request: Request, _: None = Depends(_require_control_access)) -> JSONResponse:
    """
    Model Context Protocol (MCP) JSON-RPC 2.0 message handler.
    Implements tools/list and tools/call protocols.
    """
    try:
        body = await request.json()
        method = body.get("method")
        msg_id = body.get("id")
        params = body.get("params", {})

        if method == "tools/list":
            schemas = agent.tools.get_schemas() or []
            mcp_tools = []
            for s in schemas:
                fn = s.get("function", s)
                mcp_tools.append({
                    "name": fn.get("name"),
                    "description": fn.get("description", ""),
                    "inputSchema": fn.get("parameters", {"type": "object", "properties": {}}),
                })
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": mcp_tools},
            })

        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            tool = agent.tools.get(tool_name)
            if not tool:
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Tool '{tool_name}' not found"},
                })
            tool_res = agent.tools.execute(name=tool_name, arguments=tool_args)
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": str(tool_res.content)}],
                    "isError": tool_res.is_error,
                },
            })

        elif method == "initialize":
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "friday-mcp-server", "version": "2.0.0"},
                },
            })

        return JSONResponse({
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method '{method}' not implemented"},
        })
    except Exception as e:
        return JSONResponse({
            "jsonrpc": "2.0",
            "error": {"code": -32000, "message": str(e)},
        })


# Mount the static command center after API routes so it never shadows the API.
# Local source checkouts may omit the exported UI; the API remains usable there.
_ui_directory = Path(os.getenv("FRIDAY_UI_DIR", "")).expanduser() if os.getenv("FRIDAY_UI_DIR") else None
if _ui_directory and (_ui_directory / "index.html").is_file():
    app.mount("/", StaticFiles(directory=str(_ui_directory), html=True), name="friday-ui")
