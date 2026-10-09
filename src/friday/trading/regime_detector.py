"""Market Regime Detection Engine for FRIDAY.

Detects multi-timeframe market states (Trending, Ranging, Breakout, Reversal)
using ADX/DMI, Bollinger Bands width, ATR, Volume Profile, and Market Breadth,
providing strategy suitability mapping and adaptive risk sizing recommendations.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("trading.regime_detector")


class MarketState(str, Enum):
    TRENDING_BULL_STRONG = "TRENDING_BULL_STRONG"
    TRENDING_BEAR_STRONG = "TRENDING_BEAR_STRONG"
    TRENDING_WEAK = "TRENDING_WEAK"
    RANGING_VOLATILE = "RANGING_VOLATILE"
    RANGING_QUIET = "RANGING_QUIET"
    BREAKOUT = "BREAKOUT"
    REVERSAL = "REVERSAL"
    #: No supported classification was established from the supplied readings.
    #: This includes missing/ambiguous inputs and values outside explicit regimes.
    UNKNOWN = "UNKNOWN"


@dataclass
class TimeframeRegime:
    """Regime classification for a specific timeframe."""
    timeframe: str  # 1m, 5m, 15m, 1h, 4h, 1d
    state: MarketState
    adx_value: float
    bbw_pct: float
    atr_pct: float
    trend_direction: str  # BULLISH, BEARISH, NEUTRAL, or UNKNOWN
    confidence: float


@dataclass
class RegimeRecommendation:
    """Strategy and risk management advice tailored to current market regime."""
    primary_regime: MarketState
    timeframe_consensus: str
    suitable_strategies: list[str]
    unsuitable_strategies: list[str]
    risk_level: str  # LOW, MODERATE, HIGH, EXTREME
    #: None when no market data was supplied, because the size and stop factors
    #: are functions of the classification that was never made.
    position_sizing_multiplier: float | None  # e.g., 0.5x - 1.5x
    stop_loss_adjustment_factor: float | None  # e.g., 0.8x - 1.4x
    explanation: str
    timeframes: dict[str, TimeframeRegime]
    #: False when supplied readings are insufficient to support a regime and
    #: its associated strategy/risk recommendations.
    available: bool = True
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "primary_regime": self.primary_regime.value,
            "timeframe_consensus": self.timeframe_consensus,
            "suitable_strategies": self.suitable_strategies,
            "unsuitable_strategies": self.unsuitable_strategies,
            "risk_level": self.risk_level,
            "position_sizing_multiplier": self.position_sizing_multiplier,
            "stop_loss_adjustment_factor": self.stop_loss_adjustment_factor,
            "explanation": self.explanation,
            "timeframes": {k: v.__dict__ for k, v in self.timeframes.items()},
            "timestamp": self.timestamp,
        }


class MarketRegimeDetector:
    """Analyzes market structure and indicators across multiple timeframes to classify regime."""

    def __init__(self) -> None:
        self.timeframes = ["1m", "5m", "15m", "1h", "4h", "1d"]

    @staticmethod
    def _unavailable(
        symbol: str,
        reason: str,
        timeframes: dict[str, TimeframeRegime] | None = None,
    ) -> RegimeRecommendation:
        explanation = f"No market regime could be classified for {symbol}: {reason}"
        return RegimeRecommendation(
            primary_regime=MarketState.UNKNOWN,
            timeframe_consensus=reason,
            suitable_strategies=[],
            unsuitable_strategies=[],
            risk_level="UNKNOWN",
            position_sizing_multiplier=None,
            stop_loss_adjustment_factor=None,
            explanation=explanation,
            timeframes=timeframes or {},
            available=False,
        )

    def detect_regime(
        self,
        symbol: str = "BTCUSDT",
        market_data: dict[str, Any] | None = None,
        timeframe: str | None = None,
    ) -> RegimeRecommendation:
        """Classify only the timeframes represented by actual indicator readings.

        ``market_data`` may be a flat indicator object paired with the explicit
        ``timeframe`` argument, or a mapping from timeframe names to indicator
        objects (optionally nested under ``timeframes``). A single observation
        is never rescaled or copied into unobserved timeframes. Bullish/bearish
        strong-trend labels require an explicit direction or measured +DI/-DI;
        ADX magnitude alone cannot establish direction.
        """
        if not isinstance(market_data, dict):
            return self._unavailable(symbol, "indicator data was not supplied as an object.")
        data = market_data
        nested_frames = data.get("timeframes")
        if nested_frames is not None:
            if not isinstance(nested_frames, dict):
                return self._unavailable(symbol, "the `timeframes` field must map timeframe names to readings.")
            frame_inputs = nested_frames
        else:
            frame_inputs = {
                name: data[name]
                for name in self.timeframes
                if name in data
            }
            if not frame_inputs:
                observed_timeframe = timeframe or data.get("timeframe")
                if not isinstance(observed_timeframe, str) or not observed_timeframe.strip():
                    return self._unavailable(
                        symbol,
                        "timeframe attribution is missing; supply `timeframe` for one reading or "
                        "a per-timeframe `timeframes` mapping.",
                    )
                frame_inputs = {observed_timeframe.strip(): data}

        if not frame_inputs:
            return self._unavailable(symbol, "no timeframe readings were supplied.")

        tf_results: dict[str, TimeframeRegime] = {}
        required = {"adx", "bbw_pct", "atr_pct"}
        rejected: list[str] = []
        for raw_tf, raw_reading in frame_inputs.items():
            tf = str(raw_tf).strip()
            if tf not in self.timeframes:
                return self._unavailable(symbol, f"unsupported timeframe `{tf}` was supplied.")
            if not isinstance(raw_reading, dict):
                rejected.append(f"{tf}: indicator reading is not an object")
                continue

            missing = sorted(key for key in required if raw_reading.get(key) is None)
            if missing:
                rejected.append(f"{tf}: missing {', '.join(missing)}")
                continue
            try:
                adx = float(raw_reading["adx"])
                bbw = float(raw_reading["bbw_pct"])
                atr = float(raw_reading["atr_pct"])
            except (TypeError, ValueError):
                rejected.append(f"{tf}: indicator values must be numeric")
                continue
            if (
                not all(math.isfinite(value) for value in (adx, bbw, atr))
                or not 0.0 <= adx <= 100.0
                or bbw < 0.0
                or atr < 0.0
            ):
                rejected.append(f"{tf}: indicator values are outside valid finite ranges")
                continue

            direction = str(raw_reading.get("trend_direction") or "").strip().upper()
            if direction not in {"BULLISH", "BEARISH", "NEUTRAL"}:
                direction = "UNKNOWN"
                try:
                    plus_di = float(raw_reading["plus_di"])
                    minus_di = float(raw_reading["minus_di"])
                    if (
                        math.isfinite(plus_di)
                        and math.isfinite(minus_di)
                        and plus_di >= 0.0
                        and minus_di >= 0.0
                    ):
                        direction = (
                            "BULLISH" if plus_di > minus_di
                            else "BEARISH" if minus_di > plus_di
                            else "NEUTRAL"
                        )
                except (KeyError, TypeError, ValueError):
                    pass

            # Classify the measured values for this timeframe; never scale one
            # timeframe's reading into another timeframe's evidence.
            if adx >= 25.0 and bbw >= 3.0:
                if adx >= 30.0 and direction == "BULLISH":
                    state = MarketState.TRENDING_BULL_STRONG
                elif adx >= 30.0 and direction == "BEARISH":
                    state = MarketState.TRENDING_BEAR_STRONG
                else:
                    state = MarketState.BREAKOUT
                conf = 0.88 if state in (
                    MarketState.TRENDING_BULL_STRONG,
                    MarketState.TRENDING_BEAR_STRONG,
                ) else 0.80
            elif adx >= 25.0:
                state = MarketState.TRENDING_WEAK
                conf = 0.72
            elif adx < 20.0 and bbw >= 4.0:
                state = MarketState.RANGING_VOLATILE
                direction = "NEUTRAL"
                conf = 0.81
            elif adx < 20.0 and bbw < 2.0:
                state = MarketState.RANGING_QUIET
                direction = "NEUTRAL"
                conf = 0.85
            elif adx >= 20.0:
                state = MarketState.TRENDING_WEAK
                conf = 0.60
            else:
                # The inputs landed between the supported volatility bands.
                # Preserve the measurements, but do not manufacture a regime or
                # downstream sizing recommendation from the gap.
                state = MarketState.UNKNOWN
                direction = "UNKNOWN"
                conf = 0.0

            tf_results[tf] = TimeframeRegime(
                timeframe=tf,
                state=state,
                adx_value=adx,
                bbw_pct=bbw,
                atr_pct=atr,
                trend_direction=direction,
                confidence=conf,
            )

        if not tf_results:
            details = "; ".join(rejected) or "no usable timeframe readings"
            return self._unavailable(
                symbol,
                f"no complete, valid indicator set was supplied ({details}).",
            )

        # 2. Primary timeframe and summary use only observed readings. Prefer 1h
        # when present; otherwise use the longest measured timeframe.
        primary_tf = "1h" if "1h" in tf_results else max(
            tf_results,
            key=self.timeframes.index,
        )
        primary_regime = tf_results[primary_tf].state
        if primary_regime is MarketState.UNKNOWN:
            return self._unavailable(
                symbol,
                f"the measured {primary_tf} readings do not meet a supported regime threshold.",
                timeframes=tf_results,
            )

        observed = len(tf_results)
        directions = [
            value.trend_direction
            for value in tf_results.values()
            if value.trend_direction in {"BULLISH", "BEARISH"}
        ]
        if observed == 1:
            consensus_str = f"No cross-timeframe consensus: one measured timeframe ({primary_tf})."
        elif directions:
            primary_direction = tf_results[primary_tf].trend_direction
            if primary_direction in {"BULLISH", "BEARISH"}:
                aligned = sum(direction == primary_direction for direction in directions)
                consensus_str = (
                    f"{primary_direction} direction on {aligned} of {len(directions)} "
                    f"directionally measured timeframe(s); primary timeframe {primary_tf}."
                )
            else:
                consensus_str = (
                    f"No directional consensus: primary timeframe {primary_tf} has no measured "
                    "direction."
                )
        else:
            consensus_str = (
                f"No directional consensus across {observed} supplied timeframe(s); "
                "direction was not measured."
            )
        if rejected:
            consensus_str += f" Incomplete readings omitted: {'; '.join(rejected)}."

        # 3. Strategy and risk recommendations follow the measured primary regime.
        if primary_regime in (
            MarketState.TRENDING_BULL_STRONG,
            MarketState.TRENDING_BEAR_STRONG,
        ):
            suitable = ["BTC_Supertrend_Momentum", "Breakout_ATR_Channel", "Trend_Following_EMA"]
            unsuitable = ["Tight_Mean_Reversion", "Grid_Scalper"]
            risk_level = "MODERATE"
            size_mult = 1.25
            sl_mult = 1.20
            explanation = (
                f"Market is in a **{primary_regime.value}** regime at the measured {primary_tf} "
                f"timeframe (ADX={tf_results[primary_tf].adx_value}). Trend-following and breakout "
                f"strategies are suitable; sizing multiplier is {size_mult}x."
            )
        elif primary_regime is MarketState.BREAKOUT:
            suitable = ["Breakout_ATR_Channel", "Dynamic_ATR_Scalper"]
            unsuitable = ["Tight_Mean_Reversion", "Grid_Scalper"]
            risk_level = "HIGH"
            size_mult = 0.70
            sl_mult = 1.40
            explanation = (
                f"Measured {primary_tf} indicators show breakout conditions, but direction was not "
                f"established. Position sizing is reduced to {size_mult}x until direction is measured."
            )
        elif primary_regime is MarketState.RANGING_QUIET:
            suitable = ["Bollinger_Mean_Reversion", "Grid_Scalper", "RSI_Exhaustion"]
            unsuitable = ["Breakout_Channel", "High_Leverage_Trend"]
            risk_level = "LOW"
            size_mult = 1.00
            sl_mult = 0.80
            explanation = (
                f"Measured {primary_tf} indicators show a **RANGING_QUIET** regime "
                f"(BBW={tf_results[primary_tf].bbw_pct}%). Mean-reversion and scalping strategies are suitable."
            )
        elif primary_regime is MarketState.RANGING_VOLATILE:
            suitable = ["Volatility_Breakout", "Dynamic_ATR_Scalper"]
            unsuitable = ["High_Beta_Momentum", "Loose_Stop_Swing"]
            risk_level = "HIGH"
            size_mult = 0.70
            sl_mult = 1.40
            explanation = (
                f"Measured {primary_tf} indicators show choppy **RANGING_VOLATILE** conditions. "
                f"Position sizing is reduced to {size_mult}x to mitigate tail risk."
            )
        else:
            suitable = ["Multi_Factor_Trend", "Conservative_EMA"]
            unsuitable = ["Aggressive_Breakout"]
            risk_level = "MODERATE"
            size_mult = 1.00
            sl_mult = 1.00
            explanation = (
                f"Market is in a measured **{primary_regime.value}** state at {primary_tf}; "
                "baseline allocations apply."
            )

        return RegimeRecommendation(
            primary_regime=primary_regime,
            timeframe_consensus=consensus_str,
            suitable_strategies=suitable,
            unsuitable_strategies=unsuitable,
            risk_level=risk_level,
            position_sizing_multiplier=size_mult,
            stop_loss_adjustment_factor=sl_mult,
            explanation=explanation,
            timeframes=tf_results,
        )
