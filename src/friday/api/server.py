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
import hashlib
import hmac
import json
import ipaddress
import logging
import os
import re
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from friday.core.startup_validator import validate_runtime_environment
from friday.core.cache import TTLCache, ttl_cached
from friday.core.resilience import safe_peer_call

from friday.agent.agent import FridayAgent
from friday.cli.auth import CLIAuthorizer
from friday.core.auth import DefaultSecureAuthorizer
from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.devices.android_controller import AndroidDeviceController
from friday.devices.app_launcher import launch_desktop_app
from friday.ecosystem.fleet_client import fleet_client, CANONICAL_INTERNAL_MESH_URLS
from friday.memory.event_consumer import MemoraEventConsumer
from friday.memory.memora_client import memora_client
from friday.api.companion_ws import companion_multiplexer
from friday.api.activity_stream import register as register_activity_client, unregister as unregister_activity_client
from friday.remote.laptop_bridge import (
    ALLOWED_LAPTOP_COMMANDS,
    LaptopBridgeTimeout,
    LaptopDisconnected,
    LaptopNotConnected,
    laptop_bridge,
    normalise_laptop_id,
    shell_execution_enabled,
)
from friday.autonomous import autonomous_controller, autonomous_daemon, enhanced_controller
from friday.autonomous.repair_loop import repair_loop
from friday.cognition.reflex import get_reflex_brain, parse_incident_scope
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
    # Pre-flight environment validation
    is_prod = os.getenv("FRIDAY_ENV", "").lower() == "production"
    validate_runtime_environment(fail_fast=is_prod)
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
        logger.info("Graceful shutdown initiated: stopping background tasks and listener loops...")
        background_tasks = [repair_task, supervision_task, memora_task, reflex_task, memory_mirror_task]
        for task in (repair_task, supervision_task, memora_task, reflex_task, memory_mirror_task):
            task.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*background_tasks, return_exceptions=True),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Background tasks cancellation timed out after 5.0 seconds")
        except Exception as e:
            logger.debug(f"Exception during background task cancellation: {e}")

        try:
            await asyncio.wait_for(fleet_client.aclose(), timeout=3.0)
        except Exception:
            logger.exception("Failed to close the shared fleet HTTP client during shutdown")
        logger.info("Graceful shutdown completed.")

app = FastAPI(
    title="FRIDAY Holographic Core & FastMCP Server",
    description="Multi-modal AI assistant server supporting WebGL Hologram, MediaPipe gestures, Android ADB control, and FastMCP.",
    version="2.0.0",
    lifespan=lifespan,
)

# Request correlation ID tracking middleware
class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

app.add_middleware(RequestContextMiddleware)

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    from friday.security.scrubber import redact_secrets
    clean_msg = redact_secrets(str(exc.detail))
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": f"HTTP_{exc.status_code}",
            "message": clean_msg,
            "detail": clean_msg,
            "success": False,
        },
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    from friday.security.scrubber import redact_secrets
    clean_msg = redact_secrets(str(exc))
    return JSONResponse(
        status_code=422,
        content={
            "error": "VALIDATION_ERROR",
            "message": clean_msg,
            "detail": clean_msg,
            "success": False,
        },
    )

@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    from friday.security.scrubber import redact_secrets
    clean_msg = redact_secrets(str(exc))
    logger.exception("Unhandled server exception: %s", clean_msg)
    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_SERVER_ERROR",
            "message": clean_msg or "An internal error occurred",
            "detail": clean_msg or "An internal error occurred",
            "success": False,
        },
    )

# Allow the command centre to connect without ever reflecting an untrusted origin.
# `allow_origins=["*"]` cannot be combined with credentials and Starlette resolves
# the pair by echoing whatever origin asked. The list below is explicit; the
# authoritative gate for state-changing calls is `_origin_allowed` in
# `_require_control_access`, which also covers WebSocket upgrades that CORS
# middleware does not police.
def _configured_origins() -> list[str]:
    raw = getattr(get_settings(), "allowed_origins", "") or ""
    configured = {item.strip().rstrip("/") for item in raw.split(",") if item.strip()}
    guaranteed = {
        "https://friday-universe.duckdns.org",
        "http://localhost:10000",
        "http://127.0.0.1:10000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    }
    return sorted(configured | guaranteed)


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

# Static files for the FRIDAY dashboard (orb, voice, fleet, flow)
app.mount("/static", StaticFiles(directory="src/friday/api"), name="static")

@app.middleware("http")
async def _dashboard_cache_headers(request: Request, call_next):
    """Make a redeploy impossible to miss.

    The dashboard is a static export whose chunk names are content-stable but not
    content-addressed. Without an explicit policy the browser is free to reuse a
    previously cached ``index.html``, which keeps pointing at the old chunk list
    -- the user then "does not see" changes that are live on the server. HTML is
    therefore always revalidated, while the immutable chunks keep a long cache.
    """
    response = await call_next(request)
    path = request.url.path
    if "/_next/static/" in path:
        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    elif response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


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


_CONTROL_TOKEN_TTL_SECONDS = 20 * 60
_CONTROL_TOKEN_PREFIX = "fcs1"


def _control_secret() -> str:
    """The control API key in force now, or ``""`` when none is configured.

    The environment variable is consulted before the cached Settings object for
    the same reason :func:`_require_control_access` does it: authorisation must
    reflect the configuration in force now.
    """
    live = _live_settings()
    return (
        os.getenv("FRIDAY_API_KEY")
        or getattr(live, "api_key", None)
        or os.getenv("FRIDAY_UNIVERSE_API_KEY")
        or ""
    ).strip()


def _control_secret_is_usable(secret: str) -> bool:
    return bool(secret) and secret.lower() not in {
        "friday_universe_api",
        "changeme",
        "change-me",
        "your_api_key",
    }


def _mint_control_token(secret: str) -> tuple[str, int]:
    """Mint a short-lived, origin-scoped control token.

    The owner's browser cannot read the server-side API key, and asking them to
    paste it into the dashboard is both hostile and error-prone. Instead the
    dashboard asks this same API for a token over the already-authenticated
    same-origin channel; the token is an HMAC over an expiry, so it can only have
    been produced by a process holding the key, and it stops working when the
    key rotates or the TTL elapses.
    """
    expires = int(time.time()) + _CONTROL_TOKEN_TTL_SECONDS
    payload = f"{_CONTROL_TOKEN_PREFIX}.{expires}"
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}", expires


def _control_token_valid(token: str, secret: str) -> bool:
    parts = (token or "").strip().split(".")
    if len(parts) != 3 or parts[0] != _CONTROL_TOKEN_PREFIX:
        return False
    try:
        expires = int(parts[1])
    except ValueError:
        return False
    if expires < int(time.time()):
        return False
    payload = f"{parts[0]}.{parts[1]}"
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(parts[2], expected)


async def _require_control_access(request: Request) -> None:
    """Authorise a control HTTP request.

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
    # Origin check
    origin = request.headers.get("origin", "").strip()
    if not _origin_allowed(origin, request):
        raise HTTPException(
            status_code=403,
            detail=(
                "This browser origin is not permitted to reach the FRIDAY control API. "
                "Add it to FRIDAY_ALLOWED_ORIGINS if it is a trusted frontend."
            ),
        )

    # Client IP check
    client_host = request.client.host if request.client else ""
    client_is_remote = False
    try:
        client_is_remote = not ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        pass
    remotely_exposed = bool(os.getenv("RENDER") or client_is_remote)
    live = _live_settings()
    http_method = request.method.upper()
    loopback_hardening = bool(
        getattr(live, "require_api_key_on_loopback", False)
        and http_method not in _IDEMPOTENT_METHODS
    )
    if not remotely_exposed and not loopback_hardening:
        return

    # The live environment variable is consulted before the cached Settings
    # object on purpose: this gate documents that authorisation reflects the
    # configuration "in force now", and pydantic captures a Settings snapshot
    # at construction time. An operator (or a test) that (re)sets the variable
    # after the process built its Settings must be honoured, and on Render the
    # two agree anyway, so this order changes nothing in production.
    expected = _control_secret()
    if not _control_secret_is_usable(expected):
        raise HTTPException(status_code=503, detail="Remote control is disabled until a non-example FRIDAY_API_KEY is configured.")

    # Check for API key in headers
    provided = request.headers.get("x-friday-api-key", "")
    authorization = request.headers.get("authorization", "")
    if not provided and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    if provided and hmac.compare_digest(provided, expected):
        return

    # Check for session token: header or cookie
    session_token = request.headers.get("x-friday-control-token", "")
    if not session_token:
        cookies = getattr(request, "cookies", {})
        if isinstance(cookies, dict):
            session_token = cookies.get("friday_control_token", "")

    if session_token and _control_token_valid(session_token, expected):
        return

    raise HTTPException(status_code=401, detail="A valid FRIDAY control API key is required.")


async def _require_control_access_ws(websocket: WebSocket) -> None:
    """Authorise a control WebSocket upgrade.

    For WebSocket upgrades, the token must be passed as a query parameter
    `?token=<control_token>` since browsers cannot send custom headers during
    the WebSocket handshake.
    """
    # Origin check
    origin = websocket.headers.get("origin", "").strip()
    if not _origin_allowed(origin, websocket):
        raise HTTPException(
            status_code=403,
            detail=(
                "This browser origin is not permitted to reach the FRIDAY control API. "
                "Add it to FRIDAY_ALLOWED_ORIGINS if it is a trusted frontend."
            ),
        )

    # Client IP check
    client_host = websocket.client.host if websocket.client else ""
    client_is_remote = False
    try:
        client_is_remote = not ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        pass
    remotely_exposed = bool(os.getenv("RENDER") or client_is_remote)
    live = _live_settings()
    # WebSocket doesn't have HTTP method; default to GET (idempotent) so loopback hardening doesn't apply
    loopback_hardening = bool(
        getattr(live, "require_api_key_on_loopback", False)
        and "GET" not in _IDEMPOTENT_METHODS
    )
    if not remotely_exposed and not loopback_hardening:
        return

    expected = _control_secret()
    if not _control_secret_is_usable(expected):
        raise HTTPException(status_code=503, detail="Remote control is disabled until a non-example FRIDAY_API_KEY is configured.")

    # Check for API key in headers
    provided = websocket.headers.get("x-friday-api-key", "")
    authorization = websocket.headers.get("authorization", "")
    if not provided and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    if provided and hmac.compare_digest(provided, expected):
        return

    # Check for session token: header, cookie, or query parameter (critical for WebSocket)
    session_token = websocket.headers.get("x-friday-control-token", "")
    if not session_token:
        cookies = getattr(websocket, "cookies", {})
        if isinstance(cookies, dict):
            session_token = cookies.get("friday_control_token", "")
    if not session_token and hasattr(websocket, "query_params"):
        query_params = websocket.query_params
        if hasattr(query_params, "get"):
            session_token = query_params.get("token", "")
        elif isinstance(query_params, dict):
            session_token = query_params.get("token", "")

    if session_token and _control_token_valid(session_token, expected):
        return

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


@app.get("/api/control/session")
async def control_session(request: Request) -> JSONResponse:
    """Mint a short-lived control token for the owner's dashboard.

    This is the only control surface that answers without a credential, and it is
    deliberately constrained:

    * the browser origin must already be allowed (:func:`_origin_allowed`), so a
      third-party page cannot read the token even if it calls the endpoint;
    * it fails closed with 503 when no usable ``FRIDAY_API_KEY`` is configured;
    * tokens expire, are HMAC-signed with the key, and are useless once the key
      rotates.

    The token is a control *capability*, not the key itself, so it never has to
    be pasted into a browser by the owner.
    """
    if not _origin_allowed(request.headers.get("origin", "").strip(), request):
        raise HTTPException(
            status_code=403,
            detail="This browser origin is not permitted to request a FRIDAY control session.",
        )
    secret = _control_secret()
    if not _control_secret_is_usable(secret):
        raise HTTPException(
            status_code=503,
            detail="Remote control is disabled until a non-example FRIDAY_API_KEY is configured.",
        )
    token, expires = _mint_control_token(secret)
    response = JSONResponse(
        {
            "status": "ok",
            "token": token,
            "expires_at": datetime.fromtimestamp(expires, tz=timezone.utc).isoformat(),
            "ttl_seconds": _CONTROL_TOKEN_TTL_SECONDS,
            "header": "X-FRIDAY-Control-Token",
        }
    )
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


class AgentTaskRequest(BaseModel):
    directive: str


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
    data = rep.as_dict()
    data["status"] = "healthy"
    data["service"] = "FRIDAY"
    data["agent"] = "FRIDAY"
    data["canonical_name"] = "FRIDAY"
    data["version"] = "2.0.0"
    data["peers_mesh"] = "connected"
    return data


@app.api_route("/ready", methods=["GET", "HEAD"])
@app.api_route("/api/ready", methods=["GET", "HEAD"])
async def readiness_check() -> JSONResponse:
    """Readiness probe verifying the configured database backend and disk space."""
    status: dict[str, Any] = {
        "status": "ready",
        "ready": True,
        "service": "FRIDAY",
        "agent": "FRIDAY",
        "canonical_name": "FRIDAY",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": "unavailable",
        "database_backend": "unconfigured",
        "mesh": "configured",
    }

    settings_obj = get_settings()
    dsn = getattr(settings_obj, "oracle_dsn", None)
    backend = "oracle" if dsn else "unconfigured"
    status["database_backend"] = backend

    db_status = "unavailable"
    if dsn:
        try:
            from sqlalchemy import text

            from friday.core.oracle import get_engine

            engine = get_engine(dsn)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1 FROM DUAL"))
            db_status = "connected"
        except Exception as exc:
            status["database_error"] = type(exc).__name__
    else:
        status["database_error"] = "NoOracleDSN"
    status["database"] = db_status
    if db_status != "connected":
        status["ready"] = False
        status["status"] = "not_ready"

    try:
        import shutil
        total, used, free = shutil.disk_usage(".")
        free_mb = free / (1024 * 1024)
        status["disk_free_mb"] = round(free_mb, 1)
        if free_mb < 50.0:
            status["ready"] = False
            status["status"] = "not_ready"
            status["disk"] = f"low_disk_space: {round(free_mb, 1)}MB"
        else:
            status["disk"] = "healthy"
    except Exception as exc:
        status["disk"] = f"unknown: {type(exc).__name__}"

    env_rep = validate_runtime_environment(fail_fast=False)
    if not env_rep["valid"]:
        status["ready"] = False
        status["status"] = "not_ready"
        status["environment_issues"] = env_rep["issues"]

    # Production readiness: non-Oracle backend must return 503
    is_prod = False
    try:
        env_str = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development"))
        is_prod = str(env_str).lower() == "production"
    except Exception:
        pass
    if is_prod and status.get("database_backend", "unconfigured") != "oracle" and status.get("ready", False):
        status["ready"] = False
        status["status"] = "not_ready"
        status["database_notice"] = f"Production requires Oracle backend; got {status.get('database_backend')}"

    status_code = 200 if status["ready"] else 503
    return JSONResponse(status_code=status_code, content=status)


@app.get("/metrics")
@app.get("/api/metrics")
async def metrics_endpoint() -> dict[str, Any]:
    """Return runtime observability metrics from friday_deep."""
    return default_metrics.snapshot()


@ttl_cached(ttl_seconds=2.0, maxsize=16)
def _sample_telemetry() -> dict[str, Any]:
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


@app.get("/api/telemetry")
@ttl_cached(ttl_seconds=2.0)
async def get_telemetry() -> dict[str, Any]:
    """Expose real-time hardware telemetry (CPU, RAM, Battery) for the UI with TTL caching."""
    return _sample_telemetry()


@ttl_cached(ttl_seconds=2.0, maxsize=16)
def _sample_system_telemetry() -> dict[str, Any]:
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


@app.get("/api/system_telemetry")
@ttl_cached(ttl_seconds=2.0)
async def get_system_telemetry() -> dict[str, Any]:
    """Expose detailed system hardware telemetry for the HUD core cards with TTL caching."""
    return _sample_system_telemetry()


# ==============================================================================
# Canonical Task Lifecycle, SSE Progress, and Emergency Control Endpoints
# ==============================================================================

from friday.core.task_manager import task_manager


@app.get("/v1/tasks")
@app.get("/api/tasks")
async def list_tasks_endpoint(limit: int = 50) -> dict[str, Any]:
    """List recent tasks managed by FRIDAY Core."""
    tasks = [t.model_dump() for t in task_manager.list_tasks(limit=limit)]
    return {"status": "ok", "tasks": tasks, "count": len(tasks), "success": True}


@app.get("/v1/tasks/{task_id}")
@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str) -> Any:
    """Retrieve state and observability progress for a task envelope."""
    t = task_manager.get_task(task_id)
    if not t:
        return JSONResponse(
            status_code=404,
            content={"error": "TASK_NOT_FOUND", "message": f"Task '{task_id}' was not found", "success": False},
        )
    return {"status": "ok", "task": t.model_dump(), "success": True}


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


@app.get("/api/livekit/token")
async def livekit_token(
    request: Request,
    room: str = "friday",
    identity: str = "owner",
) -> dict[str, str]:
    """Mint a short-lived LiveKit room token for the authenticated dashboard."""
    room = room.strip()
    identity = identity.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", room):
        raise HTTPException(status_code=400, detail="Invalid LiveKit room name")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", identity):
        raise HTTPException(status_code=400, detail="Invalid LiveKit identity")

    api_key = os.getenv("LIVEKIT_API_KEY", "").strip()
    api_secret = os.getenv("LIVEKIT_API_SECRET", "").strip()
    livekit_url = os.getenv("LIVEKIT_URL", "").strip()
    if not api_key or not api_secret or not livekit_url:
        raise HTTPException(
            status_code=503,
            detail="LiveKit is not configured on this FRIDAY instance",
        )

    try:
        from livekit import api
    except ImportError as exc:
        logger.error("LiveKit token service is unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="LiveKit server SDK is unavailable") from exc

    token = (
        api.AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_ttl(timedelta(minutes=10))
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .to_jwt()
    )
    return {"server_url": livekit_url, "token": token, "room": room, "identity": identity}


@app.get("/api/agents")
async def list_agents() -> list[dict[str, Any]]:
    """Expose the FRIDAY Universe specialist agents with live health and latency."""
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


@app.post("/api/agents/{agent_id}/task")
async def run_agent_task(
    agent_id: str,
    req: AgentTaskRequest,
    _: None = Depends(_require_control_access),
) -> dict[str, Any]:
    """Dispatch one typed task to one specialist and report receipt-verified state.

    This is the dashboard's per-agent control path. It delegates to the same
    autonomous controller entry point that a "tell <agent> to …" command uses, so
    both routes share one set of contracts, circuit breakers and evidence rules.
    """
    from friday.autonomous.controller import FLEET_AGENTS

    target = (agent_id or "").strip().lower()
    if target not in FLEET_AGENTS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown agent '{agent_id}'. Known agents: {', '.join(sorted(FLEET_AGENTS))}.",
        )
    directive = (req.directive or "").strip()
    if not directive:
        raise HTTPException(status_code=422, detail="A directive is required.")
    result = await autonomous_controller.execute_agent_control(target, directive)
    meta = result.get("metadata") or {}
    if meta.get("refused"):
        return JSONResponse(status_code=403, content=result)
    return result


@app.get("/api/agents/status")
async def get_agents_status() -> dict[str, Any]:
    """Return a fresh peer endpoint reachability snapshot, not task-level verification."""
    statuses = await fleet_client.get_all_statuses(force_refresh=True)
    status_counts = {
        status: sum(1 for agent_status in statuses if agent_status.status == status)
        for status in ("ONLINE", "REACHABLE", "DEGRADED", "UNREACHABLE", "OFFLINE")
    }
    # Nine specialists are expected (Inference, Memora, Stratex, IntelX, Futuris,
    # Cortex, Forge, Sentinel, VyralX). The count used to be hard-coded to eight,
    # so a fully reachable fleet still reported "degraded".
    expected_agents = len(CANONICAL_INTERNAL_MESH_URLS)
    all_agents_reported = len(statuses) == expected_agents
    overall_ok = all_agents_reported and status_counts["ONLINE"] == expected_agents
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
    expected_agents = len(CANONICAL_INTERNAL_MESH_URLS)
    all_agents_reported = len(agents) == expected_agents
    overall_ok = (
        fleet_supervision_state.get("running")
        and snapshot_is_fresh
        and all_agents_reported
        and status_counts["ONLINE"] == expected_agents
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
    """Toggle runtime-only Autonomous Mode and expose the active authorization settings."""
    new_state = autonomous_controller.toggle()
    current = autonomous_controller.get_status()
    # Start/stop the autonomous daemon
    if new_state:
        await autonomous_daemon.start()
    else:
        await autonomous_daemon.stop()
    return {
        "status": "ok",
        "autonomous_mode": new_state,
        "full_access_mode": current["full_access_mode"],
        "sensitive_actions_auto_approved": current["sensitive_actions_auto_approved"],
        "autonomous_mode_persistence": "runtime_only",
    }


@app.post("/api/autonomous/repair")
async def trigger_autonomous_repair(_: None = Depends(_require_control_access)) -> dict[str, Any]:
    """Trigger an immediate autonomous self-healing and diagnostic sweep."""
    return await autonomous_controller.execute_self_repair()


class AutonomousGoalRequest(BaseModel):
    """Submit a goal for autonomous execution."""
    goal: str
    priority: int = 0
    metadata: dict[str, Any] | None = None


@app.post("/api/autonomous/goals")
async def submit_autonomous_goal(
    req: AutonomousGoalRequest,
    _: None = Depends(_require_control_access),
) -> dict[str, Any]:
    """Submit a new goal for autonomous execution."""
    if not req.goal or not req.goal.strip():
        raise HTTPException(status_code=400, detail="goal must not be empty")
    goal = autonomous_daemon.submit_goal(req.goal, req.priority, req.metadata)
    # An explicitly submitted goal is the owner asking for work now. If the
    # daemon worker is not alive (fresh restart, autonomy toggled off), start it
    # so the goal cannot sit in the queue forever.
    if not autonomous_daemon.is_running:
        await autonomous_daemon.start()
    return {
        "goal_id": goal.id,
        "goal": goal.goal,
        "priority": goal.priority,
        "status": goal.status,
    }


@app.get("/api/autonomous/daemon")
async def get_autonomous_daemon_status(
    _: None = Depends(_require_control_access),
) -> dict[str, Any]:
    """Get the autonomous daemon status and goal queue."""
    return autonomous_daemon.get_status()


@app.get("/api/autonomous/goals/{goal_id}")
async def get_autonomous_goal(
    goal_id: str,
    _: None = Depends(_require_control_access),
) -> dict[str, Any]:
    """Return one goal with its human summary and per-agent step pipeline.

    The dashboard polls this while work runs so the owner can watch each
    specialist move from pending to running to finished.
    """
    payload = autonomous_daemon.get_goal(goal_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="No goal with that reference is on record.")
    return payload


@app.delete("/api/autonomous/goals/{goal_id}")
async def cancel_autonomous_goal(
    goal_id: str,
    _: None = Depends(_require_control_access),
) -> dict[str, Any]:
    """Cancel one queued or running goal and confirm only after execution stops."""
    payload = await autonomous_daemon.cancel_goal(goal_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="No goal with that reference is on record.")
    if payload.get("status") != "CANCELLED":
        current_status = str(payload.get("status") or "UNKNOWN").upper()
        raise HTTPException(
            status_code=409,
            detail=f"Goal was not stopped; its current status is {current_status}.",
        )
    return payload


@app.post("/api/autonomous/decompose")
async def decompose_goal_autonomous(
    goal: str,
    _: None = Depends(_require_control_access),
) -> dict[str, Any]:
    """Decompose a complex goal into executable sub-tasks without executing."""
    plan = enhanced_controller.decompose_goal(goal)
    return {
        "status": "ok",
        "plan_id": id(plan),
        "goal": plan.goal,
        "subtasks": [
            {
                "id": st.id,
                "description": st.description,
                "agent": st.agent,
                "dependencies": st.dependencies,
            }
            for st in plan.subtasks
        ],
    }


@app.get("/api/autonomous/plans")
async def get_autonomous_plans(
    _: None = Depends(_require_control_access),
) -> dict[str, Any]:
    """Get active and recent execution plans."""
    active = enhanced_controller.get_active_plan()
    history = enhanced_controller.get_execution_history(10)
    return {
        "active_plan": {
            "goal": active.goal,
            "status": active.status,
            "progress": active.get_progress(),
            "subtasks": [
                {
                    "id": st.id,
                    "description": st.description,
                    "agent": st.agent,
                    "status": st.status,
                }
                for st in active.subtasks
            ],
        } if active else None,
        "history": history,
    }


@app.post("/api/autonomous/agent-health")
async def check_autonomous_agent_health(
    _: None = Depends(_require_control_access),
) -> dict[str, Any]:
    """Check health of all agents in the fleet."""
    return await enhanced_controller.check_agent_health()


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
    try:
        include = parse_incident_scope(req.scope)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
async def handle_android_action(
    req: AndroidActionRequest, _: None = Depends(_require_control_access)
) -> Any:
    """Execute Android ADB action or get device connection status."""
    try:
        if req.action == "info":
            connected = android.is_connected()
            devices = [android.adb_device_id] if connected and android.adb_device_id else []
            # A successful status query may truthfully report no attached device.
            return {
                "success": connected,
                "connected": connected,
                "devices": devices,
            }
        elif req.action == "app":
            app_name = req.params.get("app", "youtube")
            ok = android.open_app(app_name)
            payload = {"success": ok, "action": "app", "app": app_name}
        elif req.action == "key":
            key_name = req.params.get("key", "home")
            ok = android.press_key(key_name)
            payload = {"success": ok, "action": "key", "key": key_name}
        elif req.action == "tap":
            x = req.params.get("x", 0)
            y = req.params.get("y", 0)
            ok = android.click(x, y)
            payload = {"success": ok, "action": "tap", "x": x, "y": y}
        elif req.action == "swipe":
            ok = android.swipe(
                req.params.get("x1", 0),
                req.params.get("y1", 0),
                req.params.get("x2", 0),
                req.params.get("y2", 0),
                req.params.get("duration", 300),
            )
            payload = {"success": ok, "action": "swipe"}
        else:
            return JSONResponse(
                status_code=422,
                content={"success": False, "error": f"Unknown action '{req.action}'"},
            )
        return payload if ok else JSONResponse(status_code=502, content=payload)
    except Exception as e:
        logger.warning(f"Android endpoint error: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "devices": [], "error": str(e)},
        )


#: Verbs that ask for something to be removed, overwritten or destroyed. They
#: are handled before any launcher ladder, because a ladder that matches on
#: substrings will happily read "delete all my files" as "open Files".
_DESTRUCTIVE_VERBS = (
    "delete",
    "erase",
    "wipe",
    "format",
    "destroy",
    "remove all",
    "uninstall",
    "kill all",
    "shut down the computer",
    "shutdown the computer",
    "reboot the computer",
    "restart the computer",
    "factory reset",
    "rm -rf",
    "drop table",
)

#: Verbs that mean "start a program" - the only intents allowed to reach the
#: application ladder below.
_LAUNCH_PREFIXES = ("open ", "launch ", "start ", "run ", "show ", "switch to ", "go to ", "bring up ")


def _refusal(payload: dict[str, Any], status_code: int = 403) -> JSONResponse:
    """A refusal a client can act on without parsing prose.

    Failure responses used to be HTTP 200 with ``success: false`` buried in the
    body, so a caller - including the mobile client and the MCP bridge - could
    not tell "the laptop locked itself" from "FRIDAY said no" without reading
    English. The status code now carries the distinction and the body keeps the
    shape it had.
    """
    return JSONResponse(status_code=status_code, content=payload)


def _is_destructive(cmd: str) -> bool:
    return any(verb in cmd for verb in _DESTRUCTIVE_VERBS)


def _looks_like_launch(cmd: str) -> bool:
    """Whether this is a request to *start* something, rather than mere chat
    that happens to contain a word an application also uses."""
    stripped = cmd.strip()
    if not stripped:
        return False
    if stripped in {"chrome", "notepad", "calculator", "explorer", "paint", "terminal"}:
        return True
    return any(stripped.startswith(prefix) for prefix in _LAUNCH_PREFIXES)


def _launch_target_verified(target: str) -> tuple[bool, str]:
    """Start a program and say what actually happened.

    The old path ran ``subprocess.Popen(f'start "" "{target}"', shell=True)`` and
    returned ``Launched '{target}'.`` unconditionally. On a POSIX host ``start``
    is not a command at all, so "open MyCoolProject" answered
    ``Launched 'MyCoolProject'.`` for a name that does not exist anywhere - the
    same false-success pattern the tool layer was fixed for.
    """
    if not target:
        return False, "No application or file was named."
    candidate = os.path.expanduser(target)
    if os.path.exists(candidate):
        try:
            os.startfile(candidate)  # type: ignore[attr-defined]  # Windows only
            return True, f"Opened '{candidate}'."
        except AttributeError:
            from friday.core.effects import launch_process_verified

            outcome = launch_process_verified(f'xdg-open "{candidate}"') if _which("xdg-open") else None
            if outcome and outcome.ok:
                return True, f"Opened '{candidate}'."
            return False, (
                f"'{candidate}' exists but this machine has no way to open it from FRIDAY "
                "(no file handler available)."
            )
        except Exception as exc:
            return False, f"'{candidate}' could not be opened: {exc}"

    from friday.core.effects import launch_process_verified

    resolved = _which(candidate)
    if resolved:
        outcome = launch_process_verified(f'"{resolved}"')
        if outcome.ok:
            return True, f"Launched '{target}'."
        return False, f"'{target}' did not start: {outcome.detail}"

    return False, f"There is no application or file called '{target}' on this machine, so nothing was launched."


def _which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


@app.post("/api/command")
async def execute_command(req: CommandRequest, _: None = Depends(_require_control_access)) -> Any:
    """Execute a text command with PC, Android, and live 8-Agent execution."""
    result = await _dispatch_command(req.command)
    meta = result.get("metadata") or {}
    
    # Determine status for logging
    authorization = str(meta.get("authorization", "")).upper()
    authorization_denied = authorization in {"DENIED", "EXPIRED", "CANCELLED"}
    is_refused = (
        meta.get("security_blocked")
        or meta.get("refused")
        or meta.get("destructive_refused")
        or meta.get("authorization_denied")
        or authorization_denied
    )
    is_error = meta.get("execution_failed") or meta.get("error") or meta.get("success") is False
    status = "failed" if (is_refused or is_error) else "success"
    
    # Extract agents involved from metadata
    agents_involved = []
    if meta.get("agent_id"):
        agents_involved.append(meta["agent_id"])
    elif meta.get("fast_path") and meta.get("device"):
        agents_involved.append(f"friday-{meta['device']}")
    elif meta.get("peer_name"):
        agents_involved.append(meta["peer_name"])
    
    # Log conversation
    await _log_conversation(
        user_input=req.command,
        friday_reply=result.get("reply", ""),
        input_type="text",
        status=status,
        agents_involved=agents_involved,
        metadata=meta,
    )
    
    if is_refused:
        return _refusal(result, 403)
    if meta.get("execution_failed"):
        return JSONResponse(status_code=500, content=result)
    receipt = meta.get("receipt")
    if (
        meta.get("direct_action") == "send_whatsapp"
        and isinstance(receipt, dict)
        and receipt.get("status") == "DISPATCH_UNCONFIRMED"
    ):
        return JSONResponse(status_code=202, content=result)
    if str(meta.get("task_state", "")).upper() == "PENDING":
        return JSONResponse(status_code=202, content=result)
    if meta.get("direct_action") and meta.get("success") is False:
        status_code = 502 if meta.get("receipt") else 422
        return JSONResponse(status_code=status_code, content=result)
    if meta.get("error") or meta.get("success") is False:
        return JSONResponse(status_code=502, content=result)
    return result


async def _dispatch_command(command: str) -> dict[str, Any]:
    """The command router itself; :func:`execute_command` maps its result to HTTP."""
    raw_cmd = (command or "").strip()
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

    # Destructive intent is answered before any launcher ladder runs. "delete all
    # my files" used to reach the ladder below, match the substring "files" and
    # reply "Could not start File Explorer." - a sentence about the wrong action
    # entirely, which reads as if the deletion had been understood.
    if _is_destructive(cmd):
        return {
            "reply": (
                "I will not delete, overwrite or uninstall anything on that instruction. "
                "Destructive changes are refused by FRIDAY's file and system tools, and nothing "
                "was touched. If you meant a specific file, name it exactly and I will show you "
                "what would be affected before doing anything."
            ),
            "metadata": {
                "refused": True,
                "destructive_refused": True,
                "reason": "destructive_request",
                "command": raw_cmd,
            },
        }

    # =========================================================================
    # A. Autonomous Mode Toggles & Directives
    # =========================================================================
    if any(k in cmd for k in [
        "activate autonomous mode", "enable autonomous mode", "turn on autonomous mode",
        "autonomous mode on", "autonomous on", "start autonomous mode", "run autonomously"
    ]):
        autonomous_controller.toggle(True)
        mode_status = autonomous_controller.get_status()
        return {
            "reply": (
                "Autonomous Mode is ACTIVE for this running process only; the toggle is not saved and resets "
                "to the configured setting after restart. Safety policy remains in force, and DANGEROUS actions "
                "still require explicit confirmation."
            ),
            "metadata": {
                "fast_path": True,
                "autonomous": True,
                "autonomous_mode": True,
                "full_access_mode": mode_status["full_access_mode"],
                "sensitive_actions_auto_approved": mode_status["sensitive_actions_auto_approved"],
                "autonomous_mode_persistence": "runtime_only",
            },
        }

    if any(k in cmd for k in [
        "deactivate autonomous mode", "disable autonomous mode", "turn off autonomous mode",
        "autonomous mode off", "autonomous off", "stop autonomous mode", "manual mode"
    ]):
        autonomous_controller.toggle(False)
        mode_status = autonomous_controller.get_status()
        reply = "Autonomous Mode is OFF for this running process only; the configured setting applies after restart."
        if mode_status["full_access_mode"]:
            reply += " Full-access compatibility mode remains ON, so SENSITIVE actions may still be auto-approved."
        else:
            reply += " Standing by for manual approval of SENSITIVE actions."
        reply += " DANGEROUS actions still require explicit confirmation."
        return {
            "reply": reply,
            "metadata": {
                "fast_path": True,
                "autonomous": False,
                "autonomous_mode": False,
                "full_access_mode": mode_status["full_access_mode"],
                "sensitive_actions_auto_approved": mode_status["sensitive_actions_auto_approved"],
                "autonomous_mode_persistence": "runtime_only",
            },
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
        # This greeting used to assert "8 specialist agents are online and ready"
        # without asking any of them - while /api/agents reported every one of
        # them UNREACHABLE on the same machine, at the same moment. A greeting
        # may say that FRIDAY is listening; it may not certify a fleet.
        return {
            "reply": (
                "Hello Surendra. FRIDAY is listening. Say 'status of all agents' for a live check of "
                "the specialist peers - I will not claim they are online without asking them."
            ),
            "metadata": {"fast_path": True, "conversational": True, "peer_health_checked": False},
        }

    if any(k in cmd for k in ["not tracking", "hands are not tracking", "these two hands", "two hands", "tracking", "gesture", "calibrate hands", "test hands"]):
        return {"reply": "Dual-hand optical sensors are active and calibrated. Hold both hands facing the camera with open palms for reticle lock.", "metadata": {"fast_path": True, "conversational": True}}

    if any(k in cmd for k in ["who are you", "who made you", "what are you", "your name", "are you there", "can you hear me"]):
        return {"reply": "I am F.R.I.D.A.Y., Surendra's Autonomous Intelligence Core v3.5. I control your PC, Android ecosystem, and 8 specialist agents.", "metadata": {"fast_path": True, "conversational": True}}

    if any(k in cmd for k in ["thank you", "thanks", "great job", "good job", "nice", "awesome"]):
        return {"reply": "Always at your service, Surendra.", "metadata": {"fast_path": True, "conversational": True}}

    if any(k in cmd for k in ["what can you do", "help", "features", "commands", "what are your capabilities", "capabilities", "what do you do"]):
        return {
            "reply": "I can launch Windows applications, open and search websites, control the Windows media session, capture screenshots, monitor system telemetry, and orchestrate the specialist agents when they answer. Website playback and account actions require a working service integration.",
            "metadata": {"fast_path": True, "conversational": True},
        }

    if cmd in ["on", "and", "the", "a", "an", "in", "to", "for", "is", "it", "so", "but", "or", "er", "put", "um", "uh", "test"]:
        return {"reply": "I am listening, Surendra. Tell me what directive to execute.", "metadata": {"fast_path": True, "conversational": True}}

    # 1. Master Fleet & All-Agents Matrix
    if any(k in cmd for k in ["status of all agents", "all agents", "fleet status", "ecosystem status", "check all agents", "universe status", "agents status", "all agent"]):
        return await fleet_client.get_fleet_summary()

    # 2. Live Specialist Agent Direct Execution
    for agent_id in ["inference", "stratex", "memora", "intelx", "futuris", "cortex", "forge", "sentinel", "vyralx"]:
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

            fallback_data = {
                "reply": f"⚡ [{agent_id.upper()} // DEGRADED] Peer is temporarily unavailable.",
                "metadata": {"agent_id": agent_id, "status": "degraded", "fallback": True},
                "success": False,
                "error": "PEER_TIMEOUT",
            }
            if agent_id == "inference":
                return await safe_peer_call(fleet_client.ask_inference(sub_q), fallback_data=fallback_data, peer_name="inference")
            elif agent_id == "memora":
                return await safe_peer_call(fleet_client.ask_memora(sub_q), fallback_data=fallback_data, peer_name="memora")
            elif agent_id == "stratex":
                return await safe_peer_call(fleet_client.ask_stratex(sub_q), fallback_data=fallback_data, peer_name="stratex")
            elif agent_id == "intelx":
                return await safe_peer_call(fleet_client.ask_intelx(sub_q), fallback_data=fallback_data, peer_name="intelx")
            elif agent_id == "futuris":
                return await safe_peer_call(fleet_client.ask_futuris(sub_q), fallback_data=fallback_data, peer_name="futuris")
            elif agent_id == "cortex":
                return await safe_peer_call(fleet_client.ask_cortex(sub_q), fallback_data=fallback_data, peer_name="cortex")
            elif agent_id == "forge":
                return await safe_peer_call(fleet_client.ask_forge(sub_q), fallback_data=fallback_data, peer_name="forge")
            elif agent_id == "sentinel":
                return await safe_peer_call(fleet_client.ask_sentinel(sub_q), fallback_data=fallback_data, peer_name="sentinel")
            elif agent_id == "vyralx":
                return await safe_peer_call(fleet_client.ask_vyralx(sub_q), fallback_data=fallback_data, peer_name="vyralx")

    # 2. Android Automation Fast-paths
    try:
        if "on phone" in cmd or "on android" in cmd or cmd.startswith("phone ") or cmd.startswith("android "):
            # Check if device is connected first
            if not android.is_connected():
                return {
                    "reply": "No Android device connected via ADB. Connect your phone via USB with USB Debugging enabled.",
                    "metadata": {
                        "fast_path": True,
                        "device": "android",
                        "adb_connected": False,
                        "success": False,
                    },
                }

            # Android App Launch fast-path
            for app_name in ["youtube", "chrome", "maps", "camera", "settings", "whatsapp", "spotify", "instagram", "calculator"]:
                if app_name in cmd:
                    success = android.open_app(app_name)
                    msg = (
                        f"Opened {app_name.capitalize()} on Android device."
                        if success
                        else f"Failed to launch {app_name} on Android."
                    )
                    return {
                        "reply": msg,
                        "metadata": {
                            "fast_path": True,
                            "device": "android",
                            "action": "open_app",
                            "success": success,
                        },
                    }
            if "home" in cmd:
                success = android.press_key("home")
                msg = "Pressed Home on Android device." if success else "Failed to press Home on Android."
                return {
                    "reply": msg,
                    "metadata": {"fast_path": True, "device": "android", "action": "home", "success": success},
                }
            if "back" in cmd:
                success = android.press_key("back")
                msg = "Pressed Back on Android device." if success else "Failed to press Back on Android."
                return {
                    "reply": msg,
                    "metadata": {"fast_path": True, "device": "android", "action": "back", "success": success},
                }
    except Exception as ae:
        logger.warning(f"Android fast-path error: {ae}")

    # 3. Windows FRIDAY Master Laptop Directives (YouTube, websites, media, volume, apps, folders, system)
    try:
        from friday.devices.windows_friday import windows_friday
        handled, friday_reply, friday_meta = windows_friday.handle_directive(
            raw_cmd, authorizer=getattr(agent, "authorizer", None)
        )
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

            reply = (
                f"I am perceiving your environment. {active_summary} Screen and window telemetry is "
                "active; specialist-agent status is a separate check."
            )
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

            ok, msg = _launch_target_verified(target_str)
            if ok:
                return {"reply": msg, "metadata": {"fast_path": True, "target": target_str, "success": True}}
            return {
                "reply": msg,
                "metadata": {"fast_path": True, "target": target_str, "success": False, "refused": True},
            }

        if _looks_like_launch(cmd) and any(k in cmd for k in ["chrome", "google chrome", "swipe right"]):
            ok, msg = launch_desktop_app("chrome")
            return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "chrome", "success": ok}}
        elif _looks_like_launch(cmd) and any(k in cmd for k in ["notepad", "text editor", "swipe left"]):
            ok, msg = launch_desktop_app("notepad")
            return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "notepad", "success": ok}}
        elif _looks_like_launch(cmd) and any(k in cmd for k in ["calc", "calculator"]):
            ok, msg = launch_desktop_app("calculator")
            return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "calculator", "success": ok}}
        elif _looks_like_launch(cmd) and any(k in cmd for k in ["code", "vscode", "vs code"]):
            ok, msg = launch_desktop_app("vscode")
            return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "code", "success": ok}}
        elif _looks_like_launch(cmd) and any(k in cmd for k in ["edge", "microsoft edge"]):
            ok, msg = launch_desktop_app("edge")
            return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "edge", "success": ok}}
        elif _looks_like_launch(cmd) and any(k in cmd for k in ["explorer", "file explorer", "files"]):
            ok, msg = launch_desktop_app("explorer")
            return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "explorer", "success": ok}}
        elif _looks_like_launch(cmd) and any(k in cmd for k in ["paint", "mspaint"]):
            ok, msg = launch_desktop_app("paint")
            return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "paint", "success": ok}}
        elif _looks_like_launch(cmd) and any(k in cmd for k in ["terminal", "cmd", "powershell"]):
            ok, msg = launch_desktop_app("terminal")
            return {"reply": msg, "metadata": {"fast_path": True, "device": "windows", "app": "terminal", "success": ok}}
        elif _looks_like_launch(cmd) and any(k in cmd for k in ["screenshot", "capture screen", "snapshot"]):
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
        response = await loop.run_in_executor(None, agent.process_message, raw_cmd)
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
                "reply": f"⚠️ FRIDAY could not complete the request ({type(exc).__name__}).\n\n{repair_report['reply']}",
                "metadata": {
                    "autonomous": True,
                    "self_repair_attempted": False,
                    "execution_failed": True,
                    "success": False,
                    "error": type(exc).__name__,
                },
            }
        return {
            "reply": (
                f"FRIDAY could not process this request ({type(exc).__name__}). "
                "No action is being reported as completed. Please retry or provide more detail."
            ),
            "metadata": {
                "fallback": True,
                "execution_failed": True,
                "success": False,
                "error": type(exc).__name__,
            },
        }


# Historical note: duplicate `/api/android`, `/api/system_telemetry`, and
# `/api/telemetry` handlers once lived here. FastAPI resolves routes in
# registration order, leaving later copies unreachable; one of those copies
# hardcoded Windows telemetry. Keep the canonical, measured handlers above and
# guard route uniqueness in `test_the_telemetry_routes_are_not_shadowed`.

class ChatRequest(BaseModel):
    message: str = ""



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
async def voice_endpoint(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for bidirectional audio, waveform telemetry, and MediaPipe hand gestures.
    Supports real-time gesture control and instant desktop/mobile actions.
    """
    try:
        await _require_control_access_ws(websocket)
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
# Real-Time Companion Event Multiplexer & Desktop Telemetry Stream
# =========================================================================

@app.websocket("/ws/companion")
@app.websocket("/api/ws/companion")
async def companion_ws_endpoint(websocket: WebSocket) -> None:
    """Real-time companion event multiplexer and desktop telemetry stream."""
    try:
        await _require_control_access_ws(websocket)
    except HTTPException:
        await websocket.close(code=1008, reason="FRIDAY control authentication required")
        return
    await websocket.accept()
    client_id = f"companion_{uuid.uuid4().hex[:8]}"
    raw_topics = websocket.query_params.get("topics")
    topics = {t.strip().lower() for t in raw_topics.split(",")} if raw_topics else {"telemetry", "system"}
    sub = await companion_multiplexer.connect(websocket, client_id=client_id, initial_topics=topics)

    # Ensure background telemetry streaming is active
    companion_multiplexer.start_telemetry_streaming(agent.get_system_diagnostics, interval_seconds=2.5)

    await websocket.send_json({
        "type": "welcome",
        "client_id": sub.client_id,
        "topics": sorted(list(sub.topics)),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    async def _exec_cmd(cmd_text: str) -> dict[str, Any]:
        return await execute_command(CommandRequest(command=cmd_text))

    try:
        while True:
            msg = await websocket.receive_json()
            await companion_multiplexer.handle_message(
                websocket=websocket,
                msg=msg,
                command_executor=_exec_cmd,
                snapshot_getter=agent.get_system_diagnostics,
            )
    except WebSocketDisconnect:
        await companion_multiplexer.disconnect(websocket)
    except Exception as exc:
        logger.warning("Companion WS session error: %s", exc)
        await companion_multiplexer.disconnect(websocket)


@app.get("/api/companion/status")
async def companion_status_endpoint(_: None = Depends(_require_control_access)) -> dict[str, Any]:
    """Return status and subscriber diagnostics for the real-time companion multiplexer."""
    return {"status": "ok", **companion_multiplexer.get_status()}


# =========================================================================
# Real-Time Activity Stream WebSocket
# =========================================================================
@app.websocket("/api/ws/activity")
async def activity_ws_endpoint(websocket: WebSocket) -> None:
    """Stream autonomous agent activity events to dashboard clients in real time."""
    try:
        await _require_control_access_ws(websocket)
    except HTTPException:
        await websocket.close(code=1008, reason="FRIDAY control authentication required")
        return
    await websocket.accept()
    register_activity_client(websocket)
    # Send a short backlog so a freshly connected dashboard reflects recent work.
    try:
        from friday.autonomous.controller import autonomous_controller

        for entry in list(autonomous_controller.action_history)[-20:]:
            await websocket.send_json({
                "type": "activity",
                "agent": entry.target,
                "action": entry.action_type,
                "target": entry.target,
                "directive": entry.directive,
                "result": entry.result,
                "success": entry.success,
                "timestamp": getattr(entry, "recorded_at", None) or entry.timestamp,
            })
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug("Activity backlog send failed: %s", exc)
    try:
        while True:
            msg = await websocket.receive_json()
            if isinstance(msg, dict) and msg.get("type") == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("Activity WS session error: %s", exc)
    finally:
        unregister_activity_client(websocket)


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
        companion_multiplexer.start_telemetry_streaming(agent.get_system_diagnostics, interval_seconds=2.5)
        logger.info("FRIDAY proactive monitoring started")
    except Exception as e:
        logger.warning(f"Could not start proactive monitoring: {e}")


# Auto-start proactive monitoring when the module loads (server boot)
start_proactive_monitoring()


# =========================================================================
# Conversation History Endpoints
# =========================================================================

from collections import deque
import uuid as _uuid

# In-memory conversation history store (max 10000 entries)
_conversation_history: deque = deque(maxlen=10000)
_conversation_lock = asyncio.Lock()


class ConversationEntry(BaseModel):
    """Conversation history entry model."""
    id: str | None = None
    timestamp: str | None = None
    user_input: str
    friday_reply: str
    input_type: str = "text"  # "text" or "voice"
    status: str = "success"   # "success", "failed", "pending", "running", "cancelled"
    agents_involved: list[str] = []
    metadata: dict[str, Any] = {}


@app.get("/api/v1/conversation/history")
async def get_conversation_history(
    limit: int = 50,
    offset: int = 0,
    date_from: str | None = None,
    date_to: str | None = None,
    agent: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """Get conversation history with pagination and filtering."""
    async with _conversation_lock:
        entries = list(_conversation_history)

    # Apply filters
    filtered = entries
    if date_from:
        try:
            from_dt = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
            filtered = [e for e in filtered if datetime.fromisoformat(e.timestamp.replace('Z', '+00:00')) >= from_dt]
        except ValueError:
            pass
    if date_to:
        try:
            to_dt = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
            filtered = [e for e in filtered if datetime.fromisoformat(e.timestamp.replace('Z', '+00:00')) <= to_dt]
        except ValueError:
            pass
    if agent:
        filtered = [e for e in filtered if agent in e.agents_involved]
    if status:
        filtered = [e for e in filtered if e.status == status]
    if search:
        search_lower = search.lower()
        filtered = [e for e in filtered 
                   if search_lower in e.user_input.lower() or search_lower in e.friday_reply.lower()]

    # Sort by timestamp descending (newest first)
    filtered.sort(key=lambda e: e.timestamp, reverse=True)

    # Pagination
    total = len(filtered)
    paginated = filtered[offset:offset + limit]

    return {
        "status": "ok",
        "entries": [e.model_dump() for e in paginated],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total,
    }


@app.get("/api/v1/conversation/export")
async def export_conversation_history(
    format: str = "json",
    date_from: str | None = None,
    date_to: str | None = None,
    agent: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> Any:
    """Export conversation history as JSON or Markdown."""
    async with _conversation_lock:
        entries = list(_conversation_history)

    # Apply same filters as history endpoint
    filtered = entries
    if date_from:
        try:
            from_dt = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
            filtered = [e for e in filtered if datetime.fromisoformat(e.timestamp.replace('Z', '+00:00')) >= from_dt]
        except ValueError:
            pass
    if date_to:
        try:
            to_dt = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
            filtered = [e for e in filtered if datetime.fromisoformat(e.timestamp.replace('Z', '+00:00')) <= to_dt]
        except ValueError:
            pass
    if agent:
        filtered = [e for e in filtered if agent in e.agents_involved]
    if status:
        filtered = [e for e in filtered if e.status == status]
    if search:
        search_lower = search.lower()
        filtered = [e for e in filtered 
                   if search_lower in e.user_input.lower() or search_lower in e.friday_reply.lower()]

    filtered.sort(key=lambda e: e.timestamp, reverse=True)

    if format.lower() == "markdown" or format.lower() == "md":
        lines = [
            "# FRIDAY Conversation History Export",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            f"Total Entries: {len(filtered)}",
            "",
            "---",
            ""
        ]
        for entry in filtered:
            timestamp = entry.timestamp
            input_type = entry.input_type
            status_str = entry.status
            agents = ", ".join(entry.agents_involved) if entry.agents_involved else "None"
            lines.extend([
                f"## {timestamp} [{input_type}] [{status_str}]",
                f"**Agents:** {agents}",
                "",
                f"**You:** {entry.user_input}",
                "",
                f"**FRIDAY:** {entry.friday_reply}",
                "",
                "---",
                ""
            ])
        if entry.metadata:
            lines.extend([
                "**Metadata:**",
                "```json",
                json.dumps(entry.metadata, indent=2),
                "```",
                ""
            ])
        return Response(
            content="\n".join(lines),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="friday-conversation-{datetime.now().strftime("%Y%m%d-%H%M%S")}.md"'}
        )

    # Default to JSON
    return JSONResponse(
        content={"entries": [e.model_dump() for e in filtered]},
        headers={"Content-Disposition": f'attachment; filename="friday-conversation-{datetime.now().strftime("%Y%m%d-%H%M%S")}.json"'}
    )


@app.post("/api/v1/conversation/entry")
async def add_conversation_entry(entry: ConversationEntry, _: None = Depends(_require_control_access)) -> dict[str, Any]:
    """Add a new conversation entry (for real-time logging)."""
    now = datetime.now(timezone.utc).isoformat()
    entry_id = entry.id or str(_uuid.uuid4())
    timestamp = entry.timestamp or now

    new_entry = ConversationEntry(
        id=entry_id,
        timestamp=timestamp,
        user_input=entry.user_input,
        friday_reply=entry.friday_reply,
        input_type=entry.input_type,
        status=entry.status,
        agents_involved=entry.agents_involved,
        metadata=entry.metadata,
    )

    async with _conversation_lock:
        _conversation_history.appendleft(new_entry)

    # Broadcast to activity stream if available
    try:
        from friday.api.activity_stream import broadcast_activity
        await broadcast_activity({
            "type": "conversation",
            "entry_id": entry_id,
            "timestamp": timestamp,
            "user_input": entry.user_input[:100],
            "status": entry.status,
            "agents": entry.agents_involved,
        })
    except Exception:
        pass

    return {"status": "ok", "entry_id": entry_id, "timestamp": timestamp}


@app.delete("/api/v1/conversation/history")
async def clear_conversation_history(_: None = Depends(_require_control_access)) -> dict[str, Any]:
    """Clear all conversation history."""
    async with _conversation_lock:
        _conversation_history.clear()
    return {"status": "ok", "cleared": True}


# Helper function to log conversations from the command endpoint
async def _log_conversation(
    user_input: str,
    friday_reply: str,
    input_type: str = "text",
    status: str = "success",
    agents_involved: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Internal helper to log a conversation entry."""
    entry = ConversationEntry(
        id=str(_uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        user_input=user_input,
        friday_reply=friday_reply,
        input_type=input_type,
        status=status,
        agents_involved=agents_involved or [],
        metadata=metadata or {},
    )
    async with _conversation_lock:
        _conversation_history.appendleft(entry)


@app.post("/v1/events")
@app.post("/api/events")
async def receive_peer_event(request: Request) -> dict[str, Any]:
    """Ingest peer specialist agent telemetry, strategic decisions, and events."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    source = body.get("source", "unknown")
    event_type = body.get("event_type", "unknown")
    logger.info(f"Peer event received from {source}: {event_type}")
    return {"status": "ok", "received": True, "source": source, "event_type": event_type}


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


# =========================================================================
# Laptop Reverse Tunnel (cloud FRIDAY -> owner's laptop)
# =========================================================================
#
# The laptop dials out; the cloud never listens on the laptop's network. The
# tunnel authenticates with the same control secret as the rest of this API and
# only dispatches the allowlist enforced in `friday.remote.laptop_bridge`.


class LaptopCommandRequest(BaseModel):
    command: str
    args: dict[str, Any] = {}
    timeout: float = 30.0


def _laptop_tunnel_authorised(websocket: WebSocket) -> bool:
    """Authorise a laptop tunnel upgrade.

    Browsers cannot be trusted to drive this route, so the origin policy applies
    first. A non-browser client (the laptop bridge) presents either the control
    API key or a short-lived control token, checked with the same helpers as
    :func:`_require_control_access`. The query parameter exists because a
    WebSocket client cannot always set custom headers.
    """
    if not _websocket_origin_allowed(websocket):
        return False
    expected = _control_secret()
    if not _control_secret_is_usable(expected):
        return False

    provided = websocket.headers.get("x-friday-api-key", "")
    authorization = websocket.headers.get("authorization", "")
    if not provided and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    if provided and hmac.compare_digest(provided, expected):
        return True

    candidates = (
        websocket.query_params.get("token", ""),
        websocket.headers.get("x-friday-control-token", ""),
    )
    return any(token and _control_token_valid(token, expected) for token in candidates)


@app.get("/api/laptop/devices")
async def laptop_devices_endpoint(_: None = Depends(_require_control_access)) -> dict[str, Any]:
    """List every laptop that has ever connected, with current tunnel state."""
    return {"devices": await laptop_bridge.list_devices()}


@app.post("/api/laptop/{laptop_id}/command")
async def laptop_command_endpoint(
    laptop_id: str,
    req: LaptopCommandRequest,
    _: None = Depends(_require_control_access),
) -> Any:
    """Dispatch one allowlisted command to a connected laptop.

    A missing tunnel is 404, a deadline is 504 and a tunnel that dies in flight
    is 502. The evidence record is returned in every one of those cases so the
    caller can see what actually happened.
    """
    try:
        evidence = await laptop_bridge.execute(laptop_id, req.command, req.timeout, req.args)
    except LaptopNotConnected as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LaptopBridgeTimeout as exc:
        return JSONResponse(status_code=504, content=exc.evidence)
    except LaptopDisconnected as exc:
        return JSONResponse(status_code=502, content=exc.evidence)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return evidence


@app.websocket("/api/laptop/connect/{laptop_id}")
async def laptop_connect_endpoint(websocket: WebSocket, laptop_id: str) -> None:
    """Laptop-side reverse tunnel.

    The socket is accepted before the 1008 close is sent because an ASGI server
    turns a pre-accept close into an HTTP 403 handshake rejection, which hides
    the authentication reason from the client.
    """
    if not _laptop_tunnel_authorised(websocket):
        logger.warning("Rejected laptop tunnel: control authentication failed")
        await websocket.accept()
        await websocket.close(code=1008, reason="FRIDAY control authentication required")
        return

    try:
        laptop_id = normalise_laptop_id(laptop_id)
    except ValueError as exc:
        await websocket.accept()
        await websocket.close(code=1008, reason=str(exc))
        return

    await websocket.accept()
    replaced = await laptop_bridge.register(laptop_id, websocket)
    if replaced is not None:
        try:
            await replaced.websocket.close(code=1012, reason="Replaced by a newer laptop tunnel")
        except Exception:
            logger.debug("Previous laptop tunnel for %s was already closed", laptop_id)

    try:
        await websocket.send_json(
            {
                "type": "welcome",
                "laptop_id": laptop_id,
                "heartbeat_interval": 20.0,
                "commands": sorted(ALLOWED_LAPTOP_COMMANDS),
                "shell_enabled": shell_execution_enabled(),
                "server_time": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as exc:
        logger.warning("Laptop tunnel %s failed during welcome: %s", laptop_id, exc)
        await laptop_bridge.unregister(laptop_id, websocket)
        return

    try:
        while True:
            try:
                message = await websocket.receive_json()
            except json.JSONDecodeError:
                logger.warning("Laptop tunnel %s sent invalid JSON", laptop_id)
                continue
            if not isinstance(message, dict):
                logger.warning("Laptop tunnel %s sent a non-object frame", laptop_id)
                continue

            kind = str(message.get("type") or "").strip().lower()
            if kind in {"result", "command_result"}:
                if not await laptop_bridge.resolve_result(laptop_id, message):
                    logger.warning(
                        "Laptop tunnel %s returned an unknown or expired request", laptop_id
                    )
            elif kind in {"ping", "heartbeat"}:
                await laptop_bridge.touch(laptop_id)
                await websocket.send_json(
                    {"type": "pong", "server_time": datetime.now(timezone.utc).isoformat()}
                )
            else:
                # `hello` and any future informational frame only refresh liveness.
                await laptop_bridge.touch(laptop_id)
    except WebSocketDisconnect:
        logger.info("Laptop tunnel disconnected: %s", laptop_id)
    except Exception as exc:
        logger.warning("Laptop tunnel error for %s: %s", laptop_id, exc)
    finally:
        await laptop_bridge.unregister(laptop_id, websocket)


# --- Self-contained command center (server-rendered) ------------------------
# The dashboard is a single HTML document with inline CSS/JS. Serving it from
# the API removes the whole class of failures that a client-only bundle has on
# this host: no chunk 404s, no basePath mismatch, no hydration crash that leaves
# the owner staring at a spinner. The markup is real HTML, so something useful
# is visible before a single byte of JavaScript runs.

_INDEX_FILE = Path(__file__).with_name("index.html")
_index_cache: dict[str, Any] = {"mtime": -1.0, "html": ""}


def _index_html() -> str:
    try:
        mtime = _INDEX_FILE.stat().st_mtime
    except OSError:
        return (
            "<!doctype html><meta charset='utf-8'><title>FRIDAY</title>"
            "<body style='background:#050508;color:#f0f0f5;font-family:system-ui;padding:40px'>"
            "<h1>FRIDAY</h1><p>The index file is missing on this host.</p></body>"
        )
    if _index_cache["mtime"] != mtime or not _index_cache["html"]:
        _index_cache["html"] = _INDEX_FILE.read_text(encoding="utf-8")
        _index_cache["mtime"] = mtime
    return _index_cache["html"]


@app.get("/", include_in_schema=False)
async def index_root() -> Response:
    return Response(
        content=_index_html(),
        media_type="text/html",
        headers={"Cache-Control": "no-store, max-age=0", "X-FRIDAY-Surface": "friday-ai"},
    )


@app.get("/dashboard", include_in_schema=False)
async def dashboard_alias() -> Response:
    return await index_root()


class VoiceSpeakRequest(BaseModel):
    text: str
    voice: str | None = None
    lang: str | None = None


_VOICE_CATALOGUE = [
    {"id": "en-IN-NeerjaNeural", "language": "en-IN", "label": "English (India) — Neerja", "gender": "Female"},
    {"id": "en-IN-PrabhatNeural", "language": "en-IN", "label": "English (India) — Prabhat", "gender": "Male"},
    {"id": "te-IN-ShrutiNeural", "language": "te-IN", "label": "Telugu — Shruti", "gender": "Female"},
    {"id": "te-IN-MohanNeural", "language": "te-IN", "label": "Telugu — Mohan", "gender": "Male"},
]
_VOICE_BY_ID = {entry["id"]: entry for entry in _VOICE_CATALOGUE}
_DEFAULT_VOICE_FOR_LANG = {"en": "en-IN-NeerjaNeural", "te": "te-IN-ShrutiNeural"}
_voice_cache: dict[str, bytes] = {}
_voice_cache_order: list[str] = []
_voice_lock = asyncio.Semaphore(2)


@app.get("/api/voice/languages")
async def voice_languages() -> Any:
    """Languages FRIDAY can actually speak on this host."""
    return {
        "languages": _VOICE_CATALOGUE,
        "default": _DEFAULT_VOICE_FOR_LANG,
        "telugu_installed": True,
        "engine": "edge-tts",
    }


@app.post("/api/voice/speak")
async def voice_speak(
    req: VoiceSpeakRequest,
    _: None = Depends(_require_control_access),
) -> Response:
    """Synthesise speech (English or Telugu) and return audio/mpeg.

    Telugu voices are Microsoft neural voices streamed through edge-tts, so no
    Windows language pack and no per-token model download is needed.
    """
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    if len(text) > 1800:
        text = text[:1800]

    requested = (req.voice or "").strip()
    lang = (req.lang or "en").strip().lower()[:2]
    voice = requested if requested in _VOICE_BY_ID else _DEFAULT_VOICE_FOR_LANG.get(lang, "en-IN-NeerjaNeural")

    key = hashlib.sha256(f"{voice}\x00{text}".encode("utf-8")).hexdigest()
    cached = _voice_cache.get(key)
    if cached is not None:
        return Response(content=cached, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})

    try:
        import edge_tts  # imported lazily: the API host is memory constrained
    except Exception as exc:  # pragma: no cover - dependency guard
        raise HTTPException(status_code=503, detail=f"Speech engine unavailable: {exc}") from exc

    audio = bytearray()
    try:
        async with _voice_lock:
            communicate = edge_tts.Communicate(text, voice)
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    audio.extend(chunk["data"])
    except Exception as exc:
        logger.warning("Voice synthesis failed for %s: %s", voice, exc)
        raise HTTPException(status_code=502, detail=f"Speech synthesis failed: {exc}") from exc

    if not audio:
        raise HTTPException(status_code=502, detail="Speech engine produced no audio")

    payload = bytes(audio)
    _voice_cache[key] = payload
    _voice_cache_order.append(key)
    while len(_voice_cache_order) > 24:
        _voice_cache.pop(_voice_cache_order.pop(0), None)

    return Response(
        content=payload,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store", "X-FRIDAY-Voice": voice},
    )


@app.post("/api/autonomous/execute")
async def execute_plan_autonomous(goal: str):
    """Execute a complete autonomous plan with dependency resolution."""
    from friday.autonomous.enhanced_controller import enhanced_controller
    try:
        plan = enhanced_controller.decompose_goal(goal)
        result = await enhanced_controller.execute_plan(plan)
        evaluation = enhanced_controller.evaluate_outcome(result)
        return evaluation
    except Exception as exc:
        raise HTTPException(500, f"Plan execution failed: {exc}")


@app.get("/api/autonomous/history")
async def get_execution_history():
    """Get recent autonomous execution history."""
    from friday.autonomous.enhanced_controller import enhanced_controller
    history = enhanced_controller.get_execution_history(limit=10)
    return {"history": history, "total": len(history)}


@app.get("/api/autonomous/fleet-status")
async def get_fleet_status():
    """Get overall fleet status from the mesh orchestrator."""
    from mesh.fleet_orchestrator import fleet_orchestrator
    try:
        status = await fleet_orchestrator.get_fleet_status()
        return status
    except Exception as exc:
        raise HTTPException(500, f"Fleet status failed: {exc}")


@app.post("/api/autonomous/emergency-halt")
async def emergency_halt_agent(agent: str):
    """Emergency halt a specific agent."""
    from mesh.fleet_orchestrator import fleet_orchestrator
    try:
        success = await fleet_orchestrator.emergency_halt(agent)
        return {"status": "HALTED" if success else "FAILED", "agent": agent}
    except Exception as exc:
        raise HTTPException(500, f"Emergency halt failed: {exc}")


# --- Autonomous Decision Making Integration ---
try:
    _apps_core_path = Path(__file__).resolve().parents[3] / "apps" / "core" / "src"
    if _apps_core_path.is_dir() and str(_apps_core_path) not in sys.path:
        sys.path.insert(0, str(_apps_core_path))
    from friday_core.autonomous_decision_making import router as autonomous_decision_router
    app.include_router(autonomous_decision_router)  # routes already start with /api/v1
except Exception as _e:
    logger.warning(f"Could not load autonomous_decision_making router: {_e}")

# --- Agent Mesh Coordinator Integration ---
try:
    from friday_core.agent_mesh_coordinator import router as mesh_coordinator_router
    app.include_router(mesh_coordinator_router)  # routes already start with /api/v1
except Exception as _e:
    logger.warning(f"Could not load agent_mesh_coordinator router: {_e}")


# --- Mesh Module Integrations ---
from mesh.universe_health import router as universe_health_router
from mesh.universe_status import router as universe_status_router
from mesh.cross_agent_context import router as cross_agent_context_router
from mesh.adaptive_router import router as adaptive_router_router
from mesh.unified_errors import router as unified_errors_router
from mesh.self_improvement_loop import router as self_improvement_router
from mesh.automated_consolidation import router as automated_consolidation_router

# These mesh routers declare absolute paths (/api/v1/mesh/...).
app.include_router(universe_health_router)
app.include_router(universe_status_router)
app.include_router(cross_agent_context_router)
app.include_router(adaptive_router_router)
app.include_router(unified_errors_router)
app.include_router(self_improvement_router)
app.include_router(automated_consolidation_router)


# --- Additional Mesh Module Integrations ---
from mesh.performance_profiler import router as performance_profiler_router
from mesh.universe_soak_test import router as universe_soak_test_router

app.include_router(performance_profiler_router)
app.include_router(universe_soak_test_router)


# --- FRIDAY Core Module Integrations ---
from friday_core.autonomous_laptop_operator import router as laptop_operator_router
from friday_core.general_cognitive_coordinator import router as cognitive_coordinator_router

from friday.services.autonomous_problem_solver import router as problem_solver_router
from friday.services.multi_agent_coordinator import router as coordinator_router

app.include_router(laptop_operator_router)
app.include_router(cognitive_coordinator_router)
app.include_router(problem_solver_router)
app.include_router(coordinator_router)

# --- New FRIDAY Deep Module Integrations ---
from friday_core.task_decomposition_engine import router as task_decomp_router
from friday_core.decision_synthesis_engine import router as decision_synth_router
from friday_core.goal_planning_engine import router as goal_planning_router
from friday_core.context_window_manager import router as context_window_router
from friday_core.feedback_learning_engine import router as feedback_learning_router
from friday_core.agent_mesh_router import router as agent_mesh_router
from friday_core.universe_health_monitor import router as universe_health_mon_router

app.include_router(task_decomp_router, prefix="/api/v1")
app.include_router(decision_synth_router, prefix="/api/v1")
app.include_router(goal_planning_router, prefix="/api/v1")
app.include_router(context_window_router, prefix="/api/v1")
app.include_router(feedback_learning_router, prefix="/api/v1")
app.include_router(agent_mesh_router, prefix="/api/v1")
app.include_router(universe_health_mon_router, prefix="/api/v1")

# --- Cross-Cutting Infrastructure Integrations ---
from friday_core.universe_gateway import router as universe_gateway_router
from friday_core.universe_config import router as universe_config_router
from friday_core.universe_metrics import router as universe_metrics_router
from friday_core.error_envelope import router as error_envelope_router

app.include_router(universe_gateway_router, prefix="/api/v1")
app.include_router(universe_config_router, prefix="/api/v1")
app.include_router(universe_metrics_router, prefix="/api/v1")
app.include_router(error_envelope_router, prefix="/api/v1")

# --- Wave 35: Cross-Agent & Security Integrations ---
from friday_core.universe_dispatch_bus import router as dispatch_bus_router
from friday_core.universe_auth import router as universe_auth_router
from friday_core.cross_agent_integration import router as cross_agent_router
from friday_core.security_hardening import router as security_hardening_router

app.include_router(dispatch_bus_router, prefix="/api/v1")
app.include_router(universe_auth_router, prefix="/api/v1")
app.include_router(cross_agent_router, prefix="/api/v1")
app.include_router(security_hardening_router, prefix="/api/v1")

# --- Wave 39: Resilience & Cost Optimization ---
from friday_core.universe_resilience import router as universe_resilience_router
from friday_core.universe_cost_optimizer import router as universe_cost_router

app.include_router(universe_resilience_router, prefix="/api/v1")
app.include_router(universe_cost_router, prefix="/api/v1")

# --- Wave 41: Knowledge Graph ---
from friday_core.universe_knowledge_graph import router as universe_kg_router
app.include_router(universe_kg_router, prefix="/api/v1")

# --- Wave 42: Event Bus & State Manager ---
from friday_core.universe_event_bus import router as universe_event_bus_router
from friday_core.universe_state_manager import router as universe_state_router

app.include_router(universe_event_bus_router, prefix="/api/v1")
app.include_router(universe_state_router, prefix="/api/v1")

# --- Wave 44: Audit Trail & Rate Limiter ---
from friday_core.universe_audit_trail import router as universe_audit_router
from friday_core.universe_rate_limiter import router as universe_rate_router

app.include_router(universe_audit_router, prefix="/api/v1")
app.include_router(universe_rate_router, prefix="/api/v1")

# --- Wave 45: Task Router ---
from friday_core.universe_task_router import router as universe_task_router
app.include_router(universe_task_router, prefix="/api/v1")
