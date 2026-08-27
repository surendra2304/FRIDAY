# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for FRIDAY Advanced Voice Operations & NLP Command Center."""

from datetime import datetime, timezone, timedelta
import pytest

from friday.ecosystem.context_memory import ContextualConversationMemory
from friday.ecosystem.intent_router import ActionIntent, IntentRouter
from friday.ecosystem.multi_turn_dialog import MultiTurnDialogManager
from friday.ecosystem.suggestions import EcosystemSuggestionsEngine


@pytest.fixture
def voice_setup():
    router = IntentRouter()
    memory = ContextualConversationMemory(ttl_hours=24.0)
    suggestions = EcosystemSuggestionsEngine()
    dialog = MultiTurnDialogManager()
    return router, memory, suggestions, dialog


# =========================================================================
# 1. Intent Router Compound Decomposition & Entity Extraction Tests
# =========================================================================

def test_intent_router_compound_decomposition_and_entities(voice_setup):
    """Verify compound commands are parsed into discrete sub-intents with entity extraction."""
    router, memory, suggestions, dialog = voice_setup

    # 1. Compound Command: Build dashboard + Check positions
    cmd1 = "Build me a trading dashboard and check my positions"
    parsed1 = router.parse_command(cmd1)
    assert parsed1.is_compound is True
    assert len(parsed1.sub_intents) == 2
    assert parsed1.sub_intents[0].intent == ActionIntent.FORGE_BUILD
    assert parsed1.sub_intents[0].target_subsystem == "forge"
    assert parsed1.sub_intents[1].intent == ActionIntent.TRADING_POSITIONS
    assert parsed1.sub_intents[1].target_subsystem == "trading_bot"
    assert "dashboard" in parsed1.global_entities.project_types
    assert "positions" in parsed1.global_entities.trading_terms

    # 2. Compound Command: Website status + Trades status
    cmd2 = "How are my website and trades doing?"
    parsed2 = router.parse_command(cmd2)
    assert parsed2.is_compound is True
    assert any(s.target_subsystem == "nexus" for s in parsed2.sub_intents)
    assert any(s.target_subsystem == "trading_bot" for s in parsed2.sub_intents)

    # 3. Entity Extraction across all domains
    sample_text = "Show my leads and profit on the website today from yesterday"
    entities = router.extract_entities(sample_text)
    assert "leads" in entities.website_terms
    assert "pnl" in entities.trading_terms
    assert "website" in entities.project_types
    assert "today" in entities.time_references
    assert "yesterday" in entities.time_references


# =========================================================================
# 2. Contextual Memory Pronoun & Temporal Follow-Up Tests
# =========================================================================

def test_contextual_memory_pronoun_and_temporal_resolution(voice_setup):
    """Verify 24h context, pronoun resolution, and temporal follow-ups."""
    router, memory, suggestions, dialog = voice_setup

    # 1. Pronoun Resolution
    memory.record_mention("strategy", "Supertrend BTCUSDT", {"timeframe": "1h"})
    resolved = memory.resolve_pronoun_reference("How is it doing?")
    assert resolved is not None
    assert resolved["resolved"] is True
    assert resolved["entity_type"] == "strategy"
    assert resolved["value"] == "Supertrend BTCUSDT"

    # 2. Temporal Follow-Up Resolution
    memory.record_query("How did the website do today?", target_subsystem="nexus", time_window="today")
    follow_up = memory.resolve_temporal_follow_up("What about yesterday?")
    assert follow_up is not None
    assert follow_up["resolved"] is True
    assert follow_up["target_subsystem"] == "nexus"
    assert follow_up["new_time_window"] == "yesterday"


# =========================================================================
# 3. Proactive Suggestion Engine Multi-Domain Tests
# =========================================================================

def test_proactive_suggestion_engine_triggers(voice_setup):
    """Verify triggers for trading underperformance, Nexus leads, Forge history, and Monday time."""
    router, memory, suggestions, dialog = voice_setup

    # 1. Trading Underperformance
    trade_data = {
        "strategies": {
            "Supertrend": {"profit_factor": 0.72, "pnl_usdt": -210.0}
        }
    }
    sug_trade = suggestions.generate_suggestions(trading_data=trade_data)
    assert any("Supertrend underperforming" in s.prompt for s in sug_trade)

    # 2. Nexus High-Intent Lead
    nexus_data = {
        "leads": [{"lead_id": "lead_101", "score": 94, "company_domain": "acme-corp.com"}]
    }
    sug_nexus = suggestions.generate_suggestions(nexus_data=nexus_data)
    assert any("High-intent lead detected from acme-corp.com" in s.prompt for s in sug_nexus)

    # 3. FORGE Multiple Dashboards
    forge_history = [
        {"goal": "Build risk dashboard", "type": "DASHBOARD"},
        {"goal": "Build crypto portfolio dashboard", "type": "DASHBOARD"},
        {"goal": "Build analytics dashboard", "type": "DASHBOARD"},
    ]
    sug_forge = suggestions.generate_suggestions(forge_history=forge_history)
    assert any("You've built 3 dashboards" in s.prompt for s in sug_forge)

    # 4. Monday Morning Temporal Trigger
    monday_morning = datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc)  # Monday 09:00
    sug_time = suggestions.generate_suggestions(current_time=monday_morning)
    assert any("Monday morning, want the weekly ecosystem report?" in s.prompt for s in sug_time)


# =========================================================================
# 4. Multi-Turn Dialog, Biometric Security & Caching Tests
# =========================================================================

def test_multi_turn_dialog_and_biometrics(voice_setup):
    """Verify ambiguity clarification, biometric confirmation, and 30s TTL cache."""
    router, memory, suggestions, dialog = voice_setup

    # 1. Ambiguity Clarification
    res_amb = dialog.evaluate_ambiguity("Build me a tool")
    assert res_amb is not None
    assert res_amb.needs_clarification is True
    assert "CLI, API, or script" in res_amb.prompt
    assert len(res_amb.options) == 3

    # 2. Biometric Confirmation Flow (Unconfirmed vs Confirmed)
    bio_pending = dialog.request_biometric_confirmation("emergency_trading_halt")
    assert bio_pending.is_confirmed is False
    assert bio_pending.status == "AWAITING_CONFIRMATION"

    bio_auth = dialog.request_biometric_confirmation("emergency_trading_halt", spoken_phrase="Confirmed, authorization alpha-niner")
    assert bio_auth.is_confirmed is True
    assert bio_auth.status == "AUTHORIZED"

    # 3. Subsystem Offline Recovery
    rec = dialog.handle_subsystem_unavailable("trading_bot", "get_positions")
    assert rec.needs_clarification is True
    assert "Trading Bot is currently unreachable" in rec.prompt
    assert "Retry command" in rec.options

    # 4. 30-Second TTL Cache
    dialog.cache_response("query_status", {"status": "HEALTHY"})
    cached = dialog.get_cached_response("query_status")
    assert cached is not None
    assert cached["status"] == "HEALTHY"
