# -*- coding: utf-8 -*-
"""Deterministic unit tests for Phase 6.6 Voice + Vision Integration."""

import asyncio
from unittest import mock
import pytest

from friday.core.types import SafetyLevel, ToolResult
from friday.agent.agent import FridayAgent
from friday.tools.builtin.screen_snapshot import ScreenSnapshotTool
from friday.vision.mock_screen import MockScreenCaptureProvider
from friday.vision.mock_vision import MockVisionProvider
from friday.voice.gemini_live_session import GeminiLiveVoiceSession


def test_gemini_live_session_keeps_screen_snapshot_local():
    """Verify GeminiLiveVoiceSession leaves screen tools with the local agent."""
    mock_cap = MockScreenCaptureProvider()
    mock_vis = MockVisionProvider()
    tool = ScreenSnapshotTool(capture_provider=mock_cap, vision_provider=mock_vis)

    agent = FridayAgent()
    agent.tools.register(tool)

    session = GeminiLiveVoiceSession(agent=agent)
    assert session._build_tools_config() is None


def test_voice_vision_system_instruction_mentions_screen_tool():
    """Verify Gemini Live system prompt instructs model to use get_screen_snapshot on visual screen queries."""
    session = GeminiLiveVoiceSession()
    sys_content = session._build_system_instruction()

    assert sys_content is not None
    prompt_text = sys_content.parts[0].text
    assert "get_screen_snapshot" in prompt_text
    assert "UNTRUSTED DATA" in prompt_text


def test_agent_handles_voice_vision_tool_call():
    """Verify agent executes get_screen_snapshot when queried via voice tool call simulation."""
    mock_cap = MockScreenCaptureProvider(width=1920, height=1080)
    mock_vis = MockVisionProvider(default_response="The screen shows an active trading bot dashboard with live chart.")

    agent = FridayAgent()
    agent.tools.register(ScreenSnapshotTool(capture_provider=mock_cap, vision_provider=mock_vis))

    # Simulate tool invocation from voice session
    res = agent.tools.execute("get_screen_snapshot", arguments={"query": "What is on my screen?"})
    assert res.is_error is False
    assert "Screen Snapshot (1920x1080" in res.content
    assert "active trading bot dashboard" in res.content
