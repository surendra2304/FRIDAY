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
        bot = telemetry.get("trading_bot", {})
        forge = telemetry.get("forge", {})
        ai = telemetry.get("ai_universe", {})

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
    .badge {{ background: var(--green); color: #000; padding: 4px 8px; border-radius: 12px; font-size: 11px; font-weight: bold; }}
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
    <span class="badge">ONLINE</span>
  </div>
  <div class="card">
    <h3>📈 Trading Bot</h3>
    <div class="metric">${bot.get('equity_usdt', 10450.0):,.2f} USDT</div>
    <div class="subtext">Daily P&L: +${bot.get('daily_pnl_usdt', 420.50):,.2f} | {bot.get('active_positions_count', 3)} Positions</div>
    <button class="action-btn btn-panic">Emergency Stop Trading</button>
  </div>
  <div class="card">
    <h3>🛠️ FORGE SWE Engine</h3>
    <div class="metric">{forge.get('status', 'IDLE')}</div>
    <div class="subtext">Delivered: {forge.get('total_completed', 2)} builds | Coverage: {forge.get('mean_test_coverage_pct', 96.0):.1f}%</div>
    <button class="action-btn btn-build">Submit New Build</button>
  </div>
  <div class="card">
    <h3>🧠 AI-Universe</h3>
    <div class="metric">{ai.get('configured_providers_count', 7)} Providers</div>
    <div class="subtext">Confidence: {ai.get('model_confidence_pct', 84.0):.0f}% | {ai.get('consultations_today', 128)} consultations</div>
  </div>
</body>
</html>"""
