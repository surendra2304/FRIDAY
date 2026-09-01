"""Multi-Strategy Coordinator for FRIDAY Trading.

Manages multi-strategy capital allocation, dynamic strategy rotation based on
market regimes, and directional conflict resolution between competing strategies.
"""

from dataclasses import dataclass
from typing import Any

from friday.core.logging import get_logger
from friday.trading.portfolio_analytics import PortfolioAnalyticsEngine
from friday.trading.regime_detector import MarketRegimeDetector, MarketState

logger = get_logger("trading.strategy_coordinator")


@dataclass
class StrategyAllocation:
    """Target capital allocation for an active strategy."""
    strategy_name: str
    target_weight_pct: float
    current_weight_pct: float
    status: str  # ACTIVE, REDUCED, PAUSED
    reason: str


@dataclass
class ConflictResolution:
    """Resolution of directional disagreements between multiple strategies."""
    symbol: str
    strategy_votes: dict[str, str]  # e.g., {"BTC_Trend": "LONG", "BTC_MeanRev": "SHORT"}
    resolved_action: str  # LONG, SHORT, NEUTRAL / FLAT
    resolution_rationale: str
    confidence: float


class MultiStrategyCoordinator:
    """Coordinates strategy weights, rotations, and conflict resolutions."""

    def __init__(
        self,
        analytics_engine: PortfolioAnalyticsEngine | None = None,
        regime_detector: MarketRegimeDetector | None = None,
    ) -> None:
        self.analytics_engine = analytics_engine or PortfolioAnalyticsEngine()
        self.regime_detector = regime_detector or MarketRegimeDetector()

    def optimize_allocations(
        self,
        current_regime: MarketState | None = None,
        strategy_metrics: dict[str, dict[str, Any]] | None = None,
    ) -> list[StrategyAllocation]:
        """Calculates optimal strategy weights based on current market regime and performance."""
        regime = current_regime or self.regime_detector.detect_regime().primary_regime
        metrics = strategy_metrics or {
            "BTC_Trend_Supertrend": {"sharpe": 2.10, "win_rate": 68.0, "current_weight": 0.35},
            "ETH_Mean_Reversion": {"sharpe": 1.45, "win_rate": 56.0, "current_weight": 0.35},
            "Volatility_Breakout": {"sharpe": 1.85, "win_rate": 62.0, "current_weight": 0.30},
        }

        allocations: list[StrategyAllocation] = []

        if regime in (MarketState.TRENDING_BULL_STRONG, MarketState.BREAKOUT):
            # Overweight trend and breakout strategies
            allocations.append(
                StrategyAllocation(
                    strategy_name="BTC_Trend_Supertrend",
                    target_weight_pct=50.0,
                    current_weight_pct=metrics["BTC_Trend_Supertrend"]["current_weight"] * 100.0,
                    status="ACTIVE",
                    reason="Optimal regime for trend continuation with strong momentum.",
                )
            )
            allocations.append(
                StrategyAllocation(
                    strategy_name="Volatility_Breakout",
                    target_weight_pct=35.0,
                    current_weight_pct=metrics["Volatility_Breakout"]["current_weight"] * 100.0,
                    status="ACTIVE",
                    reason="Favorable breakout conditions during trend expansion.",
                )
            )
            allocations.append(
                StrategyAllocation(
                    strategy_name="ETH_Mean_Reversion",
                    target_weight_pct=15.0,
                    current_weight_pct=metrics["ETH_Mean_Reversion"]["current_weight"] * 100.0,
                    status="REDUCED",
                    reason="Mean-reversion underperforms during strong directional trends.",
                )
            )
        elif regime == MarketState.RANGING_QUIET:
            # Overweight mean-reversion
            allocations.append(
                StrategyAllocation(
                    strategy_name="ETH_Mean_Reversion",
                    target_weight_pct=55.0,
                    current_weight_pct=metrics["ETH_Mean_Reversion"]["current_weight"] * 100.0,
                    status="ACTIVE",
                    reason="Optimal quiet ranging regime for mean-reversion and scalping.",
                )
            )
            allocations.append(
                StrategyAllocation(
                    strategy_name="BTC_Trend_Supertrend",
                    target_weight_pct=25.0,
                    current_weight_pct=metrics["BTC_Trend_Supertrend"]["current_weight"] * 100.0,
                    status="REDUCED",
                    reason="Low trend strength in quiet market.",
                )
            )
            allocations.append(
                StrategyAllocation(
                    strategy_name="Volatility_Breakout",
                    target_weight_pct=20.0,
                    current_weight_pct=metrics["Volatility_Breakout"]["current_weight"] * 100.0,
                    status="REDUCED",
                    reason="Low breakout frequency.",
                )
            )
        else:
            # Balanced allocation
            allocations.append(
                StrategyAllocation(
                    strategy_name="BTC_Trend_Supertrend",
                    target_weight_pct=40.0,
                    current_weight_pct=metrics["BTC_Trend_Supertrend"]["current_weight"] * 100.0,
                    status="ACTIVE",
                    reason="Balanced allocation across diversified strategy mix.",
                )
            )
            allocations.append(
                StrategyAllocation(
                    strategy_name="ETH_Mean_Reversion",
                    target_weight_pct=35.0,
                    current_weight_pct=metrics["ETH_Mean_Reversion"]["current_weight"] * 100.0,
                    status="ACTIVE",
                    reason="Balanced allocation.",
                )
            )
            allocations.append(
                StrategyAllocation(
                    strategy_name="Volatility_Breakout",
                    target_weight_pct=25.0,
                    current_weight_pct=metrics["Volatility_Breakout"]["current_weight"] * 100.0,
                    status="ACTIVE",
                    reason="Balanced allocation.",
                )
            )

        return allocations

    def resolve_strategy_conflict(
        self,
        symbol: str,
        strategy_signals: dict[str, str],
        current_regime: MarketState | None = None,
    ) -> ConflictResolution:
        """Resolves contradictory directional signals between competing strategies."""
        regime = current_regime or self.regime_detector.detect_regime().primary_regime
        votes = {k: v.upper() for k, v in strategy_signals.items()}

        long_count = sum(1 for v in votes.values() if v == "LONG")
        short_count = sum(1 for v in votes.values() if v == "SHORT")

        if long_count > 0 and short_count > 0:
            # Conflict exists
            if regime in (MarketState.TRENDING_BULL_STRONG, MarketState.BREAKOUT):
                resolved = "LONG"
                conf = 0.85
                rationale = "Trend strength in higher timeframes overrides mean-reversion short signals."
            elif regime in (MarketState.TRENDING_BEAR_STRONG,):
                resolved = "SHORT"
                conf = 0.85
                rationale = "Bearish macro trend overrides long pullback signals."
            elif regime == MarketState.RANGING_QUIET:
                resolved = "FLAT"
                conf = 0.70
                rationale = "Equivocal signals in ranging regime resolved to FLAT to preserve capital."
            else:
                resolved = "LONG" if long_count >= short_count else "SHORT"
                conf = 0.65
                rationale = "Majority vote resolution under neutral regime."
        elif long_count > 0:
            resolved = "LONG"
            conf = 0.90
            rationale = "All strategy signals aligned on LONG."
        elif short_count > 0:
            resolved = "SHORT"
            conf = 0.90
            rationale = "All strategy signals aligned on SHORT."
        else:
            resolved = "FLAT"
            conf = 1.00
            rationale = "All strategies in observation / HOLD state."

        return ConflictResolution(
            symbol=symbol,
            strategy_votes=votes,
            resolved_action=resolved,
            resolution_rationale=rationale,
            confidence=conf,
        )
