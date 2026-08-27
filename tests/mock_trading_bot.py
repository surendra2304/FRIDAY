# -*- coding: utf-8 -*-
"""Mock Trading Bot Server for Testing and Validation.

Simulates the external Algorithmic Trading Bot on Binance Futures Testnet,
providing /api/status, /api/advisory/recent, /api/advisory/state, and /api/panic.
Supports scenarios: 'mixed', 'all_rejected', 'all_applied', 'ai_universe_down', 'empty', 'unreachable'.
"""

from dataclasses import dataclass, field
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from typing import Any, Dict, List, Optional
import urllib.parse


class MockTradingBotState:
    """Configurable in-memory state generator for testing scenarios."""

    def __init__(self, scenario: str = "mixed") -> None:
        self.scenario = scenario
        self.panic_activated = False
        self.panic_history: List[Dict[str, Any]] = []

    def get_status_payload(self) -> Dict[str, Any]:
        return {
            "status": "PANIC" if self.panic_activated else "ACTIVE",
            "trading_mode": "TESTNET",
            "equity": 10540.25,
            "cash": 8200.00,
            "unrealized_pnl": 140.25,
            "realized_pnl": 400.00,
            "today_pnl": 540.25,
            "profit_factor": 1.85,
            "win_rate_pct": 68.5,
            "positions": [
                {"symbol": "BTCUSDT", "side": "LONG", "size": 0.05, "unrealized_pnl": 95.50},
                {"symbol": "ETHUSDT", "side": "SHORT", "size": 0.50, "unrealized_pnl": 44.75},
            ] if self.scenario != "empty" else []
        }

    def get_advisory_recent_payload(self, limit: int = 10) -> Dict[str, Any]:
        if self.scenario == "empty":
            return {"advisories": []}

        if self.scenario == "all_rejected":
            return {
                "advisories": [
                    {
                        "decision_id": "adv_rej_01",
                        "timestamp": "2026-08-27T10:00:00Z",
                        "verdict": "REJECT",
                        "confidence": 0.88,
                        "recommendation": "Expand ETH leverage from 5x to 10x",
                        "rejection_reason": "Exceeds testnet safety gate maximum leverage limit (5x)",
                        "parameter_adjustments": {"eth_max_leverage": 10},
                        "key_evidence": ["High momentum breakout detected"],
                    },
                    {
                        "decision_id": "adv_rej_02",
                        "timestamp": "2026-08-27T10:15:00Z",
                        "verdict": "REJECT",
                        "confidence": 0.75,
                        "recommendation": "Widen BTC scalper stop-loss to 3.5%",
                        "rejection_reason": "Exceeds max allowed stop loss boundary of 1.5%",
                        "parameter_adjustments": {"btc_sl_pct": 3.5},
                        "key_evidence": ["High market volatility expected"],
                    },
                ][:limit]
            }

        if self.scenario == "all_applied":
            return {
                "advisories": [
                    {
                        "decision_id": "adv_app_01",
                        "timestamp": "2026-08-27T10:00:00Z",
                        "verdict": "APPLY",
                        "confidence": 0.85,
                        "recommendation": "Tighten BTC scalper stop-loss to 0.4%",
                        "rejection_reason": None,
                        "parameter_adjustments": {"btc_sl_pct": 0.4},
                        "key_evidence": ["ATR volatility contraction pattern"],
                    },
                    {
                        "decision_id": "adv_app_02",
                        "timestamp": "2026-08-27T10:20:00Z",
                        "verdict": "APPLY",
                        "confidence": 0.92,
                        "recommendation": "Increase take-profit target to 1.8%",
                        "rejection_reason": None,
                        "parameter_adjustments": {"btc_tp_pct": 1.8},
                        "key_evidence": ["Strong trend continuation on 15m candle"],
                    },
                ][:limit]
            }

        # Default: 'mixed' scenario
        return {
            "advisories": [
                {
                    "decision_id": "adv_mix_01",
                    "timestamp": "2026-08-27T10:00:00Z",
                    "verdict": "APPLY",
                    "confidence": 0.85,
                    "recommendation": "Tighten BTC scalper stop-loss to 0.4%",
                    "parameter_adjustments": {"btc_sl_pct": 0.4},
                    "key_evidence": ["High ATR spike detected on BTC 5m chart"],
                },
                {
                    "decision_id": "adv_mix_02",
                    "timestamp": "2026-08-27T10:15:00Z",
                    "verdict": "REJECT",
                    "confidence": 0.91,
                    "recommendation": "Increase ETH max position size to 2.5x",
                    "rejection_reason": "Exceeds max account risk limit of 1.0x per asset",
                    "parameter_adjustments": {"eth_max_size": 2.5},
                    "key_evidence": ["Bullish momentum breakout and order book skew"],
                },
                {
                    "decision_id": "adv_mix_03",
                    "timestamp": "2026-08-27T10:30:00Z",
                    "verdict": "HOLD",
                    "confidence": 0.45,
                    "recommendation": "Maintain current risk parameters",
                    "key_evidence": ["Neutral market regime and low volume"],
                },
            ][:limit]
        }

    def get_advisory_state_payload(self) -> Dict[str, Any]:
        if self.scenario == "ai_universe_down":
            return {
                "ai_universe_enabled": True,
                "ai_universe_health": "DOWN",
                "active_overlay": {},
                "last_error": "HTTP 503 AI-Universe service unavailable",
                "last_consult_time": "2026-08-27T09:45:00Z",
            }

        if self.scenario == "all_applied":
            return {
                "ai_universe_enabled": True,
                "ai_universe_health": "HEALTHY",
                "active_overlay": {
                    "btc_sl_pct": 0.4,
                    "btc_tp_pct": 1.8,
                },
                "last_consult_time": "2026-08-27T10:20:00Z",
            }

        if self.scenario in ("all_rejected", "empty"):
            return {
                "ai_universe_enabled": True,
                "ai_universe_health": "HEALTHY",
                "active_overlay": {},
                "last_consult_time": "2026-08-27T10:00:00Z",
            }

        # Default 'mixed'
        return {
            "ai_universe_enabled": True,
            "ai_universe_health": "HEALTHY",
            "active_overlay": {
                "btc_sl_pct": 0.4
            },
            "last_consult_time": "2026-08-27T10:30:00Z",
        }

    def handle_panic(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        release = payload.get("release", False)
        self.panic_activated = not release
        self.panic_history.append(payload)
        if release:
            return {"status": "PANIC_RELEASED", "active": False, "message": "Normal trading operations resumed"}
        return {"status": "PANIC_ACTIVATED", "active": True, "message": "Emergency kill-switch active, all new orders blocked"}


class MockTradingBotHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler simulating the Trading Bot REST API."""

    state = MockTradingBotState()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if self.state.scenario == "unreachable":
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Service Unavailable"}).encode("utf-8"))
            return

        if path == "/api/status":
            payload = self.state.get_status_payload()
            self._respond_json(200, payload)
        elif path == "/api/advisory/recent":
            limit = int(query.get("limit", ["10"])[0])
            payload = self.state.get_advisory_recent_payload(limit=limit)
            self._respond_json(200, payload)
        elif path == "/api/advisory/state":
            payload = self.state.get_advisory_state_payload()
            self._respond_json(200, payload)
        elif path == "/api/recent-actions":
            self._respond_json(200, {"actions": ["FILTER: Passed BTC", "EXECUTE: LONG BTCUSDT @ 64500"]})
        else:
            self._respond_json(404, {"error": "Endpoint not found"})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if self.state.scenario == "unreachable":
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Service Unavailable"}).encode("utf-8"))
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        if path == "/api/panic":
            res = self.state.handle_panic(payload)
            self._respond_json(200, res)
        else:
            self._respond_json(404, {"error": "Endpoint not found"})

    def _respond_json(self, status_code: int, data: Any) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Suppress HTTP access logs during testing


class MockTradingBotServer:
    """Threaded local HTTP server for mock trading bot testing."""

    def __init__(self, port: int = 8999, scenario: str = "mixed") -> None:
        self.port = port
        self.state = MockTradingBotState(scenario=scenario)
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self) -> str:
        MockTradingBotHandler.state = self.state
        self.server = HTTPServer(("127.0.0.1", self.port), MockTradingBotHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
            self.thread = None

    def set_scenario(self, scenario: str) -> None:
        self.state.scenario = scenario
