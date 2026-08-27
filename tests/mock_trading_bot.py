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

    def get_ab_status_payload(self) -> Dict[str, Any]:
        if self.scenario == "ab_no_test":
            return {"status": "NO_ACTIVE_TEST", "message": "No active A/B experiment running"}

        if self.scenario == "ab_drawdown_terminated":
            return {
                "test_name": "AI_Universe_Volatility_Overlay",
                "status": "DRAWDOWN_TERMINATED",
                "elapsed_hours": 36.5,
                "planned_hours": 168.0,
                "progress_pct": 21.7,
                "control_arm": {
                    "equity": 9850.00,
                    "total_return_pct": -1.50,
                    "sharpe_ratio": -0.45,
                    "win_rate_pct": 45.0,
                    "profit_factor": 0.88,
                    "max_drawdown_pct": 3.20,
                    "trade_count": 18,
                },
                "treatment_arm": {
                    "equity": 8950.00,
                    "total_return_pct": -10.50,
                    "sharpe_ratio": -1.82,
                    "win_rate_pct": 30.0,
                    "profit_factor": 0.42,
                    "max_drawdown_pct": 11.20,  # Breached max drawdown threshold
                    "trade_count": 20,
                },
                "statistics": {
                    "p_value": 0.042,
                    "stat_sig_achieved": True,
                    "confidence": 95.8,
                },
                "termination_reason": "Treatment arm max drawdown breached 10.0% safety boundary",
            }

        if self.scenario == "ab_completed":
            return {
                "test_name": "AI_Universe_Volatility_Overlay",
                "status": "COMPLETED",
                "elapsed_hours": 168.0,
                "planned_hours": 168.0,
                "progress_pct": 100.0,
                "control_arm": {
                    "equity": 10320.00,
                    "total_return_pct": 3.20,
                    "sharpe_ratio": 1.15,
                    "win_rate_pct": 58.0,
                    "profit_factor": 1.45,
                    "max_drawdown_pct": 2.80,
                    "trade_count": 84,
                },
                "treatment_arm": {
                    "equity": 11150.00,
                    "total_return_pct": 11.50,
                    "sharpe_ratio": 2.35,
                    "win_rate_pct": 71.0,
                    "profit_factor": 2.40,
                    "max_drawdown_pct": 1.90,
                    "trade_count": 88,
                    "active_overlays": {"btc_sl_pct": 0.4, "btc_tp_pct": 1.8},
                },
                "statistics": {
                    "p_value": 0.008,
                    "stat_sig_achieved": True,
                    "confidence": 99.2,
                },
            }

        if self.scenario == "ab_stat_sig_reached":
            return {
                "test_name": "AI_Universe_Volatility_Overlay",
                "status": "RUNNING",
                "elapsed_hours": 120.0,
                "planned_hours": 168.0,
                "progress_pct": 71.4,
                "control_arm": {
                    "equity": 10210.00,
                    "total_return_pct": 2.10,
                    "sharpe_ratio": 0.95,
                    "win_rate_pct": 54.0,
                    "profit_factor": 1.30,
                    "max_drawdown_pct": 2.90,
                    "trade_count": 62,
                },
                "treatment_arm": {
                    "equity": 10840.00,
                    "total_return_pct": 8.40,
                    "sharpe_ratio": 2.10,
                    "win_rate_pct": 68.0,
                    "profit_factor": 2.15,
                    "max_drawdown_pct": 1.80,
                    "trade_count": 65,
                    "active_overlays": {"btc_sl_pct": 0.4},
                },
                "statistics": {
                    "p_value": 0.015,
                    "stat_sig_achieved": True,
                    "confidence": 98.5,
                },
            }

        # Default 'mixed' or 'ab_running'
        return {
            "test_name": "AI_Universe_Volatility_Overlay",
            "status": "RUNNING",
            "elapsed_hours": 72.0,
            "planned_hours": 168.0,
            "progress_pct": 42.9,
            "control_arm": {
                "equity": 10180.00,
                "total_return_pct": 1.80,
                "sharpe_ratio": 0.85,
                "win_rate_pct": 52.0,
                "profit_factor": 1.25,
                "max_drawdown_pct": 3.10,
                "trade_count": 38,
            },
            "treatment_arm": {
                "equity": 10720.00,
                "total_return_pct": 7.20,
                "sharpe_ratio": 1.95,
                "win_rate_pct": 65.0,
                "profit_factor": 2.05,
                "max_drawdown_pct": 1.95,
                "trade_count": 40,
                "active_overlays": {"btc_sl_pct": 0.4},
            },
            "statistics": {
                "p_value": 0.082,
                "stat_sig_achieved": False,
                "confidence": 91.8,
            },
        }

    def get_testnet_advisory_status_payload(self) -> Dict[str, Any]:
        if self.scenario == "testnet_ai_down":
            return {
                "enabled": True,
                "mode": "SHADOW",
                "ai_universe_health": "DOWN",
                "equity": 10540.25,
                "drawdown_pct": 1.85,
                "max_drawdown_limit": 5.0,
                "last_consult_time": "2026-08-27T11:00:00Z",
                "active_overlay": {},
                "open_positions": [{"symbol": "BTCUSDT", "side": "LONG", "size": 0.05}],
            }

        if self.scenario == "testnet_drawdown_breach":
            return {
                "enabled": True,
                "mode": "APPLY",
                "ai_universe_health": "HEALTHY",
                "equity": 9360.00,
                "drawdown_pct": 6.40,
                "max_drawdown_limit": 5.0,
                "last_consult_time": "2026-08-27T11:30:00Z",
                "active_overlay": {"btc_sl_pct": 0.4, "eth_max_leverage": 5},
                "open_positions": [{"symbol": "BTCUSDT", "side": "LONG", "size": 0.05}],
            }

        if self.scenario == "testnet_apply":
            return {
                "enabled": True,
                "mode": "APPLY",
                "ai_universe_health": "HEALTHY",
                "equity": 10850.50,
                "drawdown_pct": 1.45,
                "max_drawdown_limit": 5.0,
                "last_consult_time": "2026-08-27T11:30:00Z",
                "active_overlay": {"btc_sl_pct": 0.4, "btc_tp_pct": 1.8},
                "open_positions": [
                    {"symbol": "BTCUSDT", "side": "LONG", "size": 0.05, "unrealized_pnl": 120.00},
                    {"symbol": "ETHUSDT", "side": "SHORT", "size": 0.50, "unrealized_pnl": 45.00},
                ],
            }

        # Default 'testnet_shadow' or 'mixed'
        return {
            "enabled": True,
            "mode": "SHADOW",
            "ai_universe_health": "HEALTHY",
            "equity": 10540.25,
            "drawdown_pct": 1.85,
            "max_drawdown_limit": 5.0,
            "last_consult_time": "2026-08-27T11:15:00Z",
            "active_overlay": {},
            "open_positions": [
                {"symbol": "BTCUSDT", "side": "LONG", "size": 0.05, "unrealized_pnl": 95.50},
                {"symbol": "ETHUSDT", "side": "SHORT", "size": 0.50, "unrealized_pnl": 44.75},
            ],
        }

    def get_testnet_advisory_log_payload(self, limit: int = 10) -> Dict[str, Any]:
        return {
            "advisories": [
                {
                    "decision_id": "testnet_adv_01",
                    "timestamp": "2026-08-27T11:00:00Z",
                    "mode": "SHADOW",
                    "verdict": "APPLY",
                    "confidence": 0.88,
                    "recommendation": "Tighten testnet BTC scalper stop-loss to 0.4%",
                    "parameter_adjustments": {"btc_sl_pct": 0.4},
                    "key_evidence": ["ATR expansion pattern on 5m chart"],
                },
                {
                    "decision_id": "testnet_adv_02",
                    "timestamp": "2026-08-27T11:15:00Z",
                    "mode": "SHADOW",
                    "verdict": "REJECT",
                    "confidence": 0.93,
                    "recommendation": "Expand ETH leverage to 12x",
                    "rejection_reason": "Exceeds testnet safety limit of 5x max leverage",
                    "parameter_adjustments": {"eth_max_leverage": 12},
                    "key_evidence": ["Order book bid depth imbalance"],
                },
                {
                    "decision_id": "testnet_adv_03",
                    "timestamp": "2026-08-27T11:30:00Z",
                    "mode": "SHADOW",
                    "verdict": "HOLD",
                    "confidence": 0.50,
                    "recommendation": "Maintain testnet volatility bracket",
                    "key_evidence": ["Balanced volume delta"],
                },
            ][:limit]
        }

    def get_testnet_paper_compare_payload(self) -> Dict[str, Any]:
        return {
            "paper_trading": {
                "total_return_pct": 4.20,
                "sharpe_ratio": 1.45,
                "avg_slippage_bps": 0.5,
                "fill_rate_pct": 100.0,
                "max_drawdown_pct": 2.10,
            },
            "testnet_live": {
                "total_return_pct": 3.85,
                "sharpe_ratio": 1.38,
                "avg_slippage_bps": 2.8,
                "fill_rate_pct": 98.5,
                "max_drawdown_pct": 2.45,
            },
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
        elif path == "/api/ab/status":
            payload = self.state.get_ab_status_payload()
            self._respond_json(200, payload)
        elif path == "/api/testnet/advisory/status":
            payload = self.state.get_testnet_advisory_status_payload()
            self._respond_json(200, payload)
        elif path in ("/api/testnet/advisory/log", "/api/testnet/advisory/recent"):
            limit = int(query.get("limit", ["10"])[0])
            payload = self.state.get_testnet_advisory_log_payload(limit=limit)
            self._respond_json(200, payload)
        elif path == "/api/testnet/paper/compare":
            payload = self.state.get_testnet_paper_compare_payload()
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
        elif path == "/api/testnet/advisory/toggle":
            mode = payload.get("mode", "SHADOW")
            enabled = payload.get("enabled", True)
            self._respond_json(200, {"status": "SUCCESS", "enabled": enabled, "mode": mode, "message": f"Testnet advisory mode set to {mode}"})
        elif path == "/api/testnet/advisory/rollback":
            self._respond_json(200, {"status": "SUCCESS", "action": "ROLLBACK", "message": "All testnet parameter overlays rolled back to default baseline"})
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
