# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for FRIDAY Advanced Memory Consolidation & Learning System."""

from datetime import datetime, timezone, timedelta
import os
import shutil
import tempfile
import pytest

from friday.core.backup_recovery import BackupRecoveryManager
from friday.memory.consolidation import MemoryConsolidationEngine, SemanticMemory
from friday.memory.cross_session import CrossSessionLearning
from friday.memory.proactive import ProactiveMemory
from friday.operators.memory_health_operator import MemoryHealthMonitor


@pytest.fixture
def memory_setup():
    temp_cold_dir = tempfile.mkdtemp()
    temp_backup_dir = tempfile.mkdtemp()
    consolidation = MemoryConsolidationEngine(cold_storage_dir=temp_cold_dir)
    cross_session = CrossSessionLearning()
    proactive = ProactiveMemory()
    backup_mgr = BackupRecoveryManager(backup_dir=temp_backup_dir)
    health_op = MemoryHealthMonitor(consolidation_engine=consolidation, backup_mgr=backup_mgr)

    yield consolidation, cross_session, proactive, backup_mgr, health_op, temp_cold_dir, temp_backup_dir
    shutil.rmtree(temp_cold_dir, ignore_errors=True)
    shutil.rmtree(temp_backup_dir, ignore_errors=True)


# =========================================================================
# 1. Memory Consolidation & Decay Tests
# =========================================================================

def test_memory_consolidation_and_decay(memory_setup):
    """Verify episodic-to-semantic compression, importance scoring, decay, and cold storage."""
    consolidation, cross_session, proactive, backup_mgr, health_op, cold_dir, backup_dir = memory_setup

    # 1. Record 6 episodic trading events
    for i in range(6):
        consolidation.record_event(
            subsystem="trading_bot",
            action="query_status",
            details={"equity": 10450.0},
            emotional_weight=1.2,
        )

    # 2. Record 3 Nexus lead queries
    for i in range(3):
        consolidation.record_event(
            subsystem="nexus",
            action="query_leads",
            details={"lead_count": 14},
        )

    assert len(consolidation.episodic_memory) == 9

    # 3. Compress Episodic to Semantic
    semantics = consolidation.compress_episodic_to_semantic()
    assert len(semantics) >= 2
    assert "sem_active_trading_monitoring" in consolidation.semantic_memory
    assert "sem_growth_lead_tracking" in consolidation.semantic_memory
    assert len(consolidation.episodic_memory) == 0

    # 4. Verify Cold Storage File was Written
    cold_files = os.listdir(cold_dir)
    assert len(cold_files) >= 1

    # 5. Apply 30-Day Decay Test
    mem = consolidation.semantic_memory["sem_active_trading_monitoring"]
    initial_score = mem.importance_score
    mem.last_accessed = datetime.now(timezone.utc) - timedelta(days=35)

    decayed_count = consolidation.apply_memory_decay(decay_threshold_days=30.0)
    assert decayed_count == 1
    assert mem.importance_score == pytest.approx(initial_score * 0.5, rel=1e-2)

    # 6. Nightly Consolidation Orchestrator
    summary = consolidation.run_nightly_consolidation()
    assert summary["status"] == "CONSOLIDATION_COMPLETE"
    assert summary["cold_storage_preserved"] is True


# =========================================================================
# 2. Cross-Session Pattern Learning & Contradiction Detection Tests
# =========================================================================

def test_cross_session_learning_and_contradictions(memory_setup):
    """Verify recurring command shortcuts, preference adaptation, and contradiction alerts."""
    consolidation, cross_session, proactive, backup_mgr, health_op, cold_dir, backup_dir = memory_setup

    # 1. Record repeated sequence: Trading Status -> Forge Status
    for _ in range(3):
        cross_session.record_command("Trading status", "trading_bot")
        cross_session.record_command("Forge status", "forge")

    shortcuts = cross_session.detect_recurring_shortcuts()
    assert len(shortcuts) >= 1
    assert "seq_trading_forge_morning" in shortcuts[0].pattern_id
    assert "Offer combined Trading & Forge Morning Briefing" in shortcuts[0].suggested_shortcut

    # 2. User Preference Learning
    prefs = cross_session.learn_user_preferences(explicit_feedback="Please keep your answers brief and concise")
    assert prefs.response_length == "brief"

    prefs_batch = cross_session.learn_user_preferences(explicit_feedback="Please send batch digest alerts")
    assert prefs_batch.alert_timing == "batched"

    # 3. Contradiction Detection
    recent = ["show bitcoin positions", "what is bitcoin drawdown", "bitcoin pnl today"]
    alert = cross_session.detect_contradictions("stop alerting me about bitcoin", recent_commands=recent)
    assert alert is not None
    assert "frequently query it manually" in alert.explanation


# =========================================================================
# 3. Proactive Memory Commitments & Unfinished Tasks Tests
# =========================================================================

def test_proactive_memory_commitments_and_unfinished_tasks(memory_setup):
    """Verify future commitment tracking, proactive prompts, and interrupted task resumption."""
    consolidation, cross_session, proactive, backup_mgr, health_op, cold_dir, backup_dir = memory_setup

    # 1. Extract Commitment
    com = proactive.extract_commitment_from_text("I will review the trading strategy tomorrow")
    assert com is not None
    assert com.topic == "trading strategy"
    assert com.status == "PENDING"

    # 2. Check pending commitment on tomorrow's arrival
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1, hours=1)
    prompts = proactive.check_pending_commitments(current_time=tomorrow)
    assert len(prompts) >= 1
    assert "You mentioned reviewing the trading strategy" in prompts[0]

    # 3. Record & Check Unfinished Task
    proactive.record_unfinished_task(
        subsystem="forge",
        task_description="crypto analytics dashboard",
        interrupted_stage="requirement_gathering",
    )
    task_prompts = proactive.check_unfinished_tasks()
    assert len(task_prompts) >= 1
    assert "You started asking Forge to build 'crypto analytics dashboard'" in task_prompts[0]


# =========================================================================
# 4. Memory Health Operator & Auto-Compaction Tests
# =========================================================================

def test_memory_health_operator_and_compaction(memory_setup):
    """Verify 60s memory health audit, auto-compaction, and daily backup verification."""
    consolidation, cross_session, proactive, backup_mgr, health_op, cold_dir, backup_dir = memory_setup

    # Create backup snapshot so daily check passes
    backup_mgr.create_snapshot(snapshot_type="PERIODIC_6H")

    # Add episodic events to simulate fragmentation
    for i in range(12):
        consolidation.record_event("trading_bot", "check_pnl")

    # Tick operator (detects fragmentation > 30% and auto-compacts)
    events = health_op.tick()
    assert any(e["type"] == "MEMORY_AUTO_COMPACTION" for e in events)
    assert len(consolidation.episodic_memory) == 0

    # Diagnostic Report
    report = health_op.generate_health_report()
    assert report.status == "HEALTHY"
    assert report.daily_backup_verified is True
    assert report.last_consolidation_status == "SUCCESS"
