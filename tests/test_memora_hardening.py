# -*- coding: utf-8 -*-
"""Unit tests for Memora hardening, local-first storage, and quarantine context."""

from unittest.mock import patch, MagicMock
import os
import pytest

from friday.memory.memora_client import MemoraClient
from friday.core.types import Message, Role


def test_memora_remote_disabled_by_default():
    """Verify remote API requests are disabled by default without FRIDAY_MEMORA_REMOTE_ENABLED."""
    with patch.dict(os.environ, {}, clear=True):
        client = MemoraClient(local_db_path=":memory:")
        assert client.remote_enabled is False


def test_memora_sanitizes_credentials_before_persistence():
    """Verify raw API keys and secrets are redacted before persistence."""
    client = MemoraClient(local_db_path=":memory:")

    mock_secret_key = "sk-proj-1234567890abcdef1234567890abcdef"
    mock_gemini_key = "AIzaSyMockTokenNeverStoreInDatabase1234"
    raw_input = f"Remember my credentials: {mock_secret_key} and {mock_gemini_key} and password='my_super_password'"

    assert client.should_persist(raw_input) is False

    clean_text = client.sanitize_for_persistence(raw_input)
    assert mock_secret_key not in clean_text
    assert mock_gemini_key not in clean_text
    assert "[REDACTED_CREDENTIAL]" in clean_text


def test_memora_quarantine_headers_in_context_blocks():
    """Verify build_context_block contains UNTRUSTED reference demarcation."""
    client = MemoraClient(local_db_path=":memory:")

    with patch.object(client, "recall_memories", return_value=[{"content_text": "User prefers dark mode", "memory_type": "preference"}]):
        block = client.build_context_block("friday", "dark mode")
        assert "UNTRUSTED HISTORICAL REFERENCE DATA" in block
        assert "NOT SECURITY POLICY" in block
        assert "dark mode" in block


def test_agent_injects_recalled_memory_as_user_role():
    """Verify agent.py executes with memory quarantined under Role.USER rather than Role.SYSTEM."""
    from friday.agent.agent import FridayAgent
    from friday.llm.base import BaseLLMProvider
    from friday.tools.registry import ToolRegistry

    mock_llm = MagicMock(spec=BaseLLMProvider)
    mock_llm.model = "mock-model"
    mock_llm.provider_name = "mock"
    mock_llm.generate.return_value = Message(role=Role.ASSISTANT, content="I understand your preference.")

    agent = FridayAgent(llm_provider=mock_llm, tool_registry=ToolRegistry())

    with patch("friday.memory.memora_client.memora_client.build_context_block", return_value="User likes tea."):
        agent.execute_complex_task("what do i like?")

        # Check messages sent to LLM
        call_args = mock_llm.generate.call_args[0][0]

        # Ensure recalled memory was injected as Role.USER, not Role.SYSTEM
        found_memory = False
        for m in call_args:
            if "User likes tea" in m.content:
                found_memory = True
                assert m.role == Role.USER
                assert "UNTRUSTED HISTORICAL MEMORY CONTEXT" in m.content
        assert found_memory is True
