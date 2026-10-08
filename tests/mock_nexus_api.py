"""A minimal stand-in for the Nexus website/growth API, for real-path tests.

The Nexus operator used to answer every query from a hardcoded telemetry object,
so no test could tell a working integration from a broken one. It now POSTs
``{"command": ...}`` to ``{base_url}/v1/friday/command``; this server answers
those commands over a real socket and records what it received.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class MockNexusState:
    """Mutable state served by :class:`MockNexusServer`."""

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
        self.site_status: dict[str, Any] = {
            "status": "DEGRADED",
            "health_score": 71.5,
            "visitors_today": 1533,
            "conversion_rate_pct": 1.92,
            "leads_detected_today": 3,
            "active_experiments_count": 1,
            "pending_approvals_count": 2,
        }
        self.leads: list[dict[str, Any]] = [
            {"lead_id": "lead_live_1", "score": 81, "company_domain": "live-prospect.example",
             "evidence": "Requested a security review", "intent_level": "HIGH"},
        ]
        self.incidents: list[dict[str, Any]] = [
            {"id": "inc_live_1", "severity": "MINOR", "title": "Slow image CDN", "description": "TTFB up 400ms"},
        ]
        self.health: dict[str, Any] = {
            "status": "healthy",
            "tracking_pipeline": "OPERATIONAL",
            "policy_engine": "ACTIVE",
        }
        self.paused: list[str] = []
        self.fail_with: int | None = None

        # Manager-specific readings are mutable and served over the same real
        # socket as the operator commands above.
        self.site_overview: dict[str, Any] = {
            "status": "DEGRADED",
            "health_score": 71.5,
            "visitors_today": 1533,
            "sessions_today": 2011,
            "live_active_visitors": 1,
            "conversion_rate_today": 1.92,
            "conversion_rate_yesterday": 2.10,
            "conversion_trend": "-8.6% vs yesterday",
            "leads_today_count": 1,
            "active_incidents_count": 1,
            "pending_approvals_count": 1,
        }
        self.visitors: list[dict[str, Any]] = [
            {
                "session_id": "session_live_1",
                "current_page": "/pricing",
                "dwell_time_seconds": 120,
                "intent_score": 0.88,
                "intent_level": "HIGH",
                "inferred_company": "live-prospect.example",
            },
        ]
        self.pipeline: list[dict[str, Any]] = [
            {
                "lead_id": "pipeline_live_1",
                "company_domain": "live-prospect.example",
                "stage": "DECISION",
                "score": 81,
                "intent_score": 0.88,
                "evidence": "Requested a security review",
            },
        ]
        self.approvals: list[dict[str, Any]] = [
            {
                "action_id": "action_live_1",
                "title": "Review checkout copy",
                "status": "PENDING",
                "evidence": "A local test fixture reports this evidence.",
                "expected_lift_pct": 4.2,
            },
        ]
        self.consultations: list[dict[str, Any]] = [
            {
                "consultation_id": "consultation_live_1",
                "recommendation": "Review the checkout flow",
                "confidence": 0.72,
                "reasoning_chain": ["The scripted service reports a checkout drop."],
                "ai_universe_model": "scripted-test-provider",
            },
        ]
        self.strategies: list[dict[str, Any]] = [
            {
                "strategy_name": "Checkout copy test",
                "status": "RUNNING",
                "measured_lift_pct": None,
                "learning": "No measured result is available yet.",
            },
        ]
        self.approved: list[str] = []
        self.rejected: list[dict[str, str]] = []
        self.workflows: list[dict[str, Any]] = []
        # Per-command scripts cover malformed responses and slow services.
        self.response_overrides: dict[str, dict[str, Any]] = {}
        self.delay_by_command: dict[str, float] = {}


class MockNexusServer:
    """Answers POST /v1/friday/command with data supplied by the test."""

    def __init__(self, port: int = 8984) -> None:
        self.port = port
        self.state = MockNexusState()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _json(self, code: int, payload: Any) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    # Expected when a timeout test closes its side of the socket.
                    pass

            def _raw(self, code: int, body: bytes, content_type: str = "application/json") -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

            def do_POST(self) -> None:  # noqa: N802 - http.server API
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    body = {}
                state.received.append({"path": self.path, "body": body})
                command = body.get("command")

                if self.path != "/v1/friday/command":
                    self._json(404, {"error": "unknown path"})
                    return

                if command in state.delay_by_command:
                    import time

                    time.sleep(state.delay_by_command[command])

                if state.fail_with is not None:
                    self._json(state.fail_with, {"error": "forced failure"})
                    return

                if command in state.response_overrides:
                    override = state.response_overrides[command]
                    override_body = override.get("body", {})
                    if isinstance(override_body, bytes):
                        raw_body = override_body
                    elif isinstance(override_body, str):
                        raw_body = override_body.encode("utf-8")
                    else:
                        raw_body = json.dumps(override_body).encode("utf-8")
                    self._raw(
                        int(override.get("status", 200)),
                        raw_body,
                        str(override.get("content_type", "application/json")),
                    )
                    return
                if command == "get_site_status":
                    self._json(200, dict(state.site_status, sample_data=False))
                elif command == "get_high_intent_leads":
                    self._json(200, {"leads": state.leads})
                elif command == "get_pending_incidents":
                    self._json(200, {"incidents": state.incidents})
                elif command == "diagnose_conversion_drop":
                    self._json(
                        200,
                        {
                            "diagnosis_id": "diag_live_1",
                            "primary_cause": "Checkout JS bundle regression",
                            "affected_pages": ["/checkout"],
                            "impact_pct": -7.5,
                            "recommended_action": "Roll back bundle v4192.",
                        },
                    )
                elif command == "explain_decision":
                    self._json(
                        200,
                        {
                            "request_id": body.get("request_id", "req_latest"),
                            "decision": "Keep Variant A at 100%",
                            "confidence_pct": 66.0,
                            "reasoning_chain": ["Variant B lift was not significant (p=0.31)."],
                            "ai_universe_consultation": {"consensus": "SPLIT_DECISION", "latency_ms": 210.0},
                        },
                    )
                elif command == "pause_experiment":
                    state.paused.append(str(body.get("experiment_id")))
                    self._json(200, {"experiment_id": body.get("experiment_id"), "success": True, "status": "PAUSED"})
                elif command == "start_nexus_workflow":
                    self._json(
                        200,
                        {
                            "workflow_id": "wf_live_1",
                            "workflow_name": body.get("workflow_name"),
                            "status": "QUEUED",
                            "authorized_by_policy_engine": True,
                        },
                    )
                elif command == "get_site_overview":
                    self._json(200, dict(state.site_overview))
                elif command == "get_live_visitors":
                    self._json(200, {"visitors": state.visitors})
                elif command == "get_lead_pipeline":
                    self._json(200, {"leads": state.pipeline})
                elif command == "get_incidents":
                    self._json(200, {"incidents": state.incidents})
                elif command == "get_pending_approvals":
                    self._json(200, {"approvals": state.approvals})
                elif command == "approve_action":
                    action_id = str(body.get("action_id", ""))
                    state.approved.append(action_id)
                    self._json(200, {"action_id": action_id, "success": True, "status": "APPROVED"})
                elif command == "reject_action":
                    rejection = {
                        "action_id": str(body.get("action_id", "")),
                        "reason": str(body.get("reason", "")),
                    }
                    state.rejected.append(rejection)
                    self._json(200, {**rejection, "success": True, "status": "REJECTED"})
                elif command in {"start_workflow", "start_nexus_workflow"}:
                    workflow = {
                        "workflow_name": body.get("workflow_name"),
                        "params": body.get("params", {}),
                    }
                    state.workflows.append(workflow)
                    self._json(
                        200,
                        {
                            "workflow_id": "wf_live_1",
                            **workflow,
                            "status": "QUEUED",
                            "authorized_by_policy_engine": True,
                        },
                    )
                elif command == "get_intelligence_log":
                    self._json(200, {"consultations": state.consultations})
                elif command == "get_strategy_performance":
                    self._json(200, {"strategies": state.strategies})
                elif command == "query_analytics":
                    self._json(200, {"question": body.get("question"), "answer": "The scripted endpoint reports a 1.92% conversion rate."})
                elif command == "health_check":
                    self._json(200, dict(state.health))
                else:
                    self._json(400, {"error": f"unknown command {command!r}"})

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
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
