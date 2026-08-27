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
        nexus_data: Optional[Dict[str, Any]] = None,
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
                            prompt=f"Supertrend underperforming, want a strategy analysis from AI-Universe?",
                            rationale=f"Strategy '{name}' has a profit factor of {strat.get('profit_factor', 0.8):.2f}.",
                            action_type="consult_ai_universe_strategy",
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

        # 2. Nexus Signal Suggestions
        if nexus_data:
            leads = nexus_data.get("leads", [])
            for l in leads:
                if l.get("score", 0) >= 90:
                    self._counter += 1
                    domain = l.get("company_domain", "acme-corp.com")
                    suggestions.append(
                        SuggestionItem(
                            suggestion_id=f"sug_nexus_{self._counter:03d}",
                            category="NEXUS",
                            prompt=f"High-intent lead detected from {domain}, want me to trigger follow-up workflow?",
                            rationale=f"Lead scored {l.get('score')}/100 with evidence: {l.get('evidence', 'enterprise visit')}.",
                            action_type="trigger_lead_followup_workflow",
                            action_payload={"lead_id": l.get("lead_id"), "domain": domain},
                        )
                    )

        # 3. FORGE History-Based Suggestions
        if forge_history:
            dashboard_builds = [t for t in forge_history if "dashboard" in t.get("goal", "").lower() or t.get("type") == "DASHBOARD"]
            if len(dashboard_builds) >= 3:
                self._counter += 1
                suggestions.append(
                    SuggestionItem(
                        suggestion_id=f"sug_forge_{self._counter:03d}",
                        category="FORGE",
                        prompt="You've built 3 dashboards, want a reusable template for future builds?",
                        rationale="Multiple dashboard builds detected in FORGE task history.",
                        action_type="create_dashboard_template",
                        action_payload={"template_type": "DASHBOARD_REUSABLE"},
                    )
                )

            website_builds = [t for t in forge_history if "website" in t.get("goal", "").lower() or t.get("type") == "WEBSITE"]
            if len(website_builds) >= 3:
                self._counter += 1
                suggestions.append(
                    SuggestionItem(
                        suggestion_id=f"sug_forge_web_{self._counter:03d}",
                        category="FORGE",
                        prompt="You've built 3 websites this week — want a website template for future builds?",
                        rationale="Multiple similar website requests detected across FORGE build history.",
                        action_type="create_custom_template",
                        action_payload={"template_type": "WEBSITE_CUSTOM"},
                    )
                )

        # 4. Time Pattern Suggestions (Monday morning)
        if now.weekday() == 0 and now.hour < 12:
            self._counter += 1
            suggestions.append(
                SuggestionItem(
                    suggestion_id=f"sug_time_{self._counter:03d}",
                    category="TEMPORAL",
                    prompt="Monday morning, want the weekly ecosystem report?",
                    rationale="Weekly executive briefing routine on Monday morning.",
                    action_type="generate_weekly_report",
                    action_payload={"period": "WEEKLY"},
                )
            )

        return suggestions
