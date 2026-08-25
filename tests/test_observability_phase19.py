# -*- coding: utf-8 -*-
"""Unit tests for Phase 19: Observability, Timeline Replay, and Unified Status Panel."""

import pytest
from friday.observability.timeline import ExecutionTimeline, TimelineEvent, global_timeline
from friday.cli.main import render_status_panel


def test_timeline_recording_and_bounds():
    tl = ExecutionTimeline(max_events=5)
    assert len(tl.get_events()) == 0

    for i in range(10):
        tl.record_event(
            event_type="test_step",
            description=f"Step {i}",
            details={"step_num": i},
            duration_ms=float(i * 10),
        )

    events = tl.get_events()
    assert len(events) == 5
    assert events[-1].description == "Step 9"
    assert events[0].description == "Step 5"
    assert events[-1].duration_ms == 90.0


def test_timeline_status_updates():
    tl = ExecutionTimeline()
    tl.update_status(
        cognitive_phase="EXECUTION",
        active_agent="Coder",
        selected_provider="Groq",
        active_tool="calculator",
        last_latency_ms=125.4,
    )
    st = tl.get_status()
    assert st["cognitive_phase"] == "EXECUTION"
    assert st["active_agent"] == "Coder"
    assert st["selected_provider"] == "Groq"
    assert st["active_tool"] == "calculator"
    assert st["last_latency_ms"] == 125.4


def test_timeline_replay_formatting():
    tl = ExecutionTimeline()
    empty_str = tl.format_replay()
    assert "No recent execution steps" in empty_str

    tl.record_event("cognitive_phase", "Transitioned to PLANNING")
    tl.record_event("tool_execution", "Executed file_write", duration_ms=45.2)

    replay = tl.format_replay()
    assert "TASK EXECUTION TIMELINE REPLAY" in replay
    assert "PLANNING" in replay
    assert "file_write" in replay
    assert "45.2ms" in replay


def test_render_status_panel():
    global_timeline.update_status(
        cognitive_phase="VERIFY",
        active_agent="Architect",
        selected_provider="Mistral",
        active_tool="web_fetch",
        last_latency_ms=88.5,
    )
    status_line = render_status_panel()
    assert status_line is not None
    plain = status_line.plain
    assert "Mistral" in plain
    assert "web_fetch" in plain
    assert "88.5ms" in plain
