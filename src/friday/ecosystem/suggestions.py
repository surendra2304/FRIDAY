"""Intelligent Task Suggestions Engine for FRIDAY Ecosystem.

Synthesizes trading performance metrics, FORGE historical build patterns,
and temporal schedules into actionable proactive suggestions for the operator.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger
from friday.core.readings import read_number

logger = get_logger("ecosystem.suggestions")


@dataclass
class SuggestionItem:
    """Proactive recommendation generated for the user."""
    suggestion_id: str
    category: str  # TRADING, FORGE, TEMPORAL
    prompt: str
    rationale: str
    action_type: str
    action_payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EcosystemSuggestionsEngine:
    """Analyzes telemetry streams across subsystems to generate proactive suggestions."""

    def __init__(self) -> None:
        self._counter = 0

    def generate_suggestions(
        self,
        trading_data: dict[str, Any] | None = None,
        nexus_data: dict[str, Any] | None = None,
        forge_history: list[dict[str, Any]] | None = None,
        current_time: datetime | None = None,
    ) -> list[SuggestionItem]:
        """Evaluates inputs and outputs targeted recommendations."""
        suggestions: list[SuggestionItem] = []
        now = current_time or datetime.now(timezone.utc)

        # 1. Trading-Based Suggestions
        # Every threshold here is now compared against a *reported* number. The
        # old code compared a missing profit factor against a default of 1.5 and
        # a missing leverage against 1.0: it could not fire on absent data, but
        # it also could not tell a genuine 1.0x from silence, and the rationale
        # string formatted the very default it had invented (0.8) as though the
        # strategy had reported it.
        if trading_data:
            # Underperforming strategy trigger
            strategies = trading_data.get("strategies", {})
            for name, strat in strategies.items():
                profit_factor = read_number(strat, "profit_factor", source=f"strategy '{name}'")
                strategy_pnl = read_number(strat, "pnl_usdt", source=f"strategy '{name}'")
                underperforming = (profit_factor.known and profit_factor.value < 1.0) or (
                    strategy_pnl.known and strategy_pnl.value < -100
                )
                if underperforming:
                    self._counter += 1
                    evidence = " and ".join(
                        f"{label} {reading.number(2)}"
                        for label, reading in (("profit factor", profit_factor), ("P&L", strategy_pnl))
                        if reading.known
                    )
                    suggestions.append(
                        SuggestionItem(
                            suggestion_id=f"sug_trade_{self._counter:03d}",
                            category="TRADING",
                            prompt=f"'{name}' is underperforming, want a strategy analysis from AI-Universe?",
                            rationale=f"Reported {evidence} USDT for '{name}'.",
                            action_type="consult_ai_universe_strategy",
                            action_payload={"strategy_name": name},
                        )
                    )

            # Elevated risk / leverage trigger
            leverage = read_number(trading_data, "aggregate_leverage", source="trading data")
            daily_loss = read_number(trading_data, "daily_loss_pct", source="trading data")
            if (leverage.known and leverage.value > 2.5) or (daily_loss.known and daily_loss.value > 4.0):
                self._counter += 1
                suggestions.append(
                    SuggestionItem(
                        suggestion_id=f"sug_risk_{self._counter:03d}",
                        category="TRADING",
                        prompt="Your risk is elevated — want me to build a risk dashboard?",
                        rationale=(
                            f"Reported leverage {leverage.number(1, 'x')} with daily loss at "
                            f"{daily_loss.number(1, '%')}."
                        ),
                        action_type="cross_build_risk_dashboard",
                        action_payload={"leverage": leverage.value if leverage.known else None},
                    )
                )

        # 2. Nexus Signal Suggestions
        if nexus_data:
            leads = nexus_data.get("leads", [])
            for l in leads:
                if l.get("score", 0) >= 90:
                    self._counter += 1
                    # "acme-corp.com" was the stand-in for a lead nobody had
                    # described. A suggestion that names a specific domain the
                    # input never mentioned is worse than one that does not fire.
                    domain = l.get("company_domain") or l.get("domain")
                    if not domain:
                        logger.debug("Skipping lead suggestion %s: no company domain reported", l.get("lead_id"))
                        continue
                    suggestions.append(
                        SuggestionItem(
                            suggestion_id=f"sug_nexus_{self._counter:03d}",
                            category="NEXUS",
                            prompt=f"High-intent lead detected from {domain}, want me to trigger follow-up workflow?",
                            rationale=(
                                f"Lead scored {l.get('score')}/100 with evidence: "
                                f"{l.get('evidence') or 'not stated'}."
                            ),
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
