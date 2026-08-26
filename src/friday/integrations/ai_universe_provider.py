# -*- coding: utf-8 -*-
"""AI Universe Provider and Trading Bot Strategy Consultation Client for FRIDAY.

Orchestrates deliberative consultations between FRIDAY and AI Universe:
Flow:
1. FRIDAY retrieves live trading bot status / telemetry from Render.
2. FRIDAY delegates analysis to AI Universe (/v1/friday/ask or /v1/friday/debate).
3. AI Universe Trading Analyst & panel evaluate win rate, profit factor, drawdown, etc.
4. AI Universe returns structured recommendation with evidence.
5. FRIDAY records/logs the recommendation, but DOES NOT auto-apply it unless explicitly authorized by the user.
"""

from dataclasses import dataclass, field
import json
import os
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger
from friday.skills.trading_bot_operator import BotStatus, TradingBotOperator
from friday.tools.ai_universe_client import AIUniverseClient, AIUniverseResponse

logger = get_logger("integrations.ai_universe_provider")


@dataclass
class TradingConsultationResult:
    """Consolidated outcome of an AI Universe strategy consultation."""
    bot_status: BotStatus
    ai_universe_response: AIUniverseResponse
    recommendation: str
    confidence: float
    evidence: List[str]
    applied_to_bot: bool = False
    requires_user_authorization: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def format_summary(self) -> str:
        """Format human-readable summary for FRIDAY to present or speak."""
        evidence_str = "\n".join(f"  • {e}" for e in self.evidence) if self.evidence else "  • No empirical flags"
        return (
            f"📊 **AI Universe Strategy Consultation Summary**\n"
            f"**Current Bot Status:** Equity ${self.bot_status.equity:,.2f} USDT | PnL ${self.bot_status.today_pnl:,.2f} | PF {self.bot_status.profit_factor:.2f}\n"
            f"**Recommendation:** {self.recommendation}\n"
            f"**Calibrated Confidence:** {int(self.confidence * 100)}%\n"
            f"**Key Empirical Evidence:**\n{evidence_str}\n\n"
            f"⚠️ *Notice: This recommendation has been recorded in audit telemetry. "
            f"In accordance with safety policies, parameter adjustments are NOT auto-applied and require explicit user authorization.*"
        )


class AIUniverseTradingConsultant:
    """Coordinates advisory consultations with AI Universe for trading strategy adjustments."""

    def __init__(
        self,
        bot_operator: Optional[TradingBotOperator] = None,
        universe_client: Optional[AIUniverseClient] = None
    ) -> None:
        self.bot_operator = bot_operator or TradingBotOperator()
        self.universe_client = universe_client or AIUniverseClient()

    async def consult_on_bot_performance(
        self,
        question_override: Optional[str] = None,
        mode: str = "ask",
        max_agents: int = 3
    ) -> TradingConsultationResult:
        """
        Gathers live trading bot metrics, constructs consultation payload, queries AI Universe,
        and returns structured recommendation without auto-applying changes.
        """
        # Step 1: Query Trading Bot state from Render
        bot_status = self.bot_operator.get_bot_status()
        
        # Step 2: Build deliberative prompt for AI Universe
        metrics_payload = {
            "equity": bot_status.equity,
            "cash": bot_status.cash,
            "unrealized_pnl": bot_status.unrealized_pnl,
            "realized_pnl": bot_status.realized_pnl,
            "today_pnl": bot_status.today_pnl,
            "profit_factor": bot_status.profit_factor,
            "win_rate_pct": bot_status.win_rate_pct,
            "open_positions_count": len(bot_status.open_positions),
            "trading_mode": bot_status.mode
        }
        
        default_question = (
            f"Analyze recent Binance Futures testnet performance metrics: "
            f"Equity=${bot_status.equity:,.2f}, Unrealized PnL=${bot_status.unrealized_pnl:,.2f}, "
            f"Today's PnL=${bot_status.today_pnl:,.2f}, Profit Factor={bot_status.profit_factor:.2f}, "
            f"Win Rate={bot_status.win_rate_pct:.1f}%, Open Positions={len(bot_status.open_positions)}. "
            f"Advise if scalper stop loss / take profit parameters or risk exposure require calibration."
        )
        query = question_override or default_question

        # Step 3: Query AI Universe
        logger.info(f"[AI_UNIVERSE_CONSULTANT] Querying AI Universe in mode '{mode}'")
        if mode == "debate":
            response = await self.universe_client.debate(question=query, max_agents=max_agents)
        else:
            response = await self.universe_client.ask(question=query, mode=mode)

        # Step 4: Extract recommendations & maintain strict non-auto-execution invariant
        recommendation = response.answer
        evidence = response.key_evidence
        
        logger.info(f"[AI_UNIVERSE_CONSULTANT] Received advice with confidence {response.confidence:.2f}")

        return TradingConsultationResult(
            bot_status=bot_status,
            ai_universe_response=response,
            recommendation=recommendation,
            confidence=response.confidence,
            evidence=evidence,
            applied_to_bot=False,
            requires_user_authorization=True,
            metadata={"metrics_evaluated": metrics_payload, "agents_used": response.agents_used}
        )
