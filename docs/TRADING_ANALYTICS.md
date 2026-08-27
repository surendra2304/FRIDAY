# 📈 Advanced Trading Analytics & Portfolio Management Guide

This document provides a comprehensive reference for FRIDAY's quantitative portfolio analytics, multi-timeframe market regime detection, time-series performance prediction, Monte Carlo risk management, and multi-strategy coordination engines.

---

## 🏛️ Quantitative Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                 Market Data & Telemetry Feeds               │
│         (Binance Futures Testnet / Paper / Live APIs)       │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 FRIDAY Quantitative Engine                  │
├──────────────────────────────┬──────────────────────────────┤
│  PortfolioAnalyticsEngine    │  MarketRegimeDetector        │
│  • Multi-Account Tracking    │  • Multi-Timeframe (1m-1d)   │
│  • Sharpe / Sortino / Calmar │  • ADX / BBW / ATR / Volume  │
│  • VaR (95%/99%) & CVaR      │  • Regime Sizing Multipliers │
├──────────────────────────────┼──────────────────────────────┤
│  PerformancePredictionEngine │  RiskManagementDashboard     │
│  • Forward Alpha Forecasts   │  • Monte Carlo (10,000 Paths)│
│  • GARCH Volatility Modeling │  • HHI Concentration Risk    │
│  • 80% & 95% Confidence Bands│  • Historical Crisis Testing │
├──────────────────────────────┴──────────────────────────────┤
│  MultiStrategyCoordinator                                   │
│  • Dynamic Strategy Allocation & Rotation                   │
│  • Directional Conflict Resolution (Consensus & Macro Trend)│
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│            VoiceTradingSkill & External Analytics           │
│   • Spoken Queries & Natural Language Ops Commands          │
│   • TradingView Lightweight Charts & Webhook Formatting     │
└─────────────────────────────────────────────────────────────┘
```

---

## 📐 Mathematical Formulas & Methodologies

### 1. Risk-Adjusted Return Ratios
- **Sharpe Ratio**:
  $$\text{Sharpe} = \frac{R_p - R_f}{\sigma_p} \times \sqrt{365}$$
- **Sortino Ratio**:
  $$\text{Sortino} = \frac{R_p - R_f}{\sigma_{\text{downside}}} \times \sqrt{365}, \quad \text{where } \sigma_{\text{downside}} = \sqrt{\frac{1}{N}\sum \min(0, R_i - R_f)^2}$$
- **Calmar Ratio**:
  $$\text{Calmar} = \frac{\text{Annualized Return}}{\text{Maximum Drawdown}}$$

### 2. Value at Risk (VaR) & Expected Shortfall (CVaR)
- **1-Day 95% Parametric / Historical VaR**:
  $$\text{VaR}_{0.95} = \text{Portfolio Equity} \times |R_{0.05}|$$
- **1-Day 95% Conditional VaR (Expected Shortfall)**:
  $$\text{CVaR}_{0.95} = \mathbb{E}\left[L \mid L > \text{VaR}_{0.95}\right]$$

### 3. Concentration Risk (Herfindahl-Hirschman Index - HHI)
$$\text{HHI} = \sum_{i=1}^N \left(\frac{\text{Exposure}_i}{\text{Total Exposure}}\right)^2$$
- $\text{HHI} < 0.35$: **Diversified**
- $0.35 \le \text{HHI} \le 0.65$: **Moderate Concentration**
- $\text{HHI} > 0.65$: **Highly Concentrated**

### 4. Multi-Timeframe Market Regime Classification
- **ADX $\ge 25$ & BBW $\ge 3.0\%$**: `TRENDING_BULL_STRONG` or `BREAKOUT` (Position sizing multiplier: $1.25\times$)
- **ADX $< 20$ & BBW $< 2.0\%$**: `RANGING_QUIET` (Position sizing multiplier: $1.0\times$, tighten stop-loss by $0.80\times$)
- **ADX $< 20$ & BBW $\ge 4.0\%$**: `RANGING_VOLATILE` (Position sizing multiplier: $0.70\times$)

---

## 🎙️ Voice & Text Command Reference

| Natural Language Command | Triggered Engine | Spoken / Rendered Output |
| :--- | :--- | :--- |
| `"How is my portfolio performing?"` | `PortfolioAnalyticsEngine` | Total equity, leverage, annualized Sharpe ratio ($2.10$), Sortino ($2.85$), and max drawdown ($3.25\%$). |
| `"What's my current risk exposure?"` | `RiskManagementDashboard` | Full Markdown risk dashboard with 95% VaR, CVaR, HHI concentration rating, and Monte Carlo stress tests. |
| `"How is the BTC_Trend strategy doing?"` | `PortfolioAnalyticsEngine` | Individual strategy total return, Sharpe ratio, and capital weight attribution. |
| `"What's the current market regime?"` | `MarketRegimeDetector` | Primary regime (`TRENDING_BULL_STRONG`), timeframe consensus, and recommended strategy candidates. |
| `"How do you expect the ML strategy to perform?"` | `PerformancePredictionEngine` | 7-day expected return, 95% confidence interval, forecasted volatility, and probability of positive alpha. |
| `"Should I rebalance my portfolio?"` | `MultiStrategyCoordinator` | Regime-optimized capital allocation targets across all active strategies. |

---

## 💻 Python Code Usage Examples

```python
from friday.trading import (
    PortfolioAnalyticsEngine,
    MarketRegimeDetector,
    PerformancePredictionEngine,
    RiskManagementDashboard,
    MultiStrategyCoordinator,
)

# 1. Calculate Portfolio Metrics
engine = PortfolioAnalyticsEngine()
metrics = engine.calculate_metrics()
print(f"Sharpe Ratio: {metrics.sharpe_ratio:.2f}, 95% VaR: ${metrics.var_95_daily:,.2f}")

# 2. Detect Market Regime
detector = MarketRegimeDetector()
regime = detector.detect_regime(symbol="BTCUSDT")
print(f"Regime: {regime.primary_regime.value}, Sizing Multiplier: {regime.position_sizing_multiplier}x")

# 3. Forecast Strategy Performance
predictor = PerformancePredictionEngine()
forecast = predictor.forecast_strategy("BTC_Supertrend_Momentum")
print(f"7-Day Expected Return: {forecast.horizons['7d'].expected_return_pct:+.2f}%")

# 4. Stress Testing
dashboard = RiskManagementDashboard()
profile = dashboard.evaluate_risk(equity=10540.25)
print(f"Concentration HHI: {profile.concentration_hhi:.2f}, Crisis Status: {profile.stress_tests[0].survival_status}")
```
