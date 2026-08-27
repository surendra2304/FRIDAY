# -*- coding: utf-8 -*-
"""Intelligent Task Suggestions Engine for FRIDAY Ecosystem.

Synthesizes trading performance metrics, FORGE historical build patterns,
and temporal schedules into actionable proactive suggestions for the operator.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger

logger = get_logger("ecosystem.suggestions")


@dataclass
class SuggestionItem:
    """Proactive recommendation generated for the user."""
    suggestion_id: str
    category: str  # TRADING, FORGE, TEMPORAL
    prompt: str
    rationale: str
    action_type: str
    action_payload: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EcosystemSuggestionsEngine:
    """Analyzes telemetry streams across subsystems to generate proactive suggestions."""

    def __init__(self) -> None:
        self._counter = 0

    def generate_suggestions(
        self,
        trading_data: Optional[Dict[str, Any]] = None,
        forge_history: Optional[List[Dict[str, Any]]] = None,
        current_time: Optional[datetime] = None,
    ) -> List[SuggestionItem]:
        """Evaluates inputs and outputs targeted recommendations."""
        suggestions: List[SuggestionItem] = []
        now = current_time or datetime.now(timezone.utc)

        # 1. Trading-Based Suggestions
        if trading_data:
            # Underperforming strategy trigger
            strategies = trading_data.get("strategies", {})
            for name, strat in strategies.items():
                if strat.get("profit_factor", 1.5) < 1.0 or strat.get("pnl_usdt", 0) < -100:
                    self._counter += 1
                    suggestions.append(
                        SuggestionItem(
                            suggestion_id=f"sug_trade_{self._counter:03d}",
                            category="TRADING",
                            prompt=f"Your {name} strategy is underperforming — want me to ask Forge to build a strategy analyzer?",
                            rationale=f"Strategy '{name}' has a profit factor of {strat.get('profit_factor', 0.8):.2f}.",
                            action_type="cross_build_strategy_analyzer",
                            action_payload={"strategy_name": name},
                        )
                    )

            # Elevated risk / leverage trigger
            leverage = trading_data.get("aggregate_leverage", 1.0)
            daily_loss = trading_data.get("daily_loss_pct", 0.0)
            if leverage > 2.5 or daily_loss > 4.0:
                self._counter += 1
                suggestions.append(
                    SuggestionItem(
                        suggestion_id=f"sug_risk_{self._counter:03d}",
                        category="TRADING",
                        prompt="Your risk is elevated — want me to build a risk dashboard?",
                        rationale=f"Current portfolio leverage is {leverage:.1f}x with daily loss at {daily_loss:.1f}%.",
                        action_type="cross_build_risk_dashboard",
                        action_payload={"leverage": leverage},
                    )
                )

        # 2. FORGE History-Based Suggestions
        if forge_history:
            website_builds = [t for t in forge_history if "website" in t.get("goal", "").lower() or t.get("type") == "WEBSITE"]
            if len(website_builds) >= 3:
                self._counter += 1
                suggestions.append(
                    SuggestionItem(
                        suggestion_id=f"sug_forge_{self._counter:03d}",
                        category="FORGE",
                        prompt="You've built 3 websites this week — want a website template for future builds?",
                        rationale="Multiple similar website requests detected across FORGE build history.",
                        action_type="create_custom_template",
                        action_payload={"template_type": "WEBSITE_CUSTOM"},
                    )
                )

        # 3. Time Pattern Suggestions
        # Monday is weekday 0
        if now.weekday() == 0 and now.hour < 12:
            self._counter += 1
            suggestions.append(
                SuggestionItem(
                    suggestion_id=f"sug_time_{self._counter:03d}",
                    category="TEMPORAL",
                    prompt="It's Monday morning — want your weekly trading report?",
                    rationale="Weekly market opening routine.",
                    action_type="generate_weekly_report",
                    action_payload={"period": "WEEKLY"},
                )
            )

        return suggestions
