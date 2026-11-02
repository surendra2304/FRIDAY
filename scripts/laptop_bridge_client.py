"""Outbound tunnel client for the owner's laptop.

The laptop has no public address, so it dials the cloud FRIDAY and holds the
WebSocket open. FRIDAY sends allowlisted command frames; this client runs them
locally and returns the evidence record.

Usage (from the FRIDAY repo root)::

    set FRIDAY_API_KEY=<control key>
    python scripts/laptop_bridge_client.py

or::

    python -m scripts.laptop_bridge_client

Environment:

``FRIDAY_BRIDGE_URL``
    Tunnel URL template. ``{laptop_id}`` (or ``<id>``) is substituted; a URL
    without a placeholder is treated as the base and the id is appended.
    Defaults to ``wss://friday-universe.duckdns.org/friday/api/laptop/connect/{laptop_id}``.
``FRIDAY_API_KEY``
    Required. The same control key the cloud FRIDAY was configured with. It is
    sent in the ``X-FRIDAY-Api-Key`` header and is never logged.
``FRIDAY_LAPTOP_ID``
    Stable device name; defaults to the hostname.
``FRIDAY_LAPTOP_ALLOW_SHELL``
    ``run_shell`` is refused unless this is ``true`` on the laptop *and* on the
    cloud host.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import inspect
import json
import logging
import os
import platform
import random
import re
import socket
import subprocess
import sys
import tempfile
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

_REPO_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

import websockets  # noqa: E402

from friday.core.logging import get_logger  # noqa: E402

logger = get_logger("scripts.laptop_bridge_client")

DEFAULT_BRIDGE_URL = (
    "wss://friday-universe.duckdns.org/friday/api/laptop/connect/{laptop_id}"
)
HEARTBEAT_SECONDS = 20.0
DEFAULT_COMMAND_TIMEOUT = 30.0
MAX_OUTPUT_BYTES = 16 * 1024
RECONNECT_BASE_SECONDS = 1.0
RECONNECT_MAX_SECONDS = 60.0
MAX_ARGS_BYTES = 64 * 1024
SHELL_COMMAND = "run_shell"
ALLOWED_COMMANDS = frozenset(
    {
        "screenshot",
        "open_url",
        "list_files",
        "read_file",
        SHELL_COMMAND,
        "system_info",
        "notify",
    }
)
_TRUNCATION_MARKER = "\n[truncated]"
_INVALID_ID_CHARS = re.compile(r"[^A-Za-z0-9_.:-]+")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shell_enabled() -> bool:
    return os.getenv("FRIDAY_LAPTOP_ALLOW_SHELL", "").strip().lower() in {"1", "true", "yes", "on"}


def _bounded(value: Any, limit: int = MAX_OUTPUT_BYTES) -> str:
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, default=str)
        except (TypeError, ValueError):
            text = str(value)
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= limit:
        return text
    marker = _TRUNCATION_MARKER.encode("utf-8")
    keep = max(0, limit - len(marker))
    return raw[:keep].decode("utf-8", errors="ignore") + _TRUNCATION_MARKER


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _safe_url(uri: str) -> str:
    """A loggable form of the tunnel URL: no query string, no credentials."""
    parsed = urlparse(uri)
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname or ''}{port}{parsed.path}"


def _laptop_id() -> str:
    raw = (os.getenv("FRIDAY_LAPTOP_ID") or socket.gethostname() or "laptop").strip()
    safe = _INVALID_ID_CHARS.sub("-", raw).strip("-.")
    return (safe or "laptop")[:64]


def _bridge_url(laptop_id: str, override: str | None = None) -> str:
    template = (override or os.getenv("FRIDAY_BRIDGE_URL") or DEFAULT_BRIDGE_URL).strip()
    encoded = quote(laptop_id, safe="")
    if "{laptop_id}" in template:
        return template.replace("{laptop_id}", encoded)
    if "<id>" in template:
        return template.replace("<id>", encoded)
    return template.rstrip("/") + "/" + encoded


def _connect(uri: str, api_key: str) -> Any:
    """Open a WebSocket across ``websockets`` 11-15 header-kwarg changes."""
    params = inspect.signature(websockets.connect).parameters
    header_kwarg = "additional_headers" if "additional_headers" in params else "extra_headers"
    return websockets.connect(
        uri,
        **{
            header_kwarg: {"X-FRIDAY-Api-Key": api_key},
            "ping_interval": 20,
            "ping_timeout": 20,
            "open_timeout": 20,
            "max_size": 2**20,
        },
    )


# ---------------------------------------------------------------------------
# Local command implementations. Each returns (ok, output, error).
# ---------------------------------------------------------------------------


def _cmd_screenshot(args: dict[str, Any], timeout: float) -> tuple[bool, Any, str | None]:
    try:
        from PIL import ImageGrab
    except ImportError:
        return False, "", "Pillow is not installed; screenshot capture is unavailable"
    try:
        image = ImageGrab.grab()
        directory = Path(tempfile.gettempdir()) / "friday-laptop-bridge"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"screenshot-{int(time.time() * 1000)}.png"
        image.save(target)
        return True, str(target), None
    except Exception as exc:
        return False, "", f"screenshot failed: {type(exc).__name__}: {exc}"


def _cmd_open_url(args: dict[str, Any], timeout: float) -> tuple[bool, Any, str | None]:
    url = str(args.get("url") or args.get("href") or "").strip()
    if not url:
        return False, "", "open_url requires a 'url' argument"
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return False, "", "open_url only accepts absolute http(s) URLs"
    try:
        opened = webbrowser.open(url, new=2)
    except Exception as exc:
        return False, "", f"open_url failed: {type(exc).__name__}: {exc}"
    if not opened:
        return False, "", "the laptop reported no browser handler for the URL"
    return True, f"Opened {url}", None


def _cmd_list_files(args: dict[str, Any], timeout: float) -> tuple[bool, Any, str | None]:
    raw_path = str(args.get("path") or Path.home())
    root = Path(raw_path).expanduser()
    if not root.exists():
        return False, "", f"Path does not exist: {root}"
    if not root.is_dir():
        return False, "", f"Not a directory: {root}"
    limit = _clamp_int(args.get("limit"), default=200, low=1, high=1000)
    entries: list[dict[str, Any]] = []
    try:
        candidates = sorted(root.iterdir(), key=lambda item: item.name.lower())[:limit]
    except OSError as exc:
        return False, "", f"Could not list {root}: {exc}"
    for entry in candidates:
        try:
            stat = entry.stat()
            entries.append(
                {
                    "name": entry.name,
                    "type": "dir" if entry.is_dir() else "file",
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                }
            )
        except OSError:
            entries.append({"name": entry.name, "type": "unknown", "size": None, "modified": None})
    payload = {"path": str(root), "count": len(entries), "entries": entries}
    return True, json.dumps(payload), None


def _cmd_read_file(args: dict[str, Any], timeout: float) -> tuple[bool, Any, str | None]:
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return False, "", "read_file requires a 'path' argument"
    target = Path(raw_path).expanduser()
    if not target.exists():
        return False, "", f"File does not exist: {target}"
    if not target.is_file():
        return False, "", f"Not a file: {target}"
    try:
        with target.open("rb") as handle:
            data = handle.read(MAX_OUTPUT_BYTES + 1)
    except OSError as exc:
        return False, "", f"Could not read {target}: {exc}"
    truncated = len(data) > MAX_OUTPUT_BYTES
    text = data[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    if truncated:
        text += "\n[truncated at 16384 bytes]"
    return True, text, None


def _cmd_run_shell(args: dict[str, Any], timeout: float) -> tuple[bool, Any, str | None]:
    if not _shell_enabled():
        return (
            False,
            "",
            "run_shell is disabled; set FRIDAY_LAPTOP_ALLOW_SHELL=true on this laptop to enable it",
        )
    command = str(args.get("command") or args.get("cmd") or "").strip()
    if not command:
        return False, "", "run_shell requires a 'command' argument"
    try:
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            timeout=max(1.0, timeout),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "", f"run_shell exceeded its {timeout:g}s deadline"
    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace")
    output = stdout
    if stderr:
        output = f"{output}\n[stderr]\n{stderr}" if output else f"[stderr]\n{stderr}"
    if completed.returncode != 0:
        return False, output, f"exit code {completed.returncode}"
    return True, output, None


def _cmd_system_info(args: dict[str, Any], timeout: float) -> tuple[bool, Any, str | None]:
    info: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "user": os.getenv("USERNAME") or os.getenv("USER") or "",
        "cwd": os.getcwd(),
    }
    try:
        import psutil

        memory = psutil.virtual_memory()
        info["cpu_count"] = psutil.cpu_count()
        info["memory_total_mb"] = round(memory.total / (1024 * 1024), 1)
        info["memory_available_mb"] = round(memory.available / (1024 * 1024), 1)
        battery = psutil.sensors_battery()
        if battery is not None:
            info["battery_percent"] = round(battery.percent, 1)
            info["battery_charging"] = bool(battery.power_plugged)
    except Exception as exc:
        info["psutil_error"] = type(exc).__name__
    return True, json.dumps(info), None


def _cmd_notify(args: dict[str, Any], timeout: float) -> tuple[bool, Any, str | None]:
    title = str(args.get("title") or "FRIDAY").strip() or "FRIDAY"
    message = str(args.get("message") or args.get("body") or "").strip()
    if not message:
        return False, "", "notify requires a 'message' argument"
    try:
        from plyer import notification

        notification.notify(title=title, message=message, timeout=10)
        return True, "Notification delivered via plyer.", None
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("plyer notification failed: %s", type(exc).__name__)
    try:
        from win10toast import ToastNotifier

        ToastNotifier().show_toast(title, message, duration=10, threaded=True)
        return True, "Notification delivered via win10toast.", None
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("win10toast notification failed: %s", type(exc).__name__)
    # No desktop notifier installed: leave a durable trace instead of claiming
    # a toast the owner never saw.
    logger.info("FRIDAY notification (no desktop notifier): %s - %s", title, message)
    return True, "Notification written to the laptop bridge log (no desktop notifier installed).", None


_COMMANDS = {
    "screenshot": _cmd_screenshot,
    "open_url": _cmd_open_url,
    "list_files": _cmd_list_files,
    "read_file": _cmd_read_file,
    SHELL_COMMAND: _cmd_run_shell,
    "system_info": _cmd_system_info,
    "notify": _cmd_notify,
}


def _evidence_record(
    laptop_id: str,
    request_id: str,
    command: str,
    *,
    ok: bool,
    output: Any,
    error: str | None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> dict[str, Any]:
    now = _now_iso()
    return {
        "request_id": request_id,
        "laptop_id": laptop_id,
        "command": command,
        "started_at": started_at or now,
        "finished_at": finished_at or _now_iso(),
        "ok": bool(ok),
        "output": _bounded(output),
        "error": None if error is None else _bounded(error, 2048),
    }


def _execute_command(
    laptop_id: str, request_id: str, command: str, args: dict[str, Any], timeout: float
) -> dict[str, Any]:
    """Run one command and always return a complete evidence record."""
    started_at = _now_iso()
    ok = False
    output: Any = ""
    error: str | None = None
    handler = _COMMANDS.get(command)
    if handler is None:
        error = f"unsupported command: {command}"
    else:
        try:
            ok, output, error = handler(args, timeout)
        except Exception as exc:
            ok, output, error = False, "", f"{type(exc).__name__}: {exc}"
    return _evidence_record(
        laptop_id,
        request_id,
        command,
        ok=ok,
        output=output,
        error=error,
        started_at=started_at,
    )


async def _heartbeat_loop(websocket: Any, send_lock: asyncio.Lock, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        async with send_lock:
            await websocket.send(json.dumps({"type": "ping", "timestamp": _now_iso()}))


async def _send(websocket: Any, send_lock: asyncio.Lock, payload: dict[str, Any]) -> None:
    async with send_lock:
        await websocket.send(json.dumps(payload, default=str))


async def _handle_command(
    websocket: Any,
    send_lock: asyncio.Lock,
    laptop_id: str,
    message: dict[str, Any],
) -> None:
    request_id = str(message.get("request_id") or "").strip()
    if not request_id:
        logger.warning("Ignoring command frame without a request_id")
        return
    command = str(message.get("command") or "").strip()
    raw_args = message.get("args")
    args = raw_args if isinstance(raw_args, dict) else {}
    try:
        timeout = float(message.get("timeout") or DEFAULT_COMMAND_TIMEOUT)
    except (TypeError, ValueError):
        timeout = DEFAULT_COMMAND_TIMEOUT
    timeout = max(1.0, min(300.0, timeout))
    if len(json.dumps(args, default=str).encode("utf-8")) > MAX_ARGS_BYTES:
        result = _evidence_record(
            laptop_id,
            request_id,
            command,
            ok=False,
            output="",
            error="command args are too large",
        )
    elif command not in ALLOWED_COMMANDS:
        result = _evidence_record(
            laptop_id,
            request_id,
            command,
            ok=False,
            output="",
            error=f"unsupported command: {command}",
        )
    else:
        # Screenshots, shell commands and file reads block; keep them off the
        # event loop so heartbeats and new commands are still serviced.
        result = await asyncio.to_thread(
            _execute_command, laptop_id, request_id, command, args, timeout
        )
    try:
        await _send(websocket, send_lock, {"type": "result", **result})
    except Exception as exc:
        logger.warning("Could not return result for %s: %s", request_id, type(exc).__name__)


async def _run_session(uri: str, api_key: str, laptop_id: str) -> None:
    async with _connect(uri, api_key) as websocket:
        logger.info("Tunnel open to %s as %s", _safe_url(uri), laptop_id)
        send_lock = asyncio.Lock()
        heartbeat = asyncio.create_task(_heartbeat_loop(websocket, send_lock, HEARTBEAT_SECONDS))
        try:
            async for raw in websocket:
                try:
                    message = json.loads(raw)
                except (TypeError, ValueError):
                    logger.warning("Ignoring non-JSON frame from cloud FRIDAY")
                    continue
                if not isinstance(message, dict):
                    continue
                kind = str(message.get("type") or "").strip().lower()
                if kind == "command":
                    asyncio.create_task(
                        _handle_command(websocket, send_lock, laptop_id, message)
                    )
                elif kind in {"ping", "heartbeat"}:
                    await _send(websocket, send_lock, {"type": "pong", "timestamp": _now_iso()})
                elif kind == "welcome":
                    logger.info(
                        "Cloud accepted the tunnel (shell_enabled=%s)",
                        message.get("shell_enabled"),
                    )
                elif kind == "pong":
                    continue
                else:
                    logger.debug("Ignoring tunnel frame of type %s", kind)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat


async def _run_forever(uri: str, api_key: str, laptop_id: str) -> None:
    attempt = 0
    while True:
        try:
            await _run_session(uri, api_key, laptop_id)
            attempt = 0
            logger.info("Tunnel closed cleanly; reconnecting")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Never interpolate the URL or headers here: the URL is safe, but a
            # library exception sometimes embeds handshake details.
            logger.warning(
                "Tunnel lost (%s); will reconnect", type(exc).__name__
            )
        delay = min(RECONNECT_MAX_SECONDS, RECONNECT_BASE_SECONDS * (2 ** min(attempt, 10)))
        delay *= random.uniform(0.5, 1.5)
        attempt += 1
        logger.info("Reconnecting in %.1fs", delay)
        await asyncio.sleep(delay)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FRIDAY laptop reverse-tunnel client")
    parser.add_argument("--url", help="Bridge URL template (overrides FRIDAY_BRIDGE_URL)")
    parser.add_argument("--laptop-id", help="Stable laptop id (overrides FRIDAY_LAPTOP_ID)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.getenv("FRIDAY_LAPTOP_LOG_LEVEL", "INFO").upper(),
        format="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
    )
    args = _parse_args(argv)
    api_key = (os.getenv("FRIDAY_API_KEY") or "").strip()
    if not api_key:
        logger.error("FRIDAY_API_KEY is not set; the laptop cannot authenticate to FRIDAY")
        return 2
    laptop_id = _INVALID_ID_CHARS.sub("-", (args.laptop_id or _laptop_id()).strip()).strip("-.")
    if not laptop_id:
        logger.error("No usable laptop id; set FRIDAY_LAPTOP_ID")
        return 2
    laptop_id = laptop_id[:64]
    uri = _bridge_url(laptop_id, args.url)
    logger.info(
        "Starting laptop bridge for %s (shell_enabled=%s)",
        laptop_id,
        _shell_enabled(),
    )
    try:
        asyncio.run(_run_forever(uri, api_key, laptop_id))
    except KeyboardInterrupt:
        logger.info("Laptop bridge stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
