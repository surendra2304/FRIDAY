# -*- coding: utf-8 -*-
"""Trading Bot Operator Skill for FRIDAY.

Interfaces autonomously with the external Algorithmic Trading Bot on Binance Futures Testnet
hosted at https://algorithmic-trading-bot-fra.onrender.com (or TRADING_BOT_URL).

Strict Safety Invariants:
- TESTNET ONLY: The Trading Bot is on Binance Futures Testnet. Never live trading.
- AUTHORIZATION: Critical operations like trigger_panic (kill-switch) require explicit
  authorization from FRIDAY's authorizer / AUTHORIZE phase.
"""

from dataclasses import dataclass, field
import json
import os
import re
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error

from friday.core.logging import get_logger
from friday.core.types import AuthorizationDecision, AuthorizationRequest, SafetyLevel
from friday.skills.base_skill import BaseSkill, SkillExecutionResult

logger = get_logger("skills.trading_bot_operator")

DEFAULT_BOT_URL = "https://algorithmic-trading-bot-fra.onrender.com"


@dataclass
class BotStatus:
    """Parsed metrics snapshot from /api/status."""
    status: str
    mode: str
    equity: float
    cash: float
    unrealized_pnl: float
    realized_pnl: float
    today_pnl: float
    profit_factor: float
    win_rate_pct: float
    open_positions: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


class TradingBotOperator(BaseSkill):
    """Interacts with the Algorithmic Trading Bot on Binance Futures Testnet."""

    name = "trading_bot_operator"
    description = "Monitors and controls the Algorithmic Trading Bot (Binance Futures Testnet), querying PnL, positions, signals, and managing safety panic controls."
    required_capabilities = ["network_access"]
    tools = ["trading_bot_query", "ai_universe_query"]
    system_prompt = (
        "You are FRIDAY's Trading Bot Operator. You monitor the Algorithmic Trading Bot's "
        "Binance Futures Testnet state, report equity, unrealized and realized PnL, open positions, "
        "and enforce strict authorization before activating safety panic kill-switches."
    )
    match_patterns = [
        r"\b(?:how\s+is\s+(?:the\s+)?trading\s+bot\s+doing|trading\s+bot\s+status|bot\s+status)\b",
        r"\b(?:check|get|show)\s+(?:the\s+)?(?:trading\s+bot|bot)\s+(?:pnl|status|positions?|performance|equity)\b",
        r"\b(?:trading\s+bot\s+pnl|bot\s+pnl)\b",
        r"\b(?:trading\s+bot|bot)\s+(?:panic|kill\s*switch|stop\s+trading|resume\s+trading|release\s+panic)\b",
        r"\b(?:trigger\s+panic|activate\s+kill\s*switch|release\s+kill\s*switch)\b",
        r"\b(?:trading\s+bot\s+signals?|bot\s+signals?|recent\s+signals?|recent\s+trades?)\b",
    ]

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, timeout: float = 15.0) -> None:
        self.base_url = (base_url or os.getenv("TRADING_BOT_URL") or DEFAULT_BOT_URL).rstrip("/")
        self.api_key = (api_key or os.getenv("TRADING_BOT_API_KEY") or os.getenv("BOT_API_KEY") or "").strip()
        self.timeout = timeout

    def _http_get(self, endpoint: str) -> Dict[str, Any]:
        """Perform HTTP GET request to Trading Bot."""
        url = f"{self.base_url}{endpoint}"
        headers = {
            "User-Agent": "FRIDAY-Agent/1.0",
            "Accept": "application/json"
        }
        if self.api_key:
            headers["X-BOT-API-KEY"] = self.api_key

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            logger.error(f"[TRADING_BOT] HTTP {e.code} on GET {url}: {e.reason}")
            raise RuntimeError(f"Trading Bot API returned HTTP {e.code}: {e.reason}") from e
        except Exception as e:
            logger.error(f"[TRADING_BOT] Error on GET {url}: {e}")
            raise RuntimeError(f"Failed to connect to Trading Bot at {url}: {e}") from e

    def _http_post(self, endpoint: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Perform HTTP POST request to Trading Bot with X-BOT-API-KEY security header."""
        url = f"{self.base_url}{endpoint}"
        data = json.dumps(payload or {}).encode("utf-8")
        headers = {
            "User-Agent": "FRIDAY-Agent/1.0",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        if self.api_key:
            headers["X-BOT-API-KEY"] = self.api_key

        req = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            logger.error(f"[TRADING_BOT] HTTP {e.code} on POST {url}: {e.reason}")
            raise RuntimeError(f"Trading Bot API returned HTTP {e.code}: {e.reason}") from e
        except Exception as e:
            logger.error(f"[TRADING_BOT] Error on POST {url}: {e}")
            raise RuntimeError(f"Failed to POST to Trading Bot at {url}: {e}") from e

    def get_bot_status(self) -> BotStatus:
        """Calls /api/status and parses equity, unrealized PnL, and open positions."""
        raw = self._http_get("/api/status")
        
        # Handle status payload structure
        equity = float(raw.get("equity", raw.get("current_equity", 0.0)))
        cash = float(raw.get("cash", raw.get("usdt_cash", 0.0)))
        unrealized = float(raw.get("unrealized_pnl", raw.get("open_pnl", 0.0)))
        realized = float(raw.get("realized_pnl", raw.get("closed_pnl", 0.0)))
        today_pnl = float(raw.get("today_pnl", unrealized + realized))
        profit_factor = float(raw.get("profit_factor", 0.0))
        win_rate = float(raw.get("win_rate", raw.get("win_rate_pct", 0.0)))
        mode = str(raw.get("trading_mode", raw.get("mode", "TESTNET"))).upper()
        
        # Extract open positions
        positions = raw.get("positions", raw.get("active_positions", []))
        if isinstance(positions, dict):
            positions = list(positions.values())

        return BotStatus(
            status=str(raw.get("status", "ACTIVE")).upper(),
            mode=mode,
            equity=equity,
            cash=cash,
            unrealized_pnl=unrealized,
            realized_pnl=realized,
            today_pnl=today_pnl,
            profit_factor=profit_factor,
            win_rate_pct=win_rate,
            open_positions=positions,
            raw=raw
        )

    def get_recent_signals(self) -> Dict[str, Any]:
        """Calls /api/recent-actions to fetch recent decision logs."""
        return self._http_get("/api/recent-actions")

    def trigger_panic(self) -> Dict[str, Any]:
        """Calls POST /api/panic to activate the safety kill-switch (blocks new orders)."""
        logger.warning("[TRADING_BOT] Triggering EMERGENCY PANIC KILL-SWITCH")
        return self._http_post("/api/panic", {"release": False})

    def release_panic(self) -> Dict[str, Any]:
        """Calls POST /api/panic with {'release': True} to resume trading operations."""
        logger.info("[TRADING_BOT] Releasing panic kill-switch")
        return self._http_post("/api/panic", {"release": True})

    def execute(
        self,
        user_request: str,
        agent: Optional[Any] = None,
        tool_registry: Optional[Any] = None,
        llm_provider: Optional[Any] = None,
        authorizer: Optional[Any] = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        """Executes trading bot queries and actions based on user request."""
        clean_req = user_request.strip().lower()
        step_results: List[Dict[str, Any]] = []

        try:
            # 1. Panic Trigger / Kill Switch (High-Risk Gated Operation)
            if any(k in clean_req for k in ["trigger panic", "activate kill switch", "activate panic", "stop trading", "kill switch on"]):
                if authorizer:
                    auth_req = AuthorizationRequest(
                        tool_name=self.name,
                        arguments={"action": "trigger_panic"},
                        safety_level=SafetyLevel.DANGEROUS,
                        purpose="Activate trading bot emergency kill-switch",
                        affected_resource=f"{self.base_url}/api/panic"
                    )
                    auth_resp = authorizer.authorize(auth_req)
                    if auth_resp.decision != AuthorizationDecision.APPROVED:
                        return SkillExecutionResult(
                            skill_name=self.name,
                            success=False,
                            output=f"Emergency panic kill-switch activation blocked: {auth_resp.reason}",
                            error="Authorization Denied",
                            step_results=[{"action": "authorize", "status": "DENIED"}]
                        )

                res = self.trigger_panic()
                step_results.append({"action": "trigger_panic", "response": res})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=(
                        "⚠️ Emergency Panic Kill-Switch Activated.\n"
                        "All new order placement on Binance Futures Testnet is now blocked. "
                        "Existing protective bracket orders (SL/TP) remain active."
                    ),
                    step_results=step_results,
                    metadata=res
                )

            # 2. Panic Release / Resume Trading
            if any(k in clean_req for k in ["release panic", "resume trading", "release kill switch", "disable panic", "kill switch off"]):
                if authorizer:
                    auth_req = AuthorizationRequest(
                        tool_name=self.name,
                        arguments={"action": "release_panic"},
                        safety_level=SafetyLevel.SENSITIVE,
                        purpose="Resume trading bot normal operations",
                        affected_resource=f"{self.base_url}/api/panic"
                    )
                    auth_resp = authorizer.authorize(auth_req)
                    if auth_resp.decision != AuthorizationDecision.APPROVED:
                        return SkillExecutionResult(
                            skill_name=self.name,
                            success=False,
                            output=f"Panic kill-switch release blocked: {auth_resp.reason}",
                            error="Authorization Denied",
                            step_results=[{"action": "authorize", "status": "DENIED"}]
                        )

                res = self.release_panic()
                step_results.append({"action": "release_panic", "response": res})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output="✅ Trading Bot Panic Kill-Switch has been released. Normal Testnet evaluation resumed.",
                    step_results=step_results,
                    metadata=res
                )

            # 3. Recent Signals / Actions Query
            if any(k in clean_req for k in ["recent signal", "recent actions", "recent trades", "bot signals"]):
                actions_data = self.get_recent_signals()
                actions = actions_data.get("actions", [])
                step_results.append({"action": "get_recent_signals", "count": len(actions)})
                
                formatted_actions = "\n".join(f"• {a}" for a in actions[:10]) if actions else "No recent actions recorded."
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=f"**Trading Bot Recent Actions & Decisions:**\n{formatted_actions}",
                    step_results=step_results,
                    metadata=actions_data
                )

            # 4. Default: Bot Status & PnL Inquiry ("Friday, how is the trading bot doing?")
            status = self.get_bot_status()
            step_results.append({"action": "get_bot_status", "equity": status.equity, "unrealized_pnl": status.unrealized_pnl})

            pos_count = len(status.open_positions)
            pnl_sign = "+" if status.unrealized_pnl >= 0 else ""
            
            output_spoken = (
                f"The trading bot is currently {status.status.lower()} on Binance Futures {status.mode}. "
                f"Total equity is ${status.equity:,.2f} USDT with an unrealized PnL of {pnl_sign}${status.unrealized_pnl:,.2f} USDT across {pos_count} active position{'s' if pos_count != 1 else ''}. "
                f"Today's cumulative PnL is ${status.today_pnl:,.2f} USDT with a profit factor of {status.profit_factor:.2f}."
            )

            return SkillExecutionResult(
                skill_name=self.name,
                success=True,
                output=output_spoken,
                step_results=step_results,
                metadata={
                    "equity": status.equity,
                    "cash": status.cash,
                    "unrealized_pnl": status.unrealized_pnl,
                    "realized_pnl": status.realized_pnl,
                    "today_pnl": status.today_pnl,
                    "profit_factor": status.profit_factor,
                    "open_positions": status.open_positions,
                    "mode": status.mode,
                }
            )

        except Exception as e:
            logger.error(f"[TRADING_BOT_OPERATOR] Execution failure: {e}", exc_info=True)
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output=f"I was unable to query the trading bot: {e}",
                error=str(e),
                step_results=step_results
            )
