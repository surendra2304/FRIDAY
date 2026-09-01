"""Stratex Trading Bot Operator Skill for FRIDAY.

Interfaces autonomously with the external Stratex 24/7 Algorithmic Trading Platform on Binance Futures Testnet
hosted at https://stratex-ucjz.onrender.com (or STRATEX_URL).

Command Precedence & Safety Invariants:
1. Safety Gates (in Trading Bot) [Highest Authority]: Hard risk boundaries, max drawdown, testnet invariant.
2. FRIDAY Commands (Supervisor): Manual override and emergency kill-switch activation via bot REST API.
3. AI-Universe Recommendations (Advisor): Consultative advice logged to append-only advisory log.

Critical Contract:
- FRIDAY commands can override AI-Universe advisory recommendations, but can NEVER bypass or override
  the Trading Bot's own hardcoded safety gates.
- The `trigger_panic()` / `panic()` command triggers the Trading Bot's OWN kill-switch API (POST /api/panic).
  FRIDAY does not implement its own internal trading kill logic; it invokes the bot's authoritative kill-switch.
- The trading bot has a direct connection to AI-Universe on a schedule, logging recommendations to advisory_log.jsonl.
  FRIDAY acts as the SUPERVISOR monitoring bot metrics and AI advisory activity.
"""

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import AuthorizationDecision, AuthorizationRequest, SafetyLevel
from friday.skills.base_skill import BaseSkill, SkillExecutionResult
from friday.skills.trading_precedence import (
    CommandPrecedence,
    tag_trading_command,
    validate_precedence_invariants,
)

logger = get_logger("skills.trading_bot_operator")

DEFAULT_BOT_URL = "https://stratex-ucjz.onrender.com"


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
    open_positions: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class TradingBotOperator(BaseSkill):
    """Supervises and controls Stratex (Algorithmic Trading Platform)."""

    name = "trading_bot_operator"
    description = (
        "Supervises and controls Stratex (Algorithmic Trading Platform on Binance Futures Testnet), "
        "monitoring equity, positions, advisory logs, AI overlay state, and managing safety panic controls."
    )
    required_capabilities = ["network_access", "trading_bot_control"]
    tools = ["trading_bot_query", "ai_universe_query"]
    system_prompt = (
        "You are FRIDAY's Trading Bot Operator for Stratex. You supervise the 24/7 Stratex Algorithmic Trading Platform on "
        "Binance Futures Testnet. You report equity, PnL, open positions, supervise AI-Universe advisories, "
        "and enforce strict authorization before activating the bot's emergency panic kill-switch."
    )
    match_patterns = [
        r"\b(?:how\s+is\s+(?:the\s+)?(?:stratex|trading\s+bot)\s+doing|(?:stratex|trading\s+bot)\s+status|bot\s+status)\b",
        r"\b(?:check|get|show)\s+(?:the\s+)?(?:stratex|trading\s+bot|bot)\s+(?:pnl|status|positions?|performance|equity)\b",
        r"\b(?:stratex|trading\s+bot|bot)\s+pnl\b",
        r"\b(?:stratex|trading\s+bot|bot)\s+(?:panic|kill\s*switch|stop\s+trading|resume\s+trading|release\s+panic)\b",
        r"\b(?:trigger\s+panic|activate\s+kill\s*switch|release\s+kill\s*switch)\b",
        r"\b(?:stratex|trading\s+bot|bot)\s+(?:signals?|recent\s+signals?|recent\s+trades?)\b",
    ]

    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float = 15.0) -> None:
        self.base_url = (base_url or os.getenv("STRATEX_URL") or os.getenv("TRADING_BOT_URL") or DEFAULT_BOT_URL).rstrip("/")
        self.api_key = (api_key or os.getenv("STRATEX_API_KEY") or os.getenv("BOT_API_KEY") or os.getenv("TRADING_BOT_API_KEY") or "").strip()
        self.timeout = timeout

    def _http_get(self, endpoint: str) -> dict[str, Any]:
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

    def _http_post(self, endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
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
        
        equity = float(raw.get("equity", raw.get("current_equity", 0.0)))
        cash = float(raw.get("cash", raw.get("usdt_cash", 0.0)))
        unrealized = float(raw.get("unrealized_pnl", raw.get("open_pnl", 0.0)))
        realized = float(raw.get("realized_pnl", raw.get("closed_pnl", 0.0)))
        today_pnl = float(raw.get("today_pnl", unrealized + realized))
        profit_factor = float(raw.get("profit_factor", 0.0))
        win_rate = float(raw.get("win_rate", raw.get("win_rate_pct", 0.0)))
        mode = str(raw.get("trading_mode", raw.get("mode", "TESTNET"))).upper()
        
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

    def get_recent_signals(self) -> dict[str, Any]:
        """Calls /api/recent-actions to fetch recent decision logs."""
        return self._http_get("/api/recent-actions")

    def get_advisory_recent(self, limit: int = 10) -> dict[str, Any]:
        """Calls /api/advisory/recent?limit=N to retrieve recent AI-Universe recommendations."""
        return self._http_get(f"/api/advisory/recent?limit={max(1, limit)}")

    def get_advisory_state(self) -> dict[str, Any]:
        """Calls /api/advisory/state to inspect the active AI parameter overlay."""
        return self._http_get("/api/advisory/state")

    def get_ab_status(self) -> dict[str, Any]:
        """Calls /api/ab/status to retrieve live A/B experiment progress, arms, and statistical metrics."""
        return self._http_get("/api/ab/status")

    def get_testnet_advisory_status(self) -> dict[str, Any]:
        """Calls /api/testnet/advisory/status to retrieve testnet advisory mode, health, and active overlays."""
        return self._http_get("/api/testnet/advisory/status")

    def get_testnet_advisory_log(self, limit: int = 10) -> dict[str, Any]:
        """Calls /api/testnet/advisory/log to retrieve recent testnet advisory decisions."""
        return self._http_get(f"/api/testnet/advisory/log?limit={limit}")

    def get_testnet_paper_comparison(self) -> dict[str, Any]:
        """Calls /api/testnet/paper/compare to retrieve side-by-side testnet vs paper trading execution metrics."""
        return self._http_get("/api/testnet/paper/compare")

    def toggle_testnet_advisory(self, enabled: bool = True, mode: str = "SHADOW") -> dict[str, Any]:
        """Calls POST /api/testnet/advisory/toggle to enable/disable testnet advisory or switch mode."""
        payload = {
            "enabled": bool(enabled),
            "mode": str(mode).upper(),
            "_precedence": tag_trading_command("toggle_testnet_advisory", CommandPrecedence.FRIDAY_COMMANDS),
        }
        return self._http_post("/api/testnet/advisory/toggle", payload)

    def rollback_testnet_parameters(self) -> dict[str, Any]:
        """Calls POST /api/testnet/advisory/rollback to revert all testnet parameters to default baseline."""
        payload = {
            "action": "ROLLBACK",
            "_precedence": tag_trading_command("rollback_testnet_parameters", CommandPrecedence.FRIDAY_COMMANDS),
        }
        return self._http_post("/api/testnet/advisory/rollback", payload)

    def get_advisory_summary(self) -> str:
        """Compose a concise human/voice-friendly summary of recent AI advisory activity."""
        try:
            recent_data = self.get_advisory_recent(limit=20)
            advisories = recent_data.get("advisories", recent_data.get("recent_advisories", []))
            if isinstance(recent_data, list):
                advisories = recent_data

            state_data = self.get_advisory_state()
            active_overlay = state_data.get("active_overlay", state_data.get("overlay", {}))
            ai_health = state_data.get("ai_universe_health", state_data.get("health", "HEALTHY")).upper()

            total_count = len(advisories)
            applied_count = sum(1 for a in advisories if str(a.get("verdict", "")).upper() == "APPLY")
            rejected_count = sum(1 for a in advisories if str(a.get("verdict", "")).upper() == "REJECT")
            hold_count = total_count - (applied_count + rejected_count)

            last_rejected_reason = None
            for a in advisories:
                if str(a.get("verdict", "")).upper() == "REJECT":
                    last_rejected_reason = a.get("rejection_reason", a.get("reason", "Safety boundaries exceeded"))
                    break

            overlay_str = (
                ", ".join(f"{k}={v}" for k, v in active_overlay.items())
                if active_overlay
                else "No active parameter modifications"
            )

            rejection_clause = f" Last rejection reason: '{last_rejected_reason}'." if last_rejected_reason else ""

            return (
                f"AI-Universe Advisory is {ai_health}. In recent activity: {total_count} recommendations evaluated "
                f"({applied_count} applied, {rejected_count} rejected by bot safety bounds). "
                f"Active overlay parameters: {overlay_str}.{rejection_clause}"
            )
        except Exception as e:
            logger.warning(f"[TRADING_BOT] Failed to compose advisory summary: {e}")
            return f"AI-Universe Advisory telemetry currently unavailable: {e}"

    def get_status(self) -> dict[str, Any]:
        """Calls /api/status to retrieve live trading bot metrics dict."""
        return self._http_get("/api/status")

    def trigger_panic(self, authorizer: Any | None = None) -> dict[str, Any]:
        """Calls POST /api/panic to activate the safety kill-switch (blocks new orders)."""
        logger.warning("[TRADING_BOT] Triggering EMERGENCY PANIC KILL-SWITCH via Bot REST API")
        tag = tag_trading_command("trigger_panic", CommandPrecedence.FRIDAY_COMMANDS)
        return self._http_post("/api/panic", {"release": False, "_precedence": tag})

    def panic(self) -> dict[str, Any]:
        """Alias for trigger_panic(); invokes trading bot's authoritative kill-switch API."""
        return self.trigger_panic()

    def release_panic(self) -> dict[str, Any]:
        """Calls POST /api/panic with {'release': True} to resume trading operations."""
        logger.info("[TRADING_BOT] Releasing panic kill-switch via Bot REST API")
        tag = tag_trading_command("release_panic", CommandPrecedence.FRIDAY_COMMANDS)
        return self._http_post("/api/panic", {"release": True, "_precedence": tag})

    def execute(
        self,
        user_request: str,
        agent: Any | None = None,
        tool_registry: Any | None = None,
        llm_provider: Any | None = None,
        authorizer: Any | None = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        """Executes trading bot queries, supervisor inspections, and safety actions."""
        clean_req = user_request.strip().lower()
        step_results: list[dict[str, Any]] = []

        try:
            # Precedence validation check
            if not validate_precedence_invariants(clean_req):
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=False,
                    output="Action blocked: Attempting to bypass Trading Bot safety gates is strictly prohibited.",
                    error="Precedence Invariant Violation",
                    step_results=[{"action": "validate_precedence", "status": "REJECTED"}]
                )

            # 1. Panic Release / Resume Trading
            if any(k in clean_req for k in ["release panic", "resume trading", "release kill switch", "disable panic", "kill switch off"]):
                if authorizer:
                    auth_req = AuthorizationRequest(
                        tool_name=self.name,
                        arguments={"action": "release_panic"},
                        safety_level=SafetyLevel.SENSITIVE,
                        purpose="Resume trading bot normal operations via /api/panic",
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

            # 2. Panic Trigger / Kill Switch (High-Risk Gated Operation)
            if any(k in clean_req for k in ["trigger panic", "activate kill switch", "activate panic", "stop trading", "kill switch on", "panic"]):
                if authorizer:
                    auth_req = AuthorizationRequest(
                        tool_name=self.name,
                        arguments={"action": "trigger_panic"},
                        safety_level=SafetyLevel.DANGEROUS,
                        purpose="Activate trading bot emergency kill-switch via /api/panic",
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
                        "⚠️ Emergency Panic Kill-Switch Activated via Trading Bot API.\n"
                        "All new order placement on Binance Futures Testnet is now blocked by the bot. "
                        "Existing protective bracket orders (SL/TP) remain active under bot safety gates."
                    ),
                    step_results=step_results,
                    metadata=res
                )

            # 3. Advisory Queries (Recommendations / State / Rejected)
            if any(k in clean_req for k in ["what did ai-universe recommend", "what did ai recommend", "ai recommendations", "advisories"]):
                adv_data = self.get_advisory_recent(limit=10)
                advisories = adv_data.get("advisories", adv_data.get("recent_advisories", []))
                if isinstance(adv_data, list):
                    advisories = adv_data
                step_results.append({"action": "get_advisory_recent", "count": len(advisories)})

                if not advisories:
                    msg = "No recent AI-Universe advisory recommendations recorded in the trading log."
                else:
                    lines = []
                    for a in advisories[:5]:
                        verdict = str(a.get("verdict", "UNKNOWN")).upper()
                        conf = int(float(a.get("confidence", 0.0)) * 100)
                        rec = a.get("recommendation", a.get("summary", "Adjust parameters"))
                        reason = f" (Reason: {a.get('rejection_reason', a.get('reason', ''))})" if verdict == "REJECT" else ""
                        lines.append(f"• [{verdict} - {conf}% Conf] {rec}{reason}")
                    msg = "**Recent AI-Universe Advisory Decisions:**\n" + "\n".join(lines)

                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=msg,
                    step_results=step_results,
                    metadata=adv_data
                )

            if any(k in clean_req for k in ["rejected advisories", "show me rejected"]):
                adv_data = self.get_advisory_recent(limit=25)
                advisories = adv_data.get("advisories", adv_data.get("recent_advisories", []))
                if isinstance(adv_data, list):
                    advisories = adv_data
                rejected = [a for a in advisories if str(a.get("verdict", "")).upper() == "REJECT"]
                step_results.append({"action": "get_advisory_recent_rejected", "count": len(rejected)})

                if not rejected:
                    msg = "No rejected AI-Universe advisories found in the recent log. All recommendations were either applied or hold."
                else:
                    lines = []
                    for a in rejected[:5]:
                        conf = int(float(a.get("confidence", 0.0)) * 100)
                        rec = a.get("recommendation", a.get("summary", "Parameter change"))
                        reason = a.get("rejection_reason", a.get("reason", "Bounds violation"))
                        lines.append(f"• [REJECTED - {conf}% Conf] {rec}\n  *Rejection Reason:* {reason}")
                    msg = "**Rejected AI-Universe Advisories (Filtered by Bot Safety Gates):**\n" + "\n".join(lines)

                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=msg,
                    step_results=step_results,
                    metadata={"rejected": rejected}
                )

            if any(k in clean_req for k in ["parameters has the ai changed", "advisory state", "ai overlay", "overlay parameters"]):
                state = self.get_advisory_state()
                overlay = state.get("active_overlay", state.get("overlay", {}))
                step_results.append({"action": "get_advisory_state", "overlay": overlay})

                if not overlay:
                    msg = "The AI-Universe has not applied any active parameter modifications. Bot is running standard base parameters."
                else:
                    lines = [f"• **{k}**: {v}" for k, v in overlay.items()]
                    msg = "**Active AI-Universe Parameter Overlay:**\n" + "\n".join(lines)

                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=msg,
                    step_results=step_results,
                    metadata=state
                )

            # 4. Recent Signals / Actions Query
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

            # 5. Default: Bot Status + Advisory Summary ("Friday, how is the trading bot doing?")
            status = self.get_bot_status()
            advisory_summary = self.get_advisory_summary()
            step_results.append({"action": "get_bot_status", "equity": status.equity, "unrealized_pnl": status.unrealized_pnl})

            pos_count = len(status.open_positions)
            pnl_sign = "+" if status.unrealized_pnl >= 0 else ""
            
            output_spoken = (
                f"The trading bot is currently {status.status.lower()} on Binance Futures {status.mode}. "
                f"Total equity is ${status.equity:,.2f} USDT with an unrealized PnL of {pnl_sign}${status.unrealized_pnl:,.2f} USDT across {pos_count} active position{'s' if pos_count != 1 else ''}. "
                f"Today's cumulative PnL is ${status.today_pnl:,.2f} USDT with a profit factor of {status.profit_factor:.2f}. "
                f"{advisory_summary}"
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
                    "advisory_summary": advisory_summary,
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
