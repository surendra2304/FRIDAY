# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for FRIDAY Strategy Evolution Oversight & Approval Workflow."""

import pytest

from friday.alert_manager import ProductionAlertManager
from friday.memory.in_memory import InMemoryConversationMemory
from friday.operators.evolution_oversight import EvolutionOversightOperator
from friday.security.production_security import ProductionSecurityManager
from friday.skills.evolution_approval import EvolutionApprovalSkill
from friday.skills.registry import SkillRegistry
from friday.trading.evolution_history import EvolutionHistoryTracker
from friday.trading.strategy_portfolio import StrategyLifecycleState, StrategyPortfolioManager


@pytest.fixture
def evolution_setup():
    memory = InMemoryConversationMemory()
    alert_mgr = ProductionAlertManager(memory=memory)
    portfolio_mgr = StrategyPortfolioManager()
    history_tracker = EvolutionHistoryTracker()
    sec_mgr = ProductionSecurityManager()

    operator = EvolutionOversightOperator(
        portfolio_manager=portfolio_mgr,
        alert_manager=alert_mgr,
        memory=memory,
    )

    skill = EvolutionApprovalSkill(
        portfolio_manager=portfolio_mgr,
        history_tracker=history_tracker,
        security_manager=sec_mgr,
    )

    return skill, portfolio_mgr, history_tracker, operator, sec_mgr, alert_mgr


# =========================================================================
# 1. Strategy Portfolio Manager Tests
# =========================================================================

def test_strategy_portfolio_manager_lifecycle(evolution_setup):
    """Verify strategy portfolio tracks lifecycle states, rankings, and spoken summaries."""
    skill, portfolio_mgr, history_tracker, operator, sec_mgr, alert_mgr = evolution_setup

    overview = portfolio_mgr.get_portfolio_overview()
    assert overview["live_count"] == 3
    assert overview["incubation_count"] == 1
    assert overview["candidate_count"] == 1

    top_live = overview["live_strategies_ranked"][0]
    assert top_live["name"] == "BTC_Supertrend_Momentum"
    assert top_live["sharpe_2y"] >= 2.0

    # Get candidate
    cand = portfolio_mgr.get_candidate("Order_Flow_Imbalance")
    assert cand is not None
    assert cand.passed_gates_count == 6
    assert cand.lifecycle_state == StrategyLifecycleState.READY_FOR_REVIEW

    # Spoken summary
    spoken = portfolio_mgr.get_spoken_portfolio_summary()
    assert "Strategy portfolio overview:" in spoken
    assert "BTC_Supertrend_Momentum" in spoken


# =========================================================================
# 2. Evolution History & Learning Tests
# =========================================================================

def test_evolution_history_and_failure_learning(evolution_setup):
    """Verify failure pattern analysis and institutional learning summaries."""
    skill, portfolio_mgr, history_tracker, operator, sec_mgr, alert_mgr = evolution_setup

    patterns = history_tracker.get_failure_pattern_analysis()
    assert patterns["total_retired"] == 5
    assert "REGIME_SHIFT" in patterns["category_counts"]
    assert patterns["category_percentages"]["REGIME_SHIFT"] == 60.0

    # Spoken learning
    spoken = history_tracker.get_spoken_learning_summary()
    assert "Here is what we have learned from our 5 retired strategies:" in spoken
    assert "60% of retired strategies were pure trend-followers" in spoken


# =========================================================================
# 3. Evolution Oversight Operator Tests
# =========================================================================

def test_evolution_oversight_operator_alerts(evolution_setup):
    """Verify operator alerts on candidate ready for approval and probation entries."""
    skill, portfolio_mgr, history_tracker, operator, sec_mgr, alert_mgr = evolution_setup

    events = operator.tick()
    assert isinstance(events, list)
    assert any(e["type"] == "CANDIDATE_READY_FOR_APPROVAL" for e in events)

    # Simulate probation entry
    portfolio_mgr.update_lifecycle_state("ETH_Mean_Reversion", StrategyLifecycleState.PROBATION)
    prob_events = operator.tick()
    assert any(e["type"] == "STRATEGY_ENTERED_PROBATION" for e in prob_events)


# =========================================================================
# 4. Voice Evolution Approval Commands
# =========================================================================

def test_voice_evolution_review_and_approval_commands(evolution_setup):
    """Verify voice queries for candidate logic, risks, AI debate, backtest, and approval."""
    skill, portfolio_mgr, history_tracker, operator, sec_mgr, alert_mgr = evolution_setup

    # 1. "Tell me about the strategy"
    res1 = skill.execute("Tell me about the strategy")
    assert res1.success is True
    assert "Candidate Strategy: Order_Flow_Imbalance" in res1.output

    # 2. "What are the risks?"
    res2 = skill.execute("What are the risks?")
    assert res2.success is True
    assert "Risk analysis for Order_Flow_Imbalance" in res2.output

    # 3. "What did AI-Universe say?"
    res3 = skill.execute("What did AI-Universe say?")
    assert res3.success is True
    assert "AI-Universe multi-agent evaluation" in res3.output

    # 4. "Show the backtest"
    res4 = skill.execute("Show the backtest")
    assert res4.success is True
    assert "Profit factor is 1.68" in res4.output

    # 5. "Give me a strategy portfolio overview"
    res5 = skill.execute("Give me a strategy portfolio overview")
    assert res5.success is True
    assert "Strategy portfolio overview:" in res5.output

    # 6. "What have we learned from retired strategies?"
    res6 = skill.execute("What have we learned from retired strategies?")
    assert res6.success is True
    assert "Here is what we have learned" in res6.output

    # 7. "Approve for incubation"
    profile = sec_mgr._enrolled_voices["operator_surendra"]
    valid_embedding = list(profile.embedding)

    res_approve = skill.execute(
        "Approve for incubation",
        speaker_id="operator_surendra",
        voice_embedding=valid_embedding,
    )
    assert res_approve.success is True
    assert "APPROVED for incubation" in res_approve.output
    assert "Cryptographic Decision Signature:" in res_approve.output

    # Verify state updated
    cand = portfolio_mgr.get_candidate("Order_Flow_Imbalance")
    assert cand.lifecycle_state == StrategyLifecycleState.INCUBATION


def test_voice_evolution_approval_registered_in_registry():
    """Verify EvolutionApprovalSkill is registered in SkillRegistry."""
    reg = SkillRegistry()
    reg.load_builtins()

    skill = reg.get("evolution_approval")
    assert skill is not None
    assert "trading_bot_control" in skill.required_capabilities
