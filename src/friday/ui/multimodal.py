"""Multi-Modal User Interface for FRIDAY Ecosystem.

Supports simultaneous interaction across Voice, Text Chat, Visual Dashboard,
Email Summaries, Responsive Mobile Dashboard Views, and Voice-to-Text command previews.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("ui.multimodal")


class InteractionChannel(str, Enum):
    """Interaction channels supported by FRIDAY."""
    VOICE = "VOICE"
    TEXT_CHAT = "TEXT_CHAT"
    VISUAL_DASHBOARD = "VISUAL_DASHBOARD"
    EMAIL_SUMMARY = "EMAIL_SUMMARY"
    MOBILE_VIEW = "MOBILE_VIEW"


@dataclass
class CommandPreview:
    """Pre-execution preview of a transcribed voice command."""
    raw_audio_transcript: str
    interpreted_intent: str
    target_subsystem: str
    is_sensitive: bool
    requires_confirmation: bool
    preview_text: str


class MultiModalInterface:
    """Delivers adaptive data formatting across all user interaction channels."""

    def __init__(self) -> None:
        pass

    def preview_voice_command(
        self,
        transcript: str,
        interpreted_intent: str,
        target_subsystem: str,
        is_sensitive: bool = False,
    ) -> CommandPreview:
        """Generates a command preview before execution."""
        req_confirm = is_sensitive or any(k in transcript.lower() for k in ["build", "cancel", "stop", "panic", "close"])
        preview_text = (
            f"🎙️ [Voice Preview] Command: \"{transcript}\"\n"
            f"• Target: {target_subsystem.upper()}\n"
            f"• Intent: {interpreted_intent}\n"
            f"• Requires Confirmation: {'YES (SENSITIVE)' if req_confirm else 'NO (SAFE)'}"
        )
        return CommandPreview(
            raw_audio_transcript=transcript,
            interpreted_intent=interpreted_intent,
            target_subsystem=target_subsystem,
            is_sensitive=is_sensitive,
            requires_confirmation=req_confirm,
            preview_text=preview_text,
        )

    def render_mobile_dashboard_html(self, telemetry: dict[str, Any]) -> str:
        """Renders mobile-optimized, responsive HTML dashboard view."""
        from friday.core.readings import UNKNOWN_LABEL, read_number, read_text

        bot = telemetry.get("trading_bot", {})
        forge = telemetry.get("forge", {})
        ai = telemetry.get("ai_universe", {})

        # The mobile view carried a hardcoded "ONLINE" badge and invented
        # telemetry: $10,450 equity, a +$420.50 day, 3 positions, 2 delivered
        # builds at 96.0% coverage, 7 providers at 84% confidence with 128
        # consultations. On a phone, nobody can check any of it.
        equity = read_number(bot, "equity_usdt", source="trading bot")
        pnl = read_number(bot, "daily_pnl_usdt", source="trading bot")
        bot_positions = read_number(bot, "active_positions_count", source="trading bot")
        builds = read_number(forge, "total_completed", source="forge")
        coverage = read_number(forge, "mean_test_coverage_pct", source="forge")
        providers = read_number(ai, "configured_providers_count", source="ai universe")
        confidence = read_number(ai, "model_confidence_pct", source="ai universe")
        consultations = read_number(ai, "consultations_today", source="ai universe")
        any_reading = any(
            r.known for r in (equity, pnl, bot_positions, builds, coverage, providers, confidence, consultations)
        )
        badge = "REPORTED" if any_reading else UNKNOWN_LABEL
        badge_colour = "var(--green)" if any_reading else "#8b949e"

        def money(reading) -> str:
            return UNKNOWN_LABEL if not reading.known else f"${reading.value:,.2f}"

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>FRIDAY Mobile Command</title>
  <style>
    :root {{ --bg: #0d1117; --card-bg: #161b22; --accent: #58a6ff; --text: #c9d1d9; --green: #3fb950; --red: #f85149; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 12px; }}
    .header {{ display: flex; justify-content: space-between; align-items: center; padding-bottom: 12px; border-bottom: 1px solid #30363d; }}
    .badge {{ background: {badge_colour}; color: #000; padding: 4px 8px; border-radius: 12px; font-size: 11px; font-weight: bold; }}
    .card {{ background: var(--card-bg); border-radius: 8px; padding: 14px; margin-top: 12px; border: 1px solid #30363d; }}
    .card h3 {{ margin: 0 0 8px 0; font-size: 16px; display: flex; align-items: center; gap: 6px; }}
    .metric {{ font-size: 22px; font-weight: bold; color: #fff; margin: 4px 0; }}
    .subtext {{ font-size: 12px; color: #8b949e; }}
    .action-btn {{ width: 100%; padding: 10px; margin-top: 10px; border-radius: 6px; border: none; font-weight: bold; cursor: pointer; }}
    .btn-panic {{ background: var(--red); color: white; }}
    .btn-build {{ background: var(--accent); color: white; }}
  </style>
</head>
<body>
  <div class="header">
    <h2>FRIDAY OS</h2>
    <span class="badge">{badge}</span>
  </div>
  <div class="card">
    <h3>📈 Trading Bot</h3>
    <div class="metric">{money(equity)} USDT</div>
    <div class="subtext">Daily P&L: {money(pnl)} | {bot_positions.number(0)} Positions</div>
    <button class="action-btn btn-panic">Emergency Stop Trading</button>
  </div>
  <div class="card">
    <h3>🛠️ FORGE SWE Engine</h3>
    <div class="metric">{read_text(forge, 'status')}</div>
    <div class="subtext">Delivered: {builds.number(0)} builds | Coverage: {coverage.percent()}</div>
    <button class="action-btn btn-build">Submit New Build</button>
  </div>
  <div class="card">
    <h3>🧠 AI-Universe</h3>
    <div class="metric">{providers.number(0)} Providers</div>
    <div class="subtext">Confidence: {confidence.percent(0)} | {consultations.number(0)} consultations</div>
  </div>
</body>
</html>"""
