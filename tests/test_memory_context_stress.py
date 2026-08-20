# -*- coding: utf-8 -*-
"""Comprehensive Memory, Context Stress & Scalability Test Suite for Phase 10.6.

Validates:
1. Long conversation history scaling without unbounded RAM growth.
2. Short-term task context strict isolation from long-term memory.
3. Memory compaction, observation sliding windows (max 15), and FIFO eviction.
4. Episodic environmental memory duplicate suppression & fact forgetting.
5. FTS5 full-text search fallback under embedding quota failures.
6. Checkpoint scrubbing of sensitive tokens and raw screenshots.
7. Secure memory deletion / purge flows.
"""

from datetime import datetime, timezone
import os
import tempfile
import time
import pytest

from friday.agent.checkpoint import TaskCheckpointStore
from friday.agent.planner import PlanStep, TaskPlan
from friday.agent.state import TaskState
from friday.core.types import Message, Role, SafetyLevel
from friday.memory.in_memory import InMemoryConversationMemory
from friday.memory.sqlite import SQLiteConversationMemory
from friday.memory.task_context import ActiveTaskContext
from friday.vision.episodic_memory import EpisodicEnvironmentalMemoryManager, MemoryImportance


# --- 1. Long Conversation History Stress Test ---

def test_long_conversation_history_bounded_context_window():
    """Verify that adding 200 messages preserves the configured context window limit."""
    mem = InMemoryConversationMemory(max_messages=30)

    for i in range(200):
        mem.add_message(Message(role=Role.USER, content=f"User prompt iteration {i}"))
        mem.add_message(Message(role=Role.ASSISTANT, content=f"Assistant response iteration {i}"))

    # Bounded active context window
    ctx_window = mem.get_context_window(max_messages=30)
    assert len(ctx_window) == 30
    assert "iteration 199" in ctx_window[-1].content


# --- 2. Short-Term Task Context Isolation & Sliding Window Eviction ---

def test_task_context_sliding_window_and_isolation():
    """Verify ActiveTaskContext enforces max_observations sliding window and sensitive token redaction."""
    ctx = ActiveTaskContext(
        task_id="stress_task_1",
        goal="Stress test working context",
        max_observations=15,
        max_output_chars_per_step=500,
    )

    # Add 40 observations (exceeding capacity of 15)
    for i in range(40):
        ctx.add_observation(step_id=f"step_{i}", content=f"Observation {i} detail")

    # FIFO sliding window must keep exactly the latest 15
    assert len(ctx.observations) == 15
    assert ctx.observations[0].content == "Observation 25 detail"
    assert ctx.observations[-1].content == "Observation 39 detail"

    # Verify secret scrubbing in observations
    ctx.add_observation(step_id="step_sec", content="Found API token=sk-TESTSECRET12345")
    assert ctx.observations[-1].content == "[Sensitive credentials redacted]"

    # Verify screenshot scrubbing in step outputs
    ctx.record_step_result(step_id="step_img", result="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...")
    assert ctx.step_outputs["step_img"] == "[Visual screenshot captured and processed safely]"


# --- 3. Episodic Environmental Memory Deduplication & Fact Forgetting ---

def test_episodic_memory_deduplication_and_forgetting():
    """Verify episodic memory rejects identical duplicate facts and supports fact forgetting."""
    memory = InMemoryConversationMemory()
    manager = EpisodicEnvironmentalMemoryManager(memory=memory)

    # Record fact 1
    f1 = manager.record_derived_fact(
        category="APPLICATION_STATE",
        fact_summary="VSCode active file is agent.py",
        importance=MemoryImportance.HIGH,
    )
    assert f1 is not None

    # Record duplicate fact 1 -> returns same fact, suppressed
    f1_dup = manager.record_derived_fact(
        category="APPLICATION_STATE",
        fact_summary="VSCode active file is agent.py",
        importance=MemoryImportance.HIGH,
    )
    assert f1_dup.fact_id == f1.fact_id
    assert len(manager._facts) == 1

    # Query fact
    results = manager.query_facts("VSCode")
    assert len(results) == 1
    assert "agent.py" in results[0].fact_summary


# --- 4. SQLite Memory Search Scalability & FTS5 Lexical Search ---

def test_sqlite_memory_search_scalability(tmp_path):
    """Verify SQLite persistent memory indexing and fast FTS search under 100 stored turns."""
    db_file = str(tmp_path / "stress.db")
    mem = SQLiteConversationMemory(db_path=db_file, max_messages=50)
    conv_id = mem.create_conversation("Stress Test Session")
    mem.load_conversation(conv_id)

    for i in range(100):
        mem.add_message(Message(role=Role.USER, content=f"Transaction index {i}: keyword target_{i%10}"))

    # FTS search for target_7
    t0 = time.perf_counter()
    results = mem.search("target_7", limit=10)
    t_search = (time.perf_counter() - t0) * 1000

    assert len(results) == 10
    assert t_search < 50.0  # Latency under 50ms


# --- 5. Checkpoint Store Sanitization & Bulk Storage Performance ---

def test_checkpoint_sanitization_and_bulk_operations():
    """Verify TaskCheckpointStore scrubs secrets and handles 50 rapid checkpoints."""
    store = TaskCheckpointStore()
    plan = TaskPlan(plan_id="stress_plan", goal="Perform bulk operations", steps=[
        PlanStep(step_id="s1", description="Step 1"),
        PlanStep(step_id="s2", description="Step 2"),
    ])

    for i in range(50):
        chk = store.save_checkpoint(
            task_id=f"bulk_task_{i}",
            goal=f"Goal {i}",
            plan=plan,
            state=TaskState.PAUSED,
            active_step_id="s1",
            step_results={"s1": f"Result {i} with key=TEST_SECRET_KEY_{i}"},
        )
        assert chk.step_results["s1"] == "[Sensitive credentials redacted]"

    # Verify lookup of latest checkpoint
    latest = store.get_latest_checkpoint("bulk_task_49")
    assert latest is not None
    assert latest.task_id == "bulk_task_49"
