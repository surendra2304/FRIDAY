"""Comprehensive Test Suite for FRIDAY Final Ecosystem Optimization & User Experience."""

from datetime import datetime, timezone

from friday.core.user_preferences import UserPreferenceManager
from friday.ecosystem.context_memory import ContextualConversationMemory
from friday.ecosystem.nl_router import NLCommandRouter, NLIntent
from friday.ecosystem.suggestions import EcosystemSuggestionsEngine
from friday.optimization.ecosystem_perf import EcosystemPerformanceOptimizer
from friday.ui.multimodal import MultiModalInterface

# =========================================================================
# 1. Natural Language Command Router Tests
# =========================================================================

def test_nl_command_router_entities_and_intents():
    """Verify entity extraction, intent classification, and multi-intent decomposition."""
    router = NLCommandRouter()

    # Entity extraction
    entities = router.extract_entities("Build a responsive portfolio website with BTC analytics today")
    assert entities.project_type == "website"
    assert entities.target_asset == "BTC"
    assert entities.time_reference == "today"

    # Single intents
    cmd_build = router.parse_command("Forge, build a CLI tool for file encryption")
    assert cmd_build.primary_intent == NLIntent.BUILD_TASK
    assert "forge" in cmd_build.target_subsystems

    cmd_trade = router.parse_command("How are my open positions and daily P&L doing?")
    assert cmd_trade.primary_intent == NLIntent.TRADING_QUERY
    assert "trading_bot" in cmd_trade.target_subsystems

    cmd_intel = router.parse_command("What does AI Universe predict for ETH?")
    assert cmd_intel.primary_intent == NLIntent.INTELLIGENCE_ANALYSIS
    assert "ai_universe" in cmd_intel.target_subsystems

    cmd_status = router.parse_command("Status of everything")
    assert cmd_status.primary_intent == NLIntent.STATUS_QUERY

    cmd_panic = router.parse_command("Emergency stop trading now!")
    assert cmd_panic.primary_intent == NLIntent.EMERGENCY_ACTION

    # Multi-intent decomposition
    cmd_multi = router.parse_command("Build me a trading dashboard and show my current positions")
    assert cmd_multi.primary_intent == NLIntent.MULTI_INTENT
    assert "forge" in cmd_multi.target_subsystems
    assert "trading_bot" in cmd_multi.target_subsystems
    assert len(cmd_multi.sub_commands) >= 2


# =========================================================================
# 2. Contextual Conversation Memory Tests
# =========================================================================

def test_contextual_conversation_memory():
    """Verify context recording, pronoun resolution, and expiration."""
    memory = ContextualConversationMemory(ttl_hours=24.0)

    # Record mentions
    memory.record_mention("project", "Portfolio Website v2", {"task_id": "forge_task_01"})
    memory.record_mention("strategy", "Supertrend 15m", {"profit_factor": 1.6})

    # Latest mention
    latest = memory.get_latest_mention()
    assert latest.entity_type == "strategy"
    assert latest.value == "Supertrend 15m"

    # Pronoun resolution
    resolved = memory.resolve_pronoun_reference("How is it doing?")
    assert resolved is not None
    assert resolved["entity_type"] == "strategy"

    resolved_build = memory.resolve_pronoun_reference("How is the build going?")
    assert resolved_build is not None
    assert resolved_build["entity_type"] == "project"
    assert resolved_build["value"] == "Portfolio Website v2"


# =========================================================================
# 3. Intelligent Suggestions Engine Tests
# =========================================================================

def test_intelligent_suggestions_engine():
    """Verify suggestions based on trading P&L, build patterns, and time schedules."""
    engine = EcosystemSuggestionsEngine()

    # Trading trigger: underperforming strategy
    trading_data = {
        "strategies": {"Supertrend": {"profit_factor": 0.8, "pnl_usdt": -250.0}},
        "aggregate_leverage": 3.0,
        "daily_loss_pct": 4.5,
    }
    sugs_trade = engine.generate_suggestions(trading_data=trading_data)
    assert len(sugs_trade) >= 2
    assert any("Supertrend" in s.prompt for s in sugs_trade)
    assert any("risk is elevated" in s.prompt for s in sugs_trade)

    # FORGE trigger: repetitive website builds
    forge_history = [
        {"goal": "Build website 1", "type": "WEBSITE"},
        {"goal": "Build website 2", "type": "WEBSITE"},
        {"goal": "Build website 3", "type": "WEBSITE"},
    ]
    sugs_forge = engine.generate_suggestions(forge_history=forge_history)
    assert len(sugs_forge) >= 1
    assert "website template" in sugs_forge[0].prompt

    # Temporal trigger: Monday morning
    monday_morning = datetime(2026, 8, 31, 9, 0, 0, tzinfo=timezone.utc)
    sugs_time = engine.generate_suggestions(current_time=monday_morning)
    assert len(sugs_time) >= 1
    assert "Monday morning" in sugs_time[0].prompt


# =========================================================================
# 4. Multi-Modal Interface Tests
# =========================================================================

def test_multimodal_interface():
    """Verify voice-to-text previews and mobile HTML rendering."""
    ui = MultiModalInterface()

    # Voice command preview
    preview = ui.preview_voice_command(
        transcript="Forge, build me a portfolio website",
        interpreted_intent="BUILD_TASK",
        target_subsystem="forge",
        is_sensitive=True,
    )
    assert preview.requires_confirmation is True
    assert "Voice Preview" in preview.preview_text

    # Mobile HTML view
    html = ui.render_mobile_dashboard_html({
        "trading_bot": {"equity_usdt": 10450.0, "daily_pnl_usdt": 420.5, "active_positions_count": 3},
        "forge": {"status": "IDLE", "total_completed": 2, "mean_test_coverage_pct": 96.0},
        "ai_universe": {"configured_providers_count": 7, "model_confidence_pct": 84.0, "consultations_today": 128},
    })
    assert "<!DOCTYPE html>" in html
    assert "FRIDAY Mobile Command" in html
    assert "$10,450.00 USDT" in html


# =========================================================================
# 5. Performance Optimization Tests
# =========================================================================

def test_performance_optimization_and_caching():
    """Verify TTL caching, parallel health checks, and SLA benchmarking."""
    perf = EcosystemPerformanceOptimizer(default_cache_ttl_sec=2, max_workers=3)

    # Caching
    call_count = 0
    def compute():
        nonlocal call_count
        call_count += 1
        return {"data": 42}

    r1 = perf.get_cached_or_compute("test_key", compute)
    r2 = perf.get_cached_or_compute("test_key", compute)
    assert r1 == r2 == {"data": 42}
    assert call_count == 1  # Served from cache

    # Parallel health checks
    callables = {
        "bot": lambda: {"status": "HEALTHY"},
        "forge": lambda: {"status": "HEALTHY"},
        "ai": lambda: {"status": "HEALTHY"},
    }
    p_results = perf.parallel_health_check(callables, timeout_sec=2.0)
    assert len(p_results) == 3
    assert p_results["bot"]["status"] == "HEALTHY"

    # SLA verification
    assert perf.verify_sla("simple_query", 0.5) is True
    assert perf.verify_sla("emergency", 0.2) is True


# =========================================================================
# 6. User Preferences & Safety Invariant Tests
# =========================================================================

def test_user_preferences_and_safety_invariants():
    """Verify preference management and strict safety limits (cannot exceed 5.0% drawdown limit)."""
    mgr = UserPreferenceManager()

    # Voice update
    mgr.update_voice_preferences(speech_rate=1.2, volume=0.9)
    assert mgr.voice.speech_rate == 1.2

    # Trading update within safety
    mgr.update_trading_preferences(risk_tolerance="CONSERVATIVE", max_daily_drawdown_limit_pct=3.0)
    assert mgr.trading.max_daily_drawdown_limit_pct == 3.0

    # Attempt to bypass safety gate
    mgr.update_trading_preferences(max_daily_drawdown_limit_pct=15.0)
    assert mgr.trading.max_daily_drawdown_limit_pct == 5.0  # Clamped to 5.0%

    # Pattern learning
    for _ in range(12):
        mgr.record_interaction_and_learn("status", {"source": "voice"})
    assert mgr.reports.detail_level == "brief"
