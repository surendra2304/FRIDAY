# -*- coding: utf-8 -*-
"""Deterministic unit tests for Phase 6.5 Vision Memory & FTS/Embedding Fallback."""

import os
from unittest import mock
import pytest

from friday.core.types import Message, Role
from friday.memory.sqlite import SQLiteConversationMemory
from friday.vision.screen_context import ScreenContext
from friday.vision.vision_memory import VisionMemoryManager, redact_sensitive_visual_text


def test_redact_sensitive_visual_text():
    """Verify sensitive API keys, passwords, and tokens are redacted before persistence."""
    fake_key = "AIza" + "Sy" + "D9876543210zyxwvutsrqponmlkjihg"
    raw_text = (
        f"VS Code editor active. Configuration has gemini_api_key: {fake_key} "
        "and password='SuperSecretPassword123' and Authorization: Bearer abcdef1234567890abcdef1234567890."
    )
    sanitized = redact_sensitive_visual_text(raw_text)

    assert fake_key not in sanitized
    assert "SuperSecretPassword123" not in sanitized
    assert "abcdef1234567890abcdef1234567890" not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized or "[REDACTED_SECRET]" in sanitized
    assert "[REDACTED_PASSWORD]" in sanitized
    assert "[REDACTED_TOKEN]" in sanitized


def test_vision_memory_storage_and_duplicate_suppression(tmp_path):
    """Verify VisionMemoryManager stores derived text in SQLite and suppresses duplicates."""
    db_file = str(tmp_path / "test_vis_memory.db")
    memory = SQLiteConversationMemory(db_path=db_file)
    vmm = VisionMemoryManager(memory=memory)

    ctx = ScreenContext(
        summary="Terminal displays successful pytest run with 290 passed.",
        width=1920,
        height=1080,
    )

    # 1. First storage creates a message in persistent memory
    msg1 = vmm.store_visual_observation(ctx)
    assert msg1 is not None
    assert "Visual Observation - 1920x1080" in msg1.content
    assert "successful pytest run" in msg1.content

    # 2. Immediate duplicate storage is suppressed (returns None)
    msg2 = vmm.store_visual_observation(ctx)
    assert msg2 is None

    # 3. Forced duplicate storage creates a message
    msg3 = vmm.store_visual_observation(ctx, force=True)
    assert msg3 is not None


def test_vision_memory_fts_fallback_when_embedding_unavailable(tmp_path):
    """Verify memory recall works seamlessly via SQLite FTS5 when semantic embedding provider fails or is None."""
    db_file = str(tmp_path / "test_vis_fts.db")
    # Embedding provider is None -> SQLiteConversationMemory automatically uses FTS5
    memory = SQLiteConversationMemory(db_path=db_file, embedding_provider=None)
    vmm = VisionMemoryManager(memory=memory)

    ctx = ScreenContext(
        summary="Grafana dashboard showing CPU usage spike to 95 percent on cluster worker 2.",
        width=1920,
        height=1080,
    )
    vmm.store_visual_observation(ctx)

    # Search historical visual memories via FTS
    results = vmm.recall_visual_memories(query="Grafana CPU spike", limit=5)
    assert len(results) >= 1
    assert "Grafana dashboard" in results[0]["content"]
    assert "Visual Observation" in results[0]["content"]


def test_vision_memory_skips_error_contexts(tmp_path):
    """Verify error screen contexts are ignored and not written to persistent memory."""
    db_file = str(tmp_path / "test_err_mem.db")
    memory = SQLiteConversationMemory(db_path=db_file)
    vmm = VisionMemoryManager(memory=memory)

    err_ctx = ScreenContext(
        summary="",
        is_error=True,
        error_message="Desktop locked by screen saver",
    )

    msg = vmm.store_visual_observation(err_ctx)
    assert msg is None
