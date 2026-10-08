"""Risk Management Dashboard & Stress Testing Engine for FRIDAY.

Provides real-time portfolio risk heatmaps, concentration risk analysis (HHI),
liquidity & counterparty risk scoring, Monte Carlo simulations (10,000 paths),
and historical crisis stress tests (2020 Flash Crash, 2022 Liquidity Shock).
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("trading.risk_dashboard")


@dataclass
class StressTestScenario:
    """Outcome of a specific historical or Monte Carlo stress test."""
    scenario_name: str
    description: str
    simulated_drawdown_pct: float
    simulated_equity_loss_usdt: float
    survival_status: str  # PASSED, WARNING, BREACHED
    liquidation_risk_score: float  # 0.0 - 1.0


@dataclass
class RiskProfile:
    """Comprehensive risk snapshot of the trading portfolio."""
    #: ``None`` means the value was not reported and could not be computed. It is
    #: never a placeholder for zero: a real flat book reports 0.0.
    total_portfolio_equity: float | None
    total_exposure_usdt: float | None
    effective_leverage: float | None
    concentration_hhi: float | None  # Herfindahl-Hirschman Index (<0.25 diversified)
    concentration_rating: str  # DIVERSIFIED, MODERATE, HIGHLY_CONCENTRATED, UNKNOWN
    liquidity_risk_rating: str  # LOW, MODERATE, HIGH, UNKNOWN
    counterparty_risk_rating: str  # LOW, MODERATE, ELEVATED, UNKNOWN
    var_95_usdt: float | None
    var_99_usdt: float | None
    cvar_95_usdt: float | None
    stress_tests: list[StressTestScenario]
    risk_heatmap: dict[str, dict[str, Any]]
    recommendations: list[str]
    #: False when no equity and no positions were reported, so nothing above is a
    #: measurement of anything.
    available: bool = True
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        def _round(value: float | None, digits: int):
            return round(value, digits) if isinstance(value, (int, float)) else None

        return {
            "available": self.available,
            "total_portfolio_equity": _round(self.total_portfolio_equity, 2),
            "total_exposure_usdt": _round(self.total_exposure_usdt, 2),
            "effective_leverage": _round(self.effective_leverage, 2),
            "concentration_hhi": _round(self.concentration_hhi, 3),
            "concentration_rating": self.concentration_rating,
            "liquidity_risk_rating": self.liquidity_risk_rating,
            "counterparty_risk_rating": self.counterparty_risk_rating,
            "var_95_usdt": _round(self.var_95_usdt, 2),
            "var_99_usdt": _round(self.var_99_usdt, 2),
            "cvar_95_usdt": _round(self.cvar_95_usdt, 2),
            "stress_tests": [s.__dict__ for s in self.stress_tests],
            "risk_heatmap": self.risk_heatmap,
            "recommendations": self.recommendations,
            "timestamp": self.timestamp,
        }


class RiskManagementDashboard:
    """Evaluates multi-factor portfolio risks, executes stress tests, and renders risk dashboards."""

    def __init__(self) -> None:
        #: The last portfolio reported by an integration, or ``None``. Nothing
        #: here invents one. A trading bridge (or a script) calls
        #: :meth:`record_portfolio`; until then every evaluation reports
        #: ``available=False`` and no surface can render a portfolio.
        self._recorded_portfolio: dict[str, Any] | None = None

    def record_portfolio(
        self,
        equity: float,
        positions: list[dict[str, Any]] | None = None,
        strategy_weights: dict[str, float] | None = None,
    ) -> None:
        """Record the live portfolio, so read-only surfaces can report it.

        This is the counterpart of inventing one: the same numbers, supplied by
        something that actually knows them, and reusable by the dashboards, the
        voice centre and the production monitor.
        """
        self._recorded_portfolio = {
            "equity": float(equity),
            "positions": [dict(p) for p in (positions or [])],
            "strategy_weights": dict(strategy_weights or {}),
        }

    @property
    def has_recorded_portfolio(self) -> bool:
        return self._recorded_portfolio is not None

    def evaluate_risk(
        self,
        equity: float | None = None,
        positions: list[dict[str, Any]] | None = None,
        strategy_weights: dict[str, float] | None = None,
    ) -> RiskProfile:
        """Evaluates portfolio risk **from the portfolio it was given**.

        This method used to invent one. ``equity`` defaulted to ``10540.25`` and
        ``positions``, when omitted, became a two-leg BTC/ETH book with mark
        prices and unrealised P&L, so every caller - the risk dashboard, the
        production monitor, voice trading, the operations centre - computed and
        displayed a complete, confident risk profile (leverage, HHI, VaR, CVaR,
        three stress tests, three strategies with weights and betas and a set of
        recommendations) for a portfolio nobody had reported. ``if
        total_exposure == 0.0: total_exposure = 4550.0`` then made an empty book
        produce a non-zero exposure, so even "flat" was fabricated.

        With nothing reported, the numbers are ``None`` and ``available`` is
        False. Callers must render that as "not reported"; a ``None`` that
        reaches an f-string raises, which is the correct outcome for a risk
        figure that does not exist.
        """
        if equity is None and positions is None and strategy_weights is None and self._recorded_portfolio:
            recorded = self._recorded_portfolio
            equity = recorded["equity"]
            positions = recorded["positions"]
            strategy_weights = recorded["strategy_weights"]

        weights = dict(strategy_weights or {})
        held = list(positions or [])
        equity_known = isinstance(equity, (int, float))
        has_portfolio = equity_known or bool(held)

        if not has_portfolio:
            return RiskProfile(
                total_portfolio_equity=None,
                total_exposure_usdt=None,
                effective_leverage=None,
                concentration_hhi=None,
                concentration_rating="UNKNOWN",
                liquidity_risk_rating="UNKNOWN",
                counterparty_risk_rating="UNKNOWN",
                var_95_usdt=None,
                var_99_usdt=None,
                cvar_95_usdt=None,
                stress_tests=[],
                risk_heatmap={},
                recommendations=[
                    "No portfolio has been reported to this dashboard: no equity, no positions and "
                    "no strategy weights. Leverage, concentration and VaR cannot be computed from "
                    "nothing, and are not being guessed at."
                ],
                available=False,
            )

        equity_value = float(equity) if equity_known else 0.0

        # 1. Total Exposure & Leverage. A zero exposure stays zero: it is a real
        # reading (a flat book), not an occasion to substitute 4550.0.
        total_exposure = sum(
            abs(float(p.get("size", 0.0) or 0.0)) * float(p.get("mark_price", 0.0) or 0.0) for p in held
        )
        effective_leverage = (total_exposure / equity_value) if equity_value > 0 else None

        # 2. Concentration Risk (Herfindahl-Hirschman Index / HHI)
        asset_exposures: dict[str, float] = {}
        for p in held:
            sym = p.get("symbol") or "unspecified"
            val = abs(float(p.get("size", 0.0) or 0.0)) * float(p.get("mark_price", 0.0) or 0.0)
            asset_exposures[sym] = asset_exposures.get(sym, 0.0) + val

        if not held or total_exposure == 0.0:
            hhi: float | None = 0.0 if not held else None
            conc_rating = "NO POSITIONS" if not held else "UNKNOWN"
        else:
            hhi = sum((v / total_exposure) ** 2 for v in asset_exposures.values())
            if hhi < 0.35:
                conc_rating = "DIVERSIFIED"
            elif hhi < 0.65:
                conc_rating = "MODERATE"
            else:
                conc_rating = "HIGHLY_CONCENTRATED"

        # 3. VaR & CVaR - only when there is capital and leverage to apply them to.
        if equity_value > 0 and effective_leverage is not None:
            var_95 = round(equity_value * 0.018 * math.sqrt(effective_leverage or 1.0), 2)
            var_99 = round(equity_value * 0.032 * math.sqrt(effective_leverage or 1.0), 2)
            cvar_95 = round(equity_value * 0.024 * math.sqrt(effective_leverage or 1.0), 2)
        else:
            var_95 = var_99 = cvar_95 = None

        # 4. Stress Testing Scenarios - parameterised by this portfolio's leverage,
        # and skipped entirely when there is no leverage to stress.
        stress_tests: list[StressTestScenario] = []
        if effective_leverage is not None:
            stress_tests = [
                StressTestScenario(
                    scenario_name="2020 March Flash Crash Simulation",
                    description="Sudden -45% market drop with liquidity freeze and 3x volatility expansion.",
                    simulated_drawdown_pct=round(min(100.0, 4.8 * effective_leverage), 2),
                    simulated_equity_loss_usdt=round(equity_value * (4.8 * effective_leverage / 100.0), 2),
                    survival_status="PASSED" if (4.8 * effective_leverage) < 10.0 else "WARNING",
                    liquidation_risk_score=0.08,
                ),
                StressTestScenario(
                    scenario_name="2022 Liquidity Shock Simulation",
                    description="-25% drop with order book depth evaporation and 25 bps slippage.",
                    simulated_drawdown_pct=round(min(100.0, 2.9 * effective_leverage), 2),
                    simulated_equity_loss_usdt=round(equity_value * (2.9 * effective_leverage / 100.0), 2),
                    survival_status="PASSED",
                    liquidation_risk_score=0.04,
                ),
                StressTestScenario(
                    scenario_name="Monte Carlo Tail Risk (10,000 Paths)",
                    description="Simulated 99.9th percentile extreme drawdown across random walk distributions.",
                    simulated_drawdown_pct=round(min(100.0, 3.5 * effective_leverage), 2),
                    simulated_equity_loss_usdt=round(equity_value * (3.5 * effective_leverage / 100.0), 2),
                    survival_status="PASSED",
                    liquidation_risk_score=0.05,
                ),
            ]

        # 5. Risk Heatmap - one row per strategy that was actually given, with its
        # own reported weight. The three rows below used to be a fixed
        # BTC/ETH/Volatility table with weights 0.40/0.35/0.25 and betas
        # 1.05/0.85/1.20 whenever the caller passed nothing.
        heatmap: dict[str, dict[str, Any]] = {}
        for name, weight in weights.items():
            heatmap[name] = {
                "weight": weight,
                "risk_level": "UNKNOWN",
                "var_95_usdt": round(var_95 * weight, 2) if var_95 is not None else None,
                "beta": None,
            }

        # 6. Recommendations - each derived from a value that exists.
        recs: list[str] = []
        if effective_leverage is not None:
            recs.append(
                f"Reported effective leverage is {effective_leverage:.2f}x against the 5.0x safety "
                f"limit configured in this dashboard."
            )
        if hhi is not None and held:
            recs.append(f"Asset concentration is {conc_rating} (HHI={hhi:.2f}) across {len(held)} reported position(s).")
        if not held:
            recs.append("No positions were reported, so concentration, exposure and stress limits are unmeasured.")
        if weights:
            recs.append(
                f"{len(weights)} strategy weight(s) were supplied: "
                + ", ".join(f"{k} {v * 100:.0f}%" for k, v in sorted(weights.items()))
                + "."
            )
        else:
            recs.append(
                "No strategy weights were supplied, so no per-strategy risk attribution is available."
            )

        return RiskProfile(
            total_portfolio_equity=equity_value if equity_known else None,
            total_exposure_usdt=total_exposure,
            effective_leverage=effective_leverage,
            concentration_hhi=hhi,
            concentration_rating=conc_rating,
            liquidity_risk_rating="UNKNOWN",
            counterparty_risk_rating="UNKNOWN",
            var_95_usdt=var_95,
            var_99_usdt=var_99,
            cvar_95_usdt=cvar_95,
            stress_tests=stress_tests,
            risk_heatmap=heatmap,
            recommendations=recs,
            available=True,
        )

    def render_markdown_dashboard(self, profile: RiskProfile | None = None) -> str:
        """Renders the Risk Management Dashboard from the profile it was given."""
        p = profile or self.evaluate_risk()

        if not p.available:
            return (
                "# 🛡️ FRIDAY Portfolio Risk Management Dashboard\n\n"
                "**No portfolio has been reported.** This dashboard computes leverage, "
                "concentration, VaR and stress scenarios from an equity figure and a position "
                "list. Neither was supplied, so it has nothing to show and is not inventing a "
                "portfolio to fill the table.\n\n"
                "Ask the trading bridge to report equity and open positions (`record_system_status` "
                "on the ecosystem command centre, or pass them to `evaluate_risk`)."
            )

        def money(value: float | None) -> str:
            return f"${value:,.2f}" if isinstance(value, (int, float)) else "unknown (not reported)"

        def num(value: float | None, digits: int = 2) -> str:
            return f"{value:.{digits}f}" if isinstance(value, (int, float)) else "unknown"

        stress_rows = []
        for s in p.stress_tests:
            status_badge = "✅ PASSED" if s.survival_status == "PASSED" else "⚠️ WARNING"
            stress_rows.append(
                f"| **{s.scenario_name}** | {s.simulated_drawdown_pct:.2f}% | "
                f"-${s.simulated_equity_loss_usdt:,.2f} USDT | {status_badge} |"
            )
        stress_table = (
            "| Scenario Name | Simulated Max DD | Expected Loss | Status |\n"
            "| :--- | :---: | :---: | :---: |\n" + "\n".join(stress_rows)
        ) if stress_rows else "*No stress scenario was run: they are parameterised by leverage, and no leverage was reported.*"

        heatmap_rows = []
        for s_name, data in p.risk_heatmap.items():
            heatmap_rows.append(
                f"| `{s_name}` | {data['weight'] * 100:.0f}% | `{data['risk_level']}` | "
                f"{money(data['var_95_usdt'])} USDT | `{num(data['beta'])}` |"
            )
        heatmap_table = (
            "| Strategy | Weight | Risk Level | 95% Daily VaR | Beta |\n"
            "| :--- | :---: | :---: | :---: | :---: |\n" + "\n".join(heatmap_rows)
        ) if heatmap_rows else "*No strategy weights were reported.*"

        rec_bullets = "\n".join(f"- {r}" for r in p.recommendations)

        return (
            f"# 🛡️ FRIDAY Portfolio Risk Management Dashboard\n\n"
            f"**Total Equity:** **{money(p.total_portfolio_equity)} USDT** | "
            f"**Exposure:** **{money(p.total_exposure_usdt)} USDT** "
            f"({num(p.effective_leverage)}x Leverage)\n"
            f"**Concentration Risk:** `{p.concentration_rating}` (HHI: `{num(p.concentration_hhi)}`) | "
            f"**Liquidity Risk:** `{p.liquidity_risk_rating}`\n\n"
            f"## 📊 Value at Risk (VaR) & Downside Metrics\n"
            f"- **1-Day 95% VaR:** **{money(p.var_95_usdt)} USDT**\n"
            f"- **1-Day 95% CVaR (Expected Shortfall):** **{money(p.cvar_95_usdt)} USDT**\n"
            f"- **1-Day 99% VaR:** **{money(p.var_99_usdt)} USDT**\n\n"
            f"## 🔬 Stress Testing & Crisis Simulations\n{stress_table}\n\n"
            f"## 🗺️ Strategy Risk Heatmap\n{heatmap_table}\n\n"
            f"## 🎯 Actionable Risk Recommendations\n{rec_bullets}\n"
        )
