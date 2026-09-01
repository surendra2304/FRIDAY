"""Comprehensive unit test suite for Persistent Operators and Event-Driven Triggers."""

import os
import time
from typing import Any

from friday.core.auth import DefaultSecureAuthorizer
from friday.core.types import SafetyLevel
from friday.observability.notifications import NotificationManager
from friday.operators.base_operator import (
    BaseOperator,
    OperatorState,
)
from friday.operators.manager import OperatorManager
from friday.operators.triggers import (
    ConditionTrigger,
    FileSystemTrigger,
    IntervalTrigger,
    ProcessTrigger,
)
from friday.skills.builtins.network_diagnostic import NetworkDiagnosticSkill
from friday.skills.registry import SkillRegistry
from friday.workflows.scheduler import WorkflowScheduler


class SimpleTestOperator(BaseOperator):
    """Concrete test operator."""
    def execute_action(self, event_data: dict[str, Any]) -> Any:
        return f"Handled: {event_data.get('event_type')}"


def test_operator_lifecycle_states():
    """Verify operator state transitions: INITIALIZED -> RUNNING -> PAUSED -> RUNNING -> STOPPED."""
    op = SimpleTestOperator(name="test_op")
    assert op.check_state() == OperatorState.INITIALIZED

    op.start()
    assert op.check_state() == OperatorState.RUNNING

    op.pause()
    assert op.check_state() == OperatorState.PAUSED

    op.resume()
    assert op.check_state() == OperatorState.RUNNING

    op.stop()
    assert op.check_state() == OperatorState.STOPPED


def test_filesystem_trigger_file_creation_and_modification(tmp_path):
    """FileSystemTrigger detects newly created and modified files."""
    watch_dir = str(tmp_path / "watch_folder")
    os.makedirs(watch_dir, exist_ok=True)

    trigger = FileSystemTrigger(watch_path=watch_dir)
    trigger.start()

    # Initial check should be quiet
    assert trigger.evaluate() is None

    # Create file
    test_file = os.path.join(watch_dir, "event_doc.txt")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("Initial content")

    event = trigger.evaluate()
    assert event is not None
    assert event["event_type"] in ("file_created", "file_modified")
    assert "event_doc.txt" in event["path"]

    # Modify file after brief sleep to ensure mtime change
    time.sleep(0.02)
    with open(test_file, "a", encoding="utf-8") as f:
        f.write(" - updated")

    event_mod = trigger.evaluate()
    assert event_mod is not None
    assert event_mod["event_type"] == "file_modified"

    trigger.stop()


def test_process_trigger_with_mocked_psutil(monkeypatch):
    """ProcessTrigger detects process start and stop events."""
    mock_pids = set()

    class MockProcess:
        def __init__(self, pid, name):
            self.info = {"pid": pid, "name": name}

    def mock_iter(attrs):
        return [MockProcess(pid=p, name="notepad.exe") for p in mock_pids]

    import psutil
    monkeypatch.setattr(psutil, "process_iter", mock_iter)

    trigger = ProcessTrigger(process_name="notepad.exe", watch_event="any")
    trigger.start()

    # No events initially
    assert trigger.evaluate() is None

    # Simulate process start
    mock_pids.add(12345)
    event_start = trigger.evaluate()
    assert event_start is not None
    assert event_start["event_type"] == "process_started"
    assert event_start["pid"] == 12345

    # Simulate process stop
    mock_pids.clear()
    event_stop = trigger.evaluate()
    assert event_stop is not None
    assert event_stop["event_type"] == "process_stopped"

    trigger.stop()


def test_condition_and_interval_triggers():
    """ConditionTrigger and IntervalTrigger evaluation."""
    flag = False
    cond_trig = ConditionTrigger(predicate=lambda: flag, name="flag_trigger")
    cond_trig.start()
    assert cond_trig.evaluate() is None

    flag = True
    event = cond_trig.evaluate()
    assert event is not None
    assert event["event_type"] == "condition_met"

    interval_trig = IntervalTrigger(interval_seconds=0.01)
    interval_trig.start()
    event_int = interval_trig.evaluate()
    assert event_int is not None
    assert event_int["event_type"] == "interval_elapsed"


def test_operator_chaining():
    """Operator A pipes output to Operator B automatically upon trigger."""
    results_a = []
    results_b = []

    op_a = SimpleTestOperator(
        name="operator_a",
        target_action=lambda ev: results_a.append(ev) or "Output From Op A",
    )
    op_b = SimpleTestOperator(
        name="operator_b",
        target_action=lambda ev: results_b.append(ev) or "Output From Op B",
    )

    # Chain using pipeline syntax
    op_a | op_b

    op_a.start()
    op_b.start()

    res = op_a.handle_event({"event_type": "initial_trigger", "data": "alpha"})
    assert res.success is True
    assert len(results_a) == 1
    assert len(results_b) == 1
    assert results_b[0]["upstream_operator"] == "operator_a"
    assert results_b[0]["upstream_output"] == "Output From Op A"


def test_operator_executes_skill_and_notifies():
    """Operator executes target skill and emits notification upon event trigger."""
    skill_reg = SkillRegistry()
    skill_reg.register(NetworkDiagnosticSkill())

    notif_mgr = NotificationManager()

    op = SimpleTestOperator(
        name="network_monitor_operator",
        target_skill_name="network_diagnostic",
        skill_registry=skill_reg,
        notification_manager=notif_mgr,
        notification_category="network_alert",
    )
    op.start()

    res = op.handle_event({"event_type": "network_anomaly", "metric": "packet_loss"})
    assert res.success is True
    assert "Network Diagnostic Summary" in str(res.output)

    notifications = notif_mgr.fetch_pending_notifications(mark_delivered=False)
    assert len(notifications) == 1
    assert "network_monitor_operator" in notifications[0].message


def test_operator_safety_blocking_on_dangerous_action():
    """Operator with DANGEROUS safety level is blocked by DefaultSecureAuthorizer."""
    authorizer = DefaultSecureAuthorizer()
    op = SimpleTestOperator(
        name="wipe_system_operator",
        safety_level=SafetyLevel.DANGEROUS,
        authorizer=authorizer,
    )
    op.start()

    res = op.handle_event({"event_type": "kill_switch"})
    assert res.success is False
    assert "Safety Block" in res.error
    assert op.check_state() == OperatorState.ERROR


def test_workflow_scheduler_operator_integration():
    """WorkflowScheduler ticks registered operators during run_pending_jobs_once."""
    scheduler = WorkflowScheduler(tick_interval=0.1)

    executed_events = []
    flag = False

    op = SimpleTestOperator(
        name="scheduler_integrated_op",
        triggers=[ConditionTrigger(predicate=lambda: flag)],
        target_action=lambda ev: executed_events.append(ev),
    )

    scheduler.register_operator(op)
    assert len(scheduler.list_operators()) == 1

    # Initially flag is False -> no executions
    count = scheduler.run_pending_jobs_once()
    assert len(executed_events) == 0

    # Flip flag -> triggers operator
    flag = True
    count = scheduler.run_pending_jobs_once()
    assert count >= 1
    assert len(executed_events) == 1
    assert executed_events[0]["event_type"] == "condition_met"

    scheduler.unregister_operator("scheduler_integrated_op")
    assert len(scheduler.list_operators()) == 0


def test_operator_manager_crud_and_tick():
    """OperatorManager registers, ticks, and unregisters operators."""
    mgr = OperatorManager()
    triggered = []

    op = SimpleTestOperator(
        name="manager_test_op",
        triggers=[ConditionTrigger(predicate=lambda: True)],
        target_action=lambda ev: triggered.append(ev),
    )

    mgr.register_operator(op)
    assert len(mgr.list_operators()) == 1

    results = mgr.tick_all()
    assert len(results) == 1
    assert results[0].success is True
    assert len(triggered) == 1

    mgr.unregister_operator(op.operator_id)
    assert len(mgr.list_operators()) == 0
