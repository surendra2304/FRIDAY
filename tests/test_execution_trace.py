"""Tests for ExecutionTraceStore and checkpoint persistence."""

import pytest
from friday.agent.execution_trace import (
    ExecutionTraceCheckpoint,
    ExecutionTraceStore,
)


@pytest.fixture
def temp_trace_store(tmp_path):
    db_path = str(tmp_path / "test_traces.db")
    store = ExecutionTraceStore(db_path=db_path)
    yield store


def test_execution_trace_init_and_sync_record(temp_trace_store):
    store = temp_trace_store
    cp = ExecutionTraceCheckpoint(
        trace_id="tr_101",
        task_id="tsk_101",
        target_agent="inference",
        action="reason_step",
        status="SUCCESS",
        consensus_status="NONE",
        participating_agents=["inference"],
        agreement_ratio=1.0,
        latency_ms=145,
        retry_count=1,
        payload_summary="Test prompt",
        result_summary="Reasoning output generated",
    )
    saved = store.record_checkpoint(cp)
    assert saved.id is not None
    assert saved.id > 0
    assert saved.trace_id == "tr_101"

    traces = store.get_recent_traces(limit=10)
    assert len(traces) == 1
    t = traces[0]
    assert t.trace_id == "tr_101"
    assert t.task_id == "tsk_101"
    assert t.target_agent == "inference"
    assert t.status == "SUCCESS"
    assert t.latency_ms == 145
    assert t.participating_agents == ["inference"]


@pytest.mark.asyncio
async def test_execution_trace_async_record(temp_trace_store):
    store = temp_trace_store
    cp = ExecutionTraceCheckpoint(
        trace_id="tr_202",
        task_id="tsk_202",
        target_agent="cortex",
        action="scrape_docs",
        status="SUCCESS",
        consensus_status="NONE",
        participating_agents=["cortex"],
        agreement_ratio=1.0,
        latency_ms=210,
    )
    saved = await store.record_checkpoint_async(cp)
    assert saved.id is not None
    assert saved.id > 0

    fetched = store.get_trace_by_id("tr_202")
    assert fetched is not None
    assert fetched.trace_id == "tr_202"
    assert fetched.action == "scrape_docs"


def test_execution_trace_query_filtering(temp_trace_store):
    store = temp_trace_store
    for i in range(5):
        store.record_checkpoint(
            ExecutionTraceCheckpoint(
                trace_id=f"tr_inf_{i}",
                task_id=f"tsk_inf_{i}",
                target_agent="inference",
                action="chat",
                status="SUCCESS" if i % 2 == 0 else "DEGRADED",
            )
        )
    for i in range(3):
        store.record_checkpoint(
            ExecutionTraceCheckpoint(
                trace_id=f"tr_for_{i}",
                task_id=f"tsk_for_{i}",
                target_agent="forge",
                action="build",
                status="SUCCESS",
            )
        )

    all_recent = store.get_recent_traces(limit=20)
    assert len(all_recent) == 8

    inf_only = store.get_recent_traces(limit=10, target_agent="inference")
    assert len(inf_only) == 5
    assert all(t.target_agent == "inference" for t in inf_only)

    degraded_only = store.get_recent_traces(limit=10, status="DEGRADED")
    assert len(degraded_only) == 2
    assert all(t.status == "DEGRADED" for t in degraded_only)


def test_consensus_trace_filtering(temp_trace_store):
    store = temp_trace_store
    store.record_checkpoint(
        ExecutionTraceCheckpoint(
            trace_id="tr_single",
            task_id="tsk_1",
            target_agent="memora",
            action="recall",
            status="SUCCESS",
            consensus_status="NONE",
        )
    )
    store.record_checkpoint(
        ExecutionTraceCheckpoint(
            trace_id="tr_consensus_1",
            task_id="tsk_2",
            target_agent="consensus",
            action="market_evaluation",
            status="SUCCESS",
            consensus_status="ACHIEVED",
            participating_agents=["inference", "cortex", "futuris"],
            agreement_ratio=1.0,
        )
    )
    store.record_checkpoint(
        ExecutionTraceCheckpoint(
            trace_id="tr_consensus_2",
            task_id="tsk_3",
            target_agent="consensus",
            action="policy_vote",
            status="DEGRADED",
            consensus_status="DIVERGENT",
            participating_agents=["sentinel", "cortex"],
            agreement_ratio=0.5,
        )
    )

    c_traces = store.get_consensus_traces(limit=10)
    assert len(c_traces) == 2
    trace_ids = [t.trace_id for t in c_traces]
    assert "tr_consensus_1" in trace_ids
    assert "tr_consensus_2" in trace_ids
    assert "tr_single" not in trace_ids
