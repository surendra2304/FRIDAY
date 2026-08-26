# -*- coding: utf-8 -*-
"""Unit tests for Proactive Background Monitoring Proactive FRIDAY: Scheduler, Background Monitor, Notification Manager, and Safety Gating."""

import os
import time
import pytest

from friday.core.types import SafetyLevel, AuthorizationDecision
from friday.core.auth import DefaultSecureAuthorizer
from friday.workflows.scheduler import WorkflowScheduler, ScheduledJob
from friday.observability.notifications import NotificationManager
from friday.observability.monitor import BackgroundMonitorService
from friday.agent.agent import FridayAgent
from friday.memory.in_memory import InMemoryConversationMemory
from friday.llm.base import BaseLLMProvider
from friday.core.types import Message, Role


class DummyLLM(BaseLLMProvider):
    def __init__(self, model="dummy-model"):
        super().__init__(model=model)

    @property
    def provider_name(self) -> str:
        return "dummy"

    def generate(self, messages, tools=None):
        return Message(role=Role.ASSISTANT, content="I'm here to help.")


def test_workflow_scheduler_interval_execution():
    scheduler = WorkflowScheduler(tick_interval=0.1)
    call_counts = {"count": 0}

    def increment():
        call_counts["count"] += 1

    job_id = scheduler.register_interval_job(
        name="test_counter",
        interval_seconds=0.05,
        action_fn=increment,
        safety_level=SafetyLevel.SAFE,
    )
    assert len(scheduler.list_jobs()) == 1

    # Run once
    ran = scheduler.run_pending_jobs_once()
    assert ran == 1
    assert call_counts["count"] == 1

    # Clean unregister
    assert scheduler.unregister_job(job_id) is True
    assert len(scheduler.list_jobs()) == 0


def test_workflow_scheduler_file_watch_condition(tmp_path):
    scheduler = WorkflowScheduler(tick_interval=0.1)
    watched_file = str(tmp_path / "watch_target.txt")
    with open(watched_file, "w") as f:
        f.write("initial")

    triggers = {"count": 0}

    def on_mod():
        triggers["count"] += 1

    job_id = scheduler.register_file_watch_job(
        name="file_watcher",
        file_path=watched_file,
        action_fn=on_mod,
    )

    # First run without changes -> no trigger
    scheduler.run_pending_jobs_once()
    assert triggers["count"] == 0

    # Modify file
    time.sleep(0.05)
    with open(watched_file, "w") as f:
        f.write("updated content")

    # Run check -> trigger
    ran = scheduler.run_pending_jobs_once()
    assert ran == 1
    assert triggers["count"] == 1


def test_scheduler_safety_gating():
    authorizer = DefaultSecureAuthorizer()
    scheduler = WorkflowScheduler(authorizer=authorizer)
    executed = []

    def dangerous_action():
        executed.append("dangerous")

    # Registering a DANGEROUS risk job without pre-approval should be blocked by DefaultSecureAuthorizer
    scheduler.register_interval_job(
        name="dangerous_job",
        interval_seconds=1.0,
        action_fn=dangerous_action,
        safety_level=SafetyLevel.DANGEROUS,
    )

    ran = scheduler.run_pending_jobs_once()
    assert ran == 0
    assert len(executed) == 0


def test_notifications_manager_queue_and_summary():
    nm = NotificationManager()
    assert nm.pop_notifications_summary() is None

    # Post notification
    n_id = nm.post_notification("weather alert in your area", category="weather")
    assert n_id is not None

    summary = nm.pop_notifications_summary()
    assert "I noticed that weather alert in your area while you were away." in summary

    # Subsequent fetch should be empty
    assert nm.pop_notifications_summary() is None


def test_background_monitor_webpage_diff():
    scheduler = WorkflowScheduler()
    nm = NotificationManager()
    monitor = BackgroundMonitorService(scheduler=scheduler, notifications=nm)

    pages = {"content": "Initial HTML 1.0"}

    def fetch_mock(url):
        return pages["content"]

    monitor.monitor_webpage_change(
        name="NewsSite",
        url="https://example.com/news",
        fetch_fn=fetch_mock,
        interval_seconds=0.1,
    )

    # Initial baseline
    scheduler.run_pending_jobs_once(force_interval=True)
    assert len(nm.fetch_pending_notifications(mark_delivered=False)) == 0

    # Update web page content
    pages["content"] = "Breaking News HTML 2.0"
    scheduler.run_pending_jobs_once(force_interval=True)

    pending = nm.fetch_pending_notifications(mark_delivered=True)
    assert len(pending) == 1
    assert "content at 'https://example.com/news'" in pending[0].message


def test_agent_surfaces_proactive_notifications():
    mem = InMemoryConversationMemory()
    llm = DummyLLM()
    agent = FridayAgent(llm_provider=llm, memory=mem)

    # Enqueue proactive notification
    agent.notifications.post_notification("file 'report.pdf' was modified")

    # Next user message should prepend proactive insight
    resp = agent.process_message("hello")
    assert "I noticed that file 'report.pdf' was modified while you were away." in resp.content
    assert len(resp.content) > len("I noticed that file 'report.pdf' was modified while you were away.")

    agent.close()
