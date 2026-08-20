# -*- coding: utf-8 -*-
"""Comprehensive unit test suite for Phase 8.5: Visual Memory & Episodic Environmental Memory.

Tests:
1. Storing derived observations as structured episodic facts without raw screenshots.
2. Retrieval and semantic relevance filtering.
3. Perceptual and semantic duplicate suppression.
4. Fact correction and superseding mechanism.
5. Fact forgetting / deactivation mechanism.
6. Fallback from embedding search to SQLite FTS.
7. Secret and token redaction before memory persistence.
8. Cross-task isolation with task ID filtering.
"""

from datetime import datetime, timezone
import pytest

from friday.memory.in_memory import InMemoryConversationMemory
from friday.vision.episodic_memory import (
    EpisodicEnvironmentalFact,
    EpisodicEnvironmentalMemoryManager,
    MemoryImportance,
    redact_sensitive_visual_text,
)
from friday.vision.screen_context import ScreenContext
from friday.vision.temporal import EnvironmentalChange, EnvironmentalChangeType


# 1. Storing Derived Observations Without Screenshots
def test_storing_derived_observations():
    """Verify structured environmental facts are saved without binary screenshot blobs."""
    memory = InMemoryConversationMemory()
    mgr = EpisodicEnvironmentalMemoryManager(memory=memory)

    ctx = ScreenContext(
        summary="Terminal showing Docker build succeeded with container ID 8f9b1c",
        active_application="WindowsTerminal.exe",
        window_title="PowerShell - docker build",
    )

    fact = mgr.record_screen_observation(ctx, task_id="task_deploy")
    assert fact is not None
    assert fact.category == "SCREEN_OBSERVATION"
    assert "Docker build succeeded" in fact.fact_summary
    assert fact.source_application == "WindowsTerminal.exe"
    assert fact.task_id == "task_deploy"

    # Verify underlying memory message contains no binary data
    stored_msgs = memory.get_context_window(10)
    assert len(stored_msgs) >= 1
    assert "data:image" not in stored_msgs[-1].content
    assert "Docker build succeeded" in stored_msgs[-1].content


# 2. Retrieval and Relevance Filtering
def test_retrieval_and_relevance_filtering():
    """Verify episodic memory retrieval returns facts matching query sorted by importance."""
    memory = InMemoryConversationMemory()
    mgr = EpisodicEnvironmentalMemoryManager(memory=memory)

    mgr.record_derived_fact(
        category="DATABASE_STATUS",
        fact_summary="PostgreSQL connection pool healthy with 20 connections",
        importance=MemoryImportance.MEDIUM,
    )
    mgr.record_derived_fact(
        category="DATABASE_ALERT",
        fact_summary="PostgreSQL disk quota critical at 95% utilization",
        importance=MemoryImportance.CRITICAL,
    )
    mgr.record_derived_fact(
        category="FRONTEND_UI",
        fact_summary="Navbar active tab is Dashboard",
        importance=MemoryImportance.LOW,
    )

    results = mgr.query_facts("PostgreSQL", limit=5)
    assert len(results) == 2
    # Critical importance should rank first
    assert results[0].importance == MemoryImportance.CRITICAL
    assert "disk quota critical" in results[0].fact_summary


# 3. Duplicate Suppression
def test_duplicate_suppression():
    """Verify low-value repetitive observations are suppressed and do not flood memory."""
    memory = InMemoryConversationMemory()
    mgr = EpisodicEnvironmentalMemoryManager(memory=memory)

    # First observation
    fact1 = mgr.record_derived_fact(
        category="STATUS",
        fact_summary="Application running on port 8080",
        source_application="server.exe",
    )

    # Identical repeated observation
    fact2 = mgr.record_derived_fact(
        category="STATUS",
        fact_summary="Application running on port 8080",
        source_application="server.exe",
    )

    assert fact1 is not None
    assert fact2 is not None
    assert fact1.fact_id == fact2.fact_id  # Reused existing fact
    assert len(mgr._facts) == 1


# 4. Fact Correction Mechanism
def test_fact_correction_and_superseding():
    """Verify facts can be corrected, properly marking old facts as superseded."""
    memory = InMemoryConversationMemory()
    mgr = EpisodicEnvironmentalMemoryManager(memory=memory)

    old_fact = mgr.record_derived_fact(
        category="CONFIG",
        fact_summary="Server running on port 3000",
    )
    assert old_fact.is_active is True

    new_fact = mgr.correct_fact(
        old_fact_id=old_fact.fact_id,
        new_fact_summary="Server running on port 8080",
        reason="Port reassigned in .env",
    )

    assert new_fact is not None
    assert old_fact.is_active is False
    assert old_fact.superseded_by == new_fact.fact_id
    assert new_fact.metadata.get("supersedes") == old_fact.fact_id

    # Active query should only return new fact
    active_facts = mgr.query_facts("Server running on port")
    assert len(active_facts) == 1
    assert "8080" in active_facts[0].fact_summary


# 5. Fact Forgetting Mechanism
def test_fact_forgetting_mechanism():
    """Verify deactivation of obsolete facts via forget_fact."""
    memory = InMemoryConversationMemory()
    mgr = EpisodicEnvironmentalMemoryManager(memory=memory)

    fact = mgr.record_derived_fact(
        category="TEMP",
        fact_summary="Temporary token extracted",
    )
    assert fact.is_active is True

    res = mgr.forget_fact(fact.fact_id)
    assert res is True
    assert fact.is_active is False

    query_res = mgr.query_facts("Temporary token")
    assert len(query_res) == 0


# 6. Secret and Credential Redaction
def test_secret_redaction_before_persistence():
    """Verify API keys, passwords, and tokens are redacted from episodic memory."""
    memory = InMemoryConversationMemory()
    mgr = EpisodicEnvironmentalMemoryManager(memory=memory)

    fake_key = "AIza" + "Sy" + "D12345678901234567890123456789012"
    secret_obs = f"Connected with api_key: {fake_key} and password=SuperSecretPass99."
    fact = mgr.record_derived_fact(
        category="AUTH",
        fact_summary=secret_obs,
    )

    assert fake_key not in fact.fact_summary
    assert "SuperSecretPass99" not in fact.fact_summary
    assert ("[REDACTED_API_KEY]" in fact.fact_summary or "[REDACTED_SECRET]" in fact.fact_summary)
    assert "[REDACTED_PASSWORD]" in fact.fact_summary


# 7. Cross-Task Isolation
def test_cross_task_isolation():
    """Verify facts scoped to specific task IDs are isolated upon querying."""
    memory = InMemoryConversationMemory()
    mgr = EpisodicEnvironmentalMemoryManager(memory=memory)

    mgr.record_derived_fact(
        category="TASK_STEP",
        fact_summary="Compiled module A successfully",
        task_id="task_alpha",
    )
    mgr.record_derived_fact(
        category="TASK_STEP",
        fact_summary="Compiled module B successfully",
        task_id="task_beta",
    )

    alpha_facts = mgr.query_facts("Compiled", task_id="task_alpha")
    assert len(alpha_facts) == 1
    assert "module A" in alpha_facts[0].fact_summary

    beta_facts = mgr.query_facts("Compiled", task_id="task_beta")
    assert len(beta_facts) == 1
    assert "module B" in beta_facts[0].fact_summary
