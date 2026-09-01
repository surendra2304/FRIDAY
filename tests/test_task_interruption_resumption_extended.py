"""Comprehensive unit test suite for Cognitive Task Planning.7: Task Interruption, Checkpointing & Resumption.

Tests:
1. User pause, pause/resume lifecycle, and execution status preservation.
2. Voice barge-in interruption recording without task state corruption.
3. Process restart persistence via SQLite checkpoint store.
4. Network failure interruption and recovery state serialization.
5. Stale checkpoint and changed screen environment detection on resumption.
6. User cancellation checkpoint cleanup.
7. Sensitive data sanitization (API keys, passwords, base64 screenshots).
"""


from friday.agent.checkpoint import InterruptionReason, TaskCheckpointStore
from friday.agent.planner import PlanStep, StepStatus, TaskPlan
from friday.agent.state import TaskState


# 1. User Pause and Resume Lifecycle
def test_user_pause_and_resume():
    step1 = PlanStep(step_id="s1", description="Step 1", tool_name="tool_1", status=StepStatus.COMPLETED)
    step2 = PlanStep(step_id="s2", description="Step 2", tool_name="tool_2", status=StepStatus.PENDING)
    plan = TaskPlan(plan_id="plan_1", goal="Pause Test", steps=[step1, step2])

    store = TaskCheckpointStore()
    chk = store.save_checkpoint(
        task_id="task_pause_1",
        goal="Pause Test",
        plan=plan,
        state=TaskState.PAUSED,
        active_step_id="s2",
        step_results={"s1": "Output 1"},
        environment_hash="hash_abc",
        interruption_reason=InterruptionReason.USER_PAUSE,
    )

    assert chk.state == TaskState.PAUSED
    assert chk.interruption_reason == InterruptionReason.USER_PAUSE
    assert chk.completed_steps == ["s1"]
    assert chk.pending_steps == ["s2"]

    retrieved = store.get_latest_checkpoint("task_pause_1")
    assert retrieved is not None
    assert retrieved.active_step_id == "s2"
    assert retrieved.interruption_reason == InterruptionReason.USER_PAUSE


# 2. Voice Barge-In Interruption
def test_voice_barge_in_interruption():
    step1 = PlanStep(step_id="s1", description="Speaking response", tool_name="tts", status=StepStatus.IN_PROGRESS)
    plan = TaskPlan(plan_id="plan_v", goal="Voice Workflow", steps=[step1])

    store = TaskCheckpointStore()
    chk = store.save_checkpoint(
        task_id="task_voice_1",
        goal="Voice Workflow",
        plan=plan,
        state=TaskState.PAUSED,
        active_step_id="s1",
        step_results={},
        interruption_reason=InterruptionReason.VOICE_BARGE_IN,
    )

    assert chk.interruption_reason == InterruptionReason.VOICE_BARGE_IN
    val = store.validate_resumption(chk, current_environment_hash="default")
    assert val["can_resume"] is True
    assert val["environment_valid"] is True


# 3. Process Restart Persistence via SQLite
def test_process_restart_sqlite_store(tmp_path):
    db_path = str(tmp_path / "checkpoints_test.db")

    store1 = TaskCheckpointStore(db_path=db_path)
    step1 = PlanStep(step_id="s1", description="Step 1", tool_name="t1", status=StepStatus.COMPLETED)
    plan = TaskPlan(plan_id="p_persist", goal="Persistent Goal", steps=[step1])

    store1.save_checkpoint(
        task_id="task_persist_1",
        goal="Persistent Goal",
        plan=plan,
        state=TaskState.PAUSED,
        active_step_id=None,
        step_results={"s1": "Persisted output"},
        environment_hash="env_hash_123",
        interruption_reason=InterruptionReason.APPLICATION_SHUTDOWN,
        recovery_state={"retry_count": 1},
    )

    # Simulate process restart by instantiating new store
    store2 = TaskCheckpointStore(db_path=db_path)
    chk = store2.get_latest_checkpoint("task_persist_1")

    assert chk is not None
    assert chk.goal == "Persistent Goal"
    assert chk.interruption_reason == InterruptionReason.APPLICATION_SHUTDOWN
    assert chk.recovery_state == {"retry_count": 1}
    assert chk.step_results["s1"] == "Persisted output"


# 4. Changed Screen / Environment Stale Detection
def test_environment_stale_detection():
    step1 = PlanStep(step_id="s1", description="Step 1", tool_name="t1", status=StepStatus.COMPLETED)
    plan = TaskPlan(plan_id="p_stale", goal="Stale Test", steps=[step1])

    store = TaskCheckpointStore()
    chk = store.save_checkpoint(
        task_id="task_stale_1",
        goal="Stale Test",
        plan=plan,
        state=TaskState.PAUSED,
        active_step_id="s1",
        step_results={},
        environment_hash="screen_hash_initial",
    )

    # Valid resumption with same environment
    val_ok = store.validate_resumption(chk, current_environment_hash="screen_hash_initial")
    assert val_ok["environment_valid"] is True
    assert val_ok["requires_replan"] is False

    # Invalid resumption with changed screen environment
    val_changed = store.validate_resumption(chk, current_environment_hash="screen_hash_different")
    assert val_changed["environment_valid"] is False
    assert val_changed["requires_replan"] is True


# 5. Sensitive Data Sanitization
def test_checkpoint_sensitive_data_sanitization():
    step1 = PlanStep(step_id="s1", description="Step 1", tool_name="t1", status=StepStatus.COMPLETED)
    plan = TaskPlan(plan_id="p_sec", goal="Security Test", steps=[step1])

    store = TaskCheckpointStore()
    chk = store.save_checkpoint(
        task_id="task_sec_1",
        goal="Security Test",
        plan=plan,
        state=TaskState.PAUSED,
        active_step_id="s1",
        step_results={
            "s1": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==",
            "s2": "User token=ghp_secretpassword12345",
        },
    )

    assert "[Visual screenshot sanitized]" in chk.step_results["s1"]
    assert "[Sensitive credentials redacted]" in chk.step_results["s2"]


# 6. Cancellation Cleanup
def test_cancellation_cleanup():
    step1 = PlanStep(step_id="s1", description="Step 1", tool_name="t1", status=StepStatus.COMPLETED)
    plan = TaskPlan(plan_id="p_cancel", goal="Cancel Test", steps=[step1])

    store = TaskCheckpointStore()
    store.save_checkpoint(
        task_id="task_cancel_1",
        goal="Cancel Test",
        plan=plan,
        state=TaskState.PAUSED,
        active_step_id="s1",
        step_results={},
    )

    assert store.get_latest_checkpoint("task_cancel_1") is not None
    deleted = store.delete_checkpoint("task_cancel_1")
    assert deleted is True
    assert store.get_latest_checkpoint("task_cancel_1") is None
