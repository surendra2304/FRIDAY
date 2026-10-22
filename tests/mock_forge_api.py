"""A minimal stand-in for the FORGE REST API, for real-path tests.

`ForgeManagerSkill.get_forge_health()` used to return a constant "HEALTHY"
without making a request, and `submit_build_request()` never left the process.
Both now talk HTTP, so the tests need something on the other end: this serves
``GET /api/health``, ``POST /api/tasks``, ``GET /api/tasks`` and
``GET /api/tasks/{id}`` over a real socket, and records every request it
receives so a test can prove the call happened.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


class MockForgeState:
    """Mutable state served by :class:`MockForgeServer`."""

    def __init__(self) -> None:
        self.health_status = "healthy"
        self.service = "Mock FORGE Engine"
        self.ai_universe_connection = "CONNECTED"
        self.tasks: dict[str, dict[str, Any]] = {}
        self.received_requests: list[dict[str, Any]] = []
        self.fail_next_health_with: int | None = None


class MockForgeServer:
    """A real HTTP server that answers the FORGE endpoints this client uses."""

    def __init__(self, port: int = 8977) -> None:
        self.port = port
        self.state = MockForgeState()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> str:
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # keep test output clean
                pass

            def _json(self, code: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _record(self, method: str, path: str, body: Any = None) -> None:
                state.received_requests.append({"method": method, "path": path, "body": body})

            def do_GET(self) -> None:  # noqa: N802 - http.server API
                parsed = urllib.parse.urlparse(self.path)
                self._record("GET", parsed.path)
                if parsed.path == "/api/health":
                    if state.fail_next_health_with is not None:
                        code, state.fail_next_health_with = state.fail_next_health_with, None
                        self._json(code, {"error": "forced failure"})
                        return
                    self._json(
                        200,
                        {
                            "status": state.health_status,
                            "service": state.service,
                            "ai_universe_connection": state.ai_universe_connection,
                        },
                    )
                    return
                if parsed.path == "/api/tasks":
                    self._json(200, {"tasks": list(state.tasks.values()), "total": len(state.tasks)})
                    return
                if parsed.path.startswith("/api/tasks/"):
                    task_id = parsed.path[len("/api/tasks/") :]
                    task = state.tasks.get(task_id)
                    if task is None:
                        self._json(404, {"error": f"task {task_id} not found"})
                    else:
                        self._json(200, task)
                    return
                self._json(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802 - http.server API
                parsed = urllib.parse.urlparse(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    body = {"raw": raw.decode("utf-8", "replace")}
                self._record("POST", parsed.path, body)
                if parsed.path == "/api/tasks":
                    task_id = f"forge_remote_{len(state.tasks) + 1:02d}"
                    state.tasks[task_id] = {"task_id": task_id, "state": "QUEUED", "request": body}
                    self._json(202, {"accepted": True, "task_id": task_id, "state": "QUEUED"})
                    return
                self._json(404, {"error": "not found"})

        self._server = HTTPServer(("127.0.0.1", self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.base_url

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
