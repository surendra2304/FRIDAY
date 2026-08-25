# -*- coding: utf-8 -*-
"""Unit tests for Phase 32 Critical Limit & Failover Fixes."""

from unittest import mock
import pytest

from friday.core.exceptions import LLMProviderError
from friday.core.types import Message, Role, SafetyLevel
from friday.llm.cerebras_provider import CerebrasLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.memory.sqlite import SQLiteConversationMemory
from friday.tools.builtin.open_application import OpenApplicationTool
from friday.vision.intent_detector import IntentDetector


def test_sqlite_memory_truncates_tool_output_bloat(tmp_path):
    """Tool messages exceeding 1000 characters must be truncated in memory."""
    db_file = tmp_path / "test_memory.db"
    mem = SQLiteConversationMemory(db_path=str(db_file), max_messages=10)

    huge_content = "A" * 5000
    msg = Message(role=Role.TOOL, name="fetch_webpage_content", content=huge_content, tool_call_id="call_123")
    mem.add_message(msg)

    stored = mem.get_messages()
    assert len(stored) == 1
    assert len(stored[0].content) <= 1040
    assert stored[0].content.startswith("A" * 1000)
    assert "[truncated to 1000 chars]" in stored[0].content


def test_sqlite_memory_context_window_truncation_5_turns_and_tokens(tmp_path):
    """Context window truncates to last 5 turns (~10 messages) and enforces token budget."""
    db_file = tmp_path / "test_window.db"
    mem = SQLiteConversationMemory(db_path=str(db_file), max_messages=50)

    # Insert 15 turns (30 messages)
    for i in range(15):
        mem.add_message(Message(role=Role.USER, content=f"User question {i}"))
        mem.add_message(Message(role=Role.ASSISTANT, content=f"Assistant answer {i}"))

    # Request context window with 5 turns limit
    window = mem.get_context_window(max_messages=50, max_turns=5, max_tokens=3000)
    assert len(window) == 10
    assert window[0].content == "User question 10"
    assert window[-1].content == "Assistant answer 14"


def test_in_memory_truncates_tool_output_bloat():
    """In-memory backend also truncates tool responses exceeding 1000 characters."""
    mem = InMemoryConversationMemory(max_messages=10)
    huge_content = "X" * 3000
    msg = Message(role=Role.TOOL, name="get_screen_snapshot", content=huge_content, tool_call_id="call_999")
    mem.add_message(msg)

    stored = mem.get_messages()
    assert len(stored) == 1
    assert len(stored[0].content) <= 1040
    assert "[truncated to 1000 chars]" in stored[0].content


def test_cerebras_402_payment_required_marks_credential_unhealthy():
    """Cerebras provider catches 402, marks credential unhealthy, and raises LLMProviderError."""
    mock_pool = mock.MagicMock()
    mock_client = mock.MagicMock()

    class Mock402Exception(Exception):
        status_code = 402

    mock_client.chat.completions.create.side_effect = Mock402Exception("Payment Required: free tier exhausted")

    provider = CerebrasLLMProvider(
        api_key="csk-test-key",
        credential_pool=mock_pool,
        max_retries=2,
    )
    provider._client = mock_client

    messages = [Message(role=Role.USER, content="Hello")]

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate(messages=messages)

    assert "402 Payment Required" in str(exc_info.value)
    # Crucial: no retries should have been attempted, failing immediately
    assert mock_client.chat.completions.create.call_count == 1
    mock_pool.report_unhealthy.assert_called_once_with("csk-test-key")


def test_microsoft_store_in_allowlist():
    """Microsoft Store is recognized in IntentDetector and OpenApplicationTool."""
    assert "microsoft store" in IntentDetector.APP_LAUNCH_MAP
    assert IntentDetector.APP_LAUNCH_MAP["microsoft store"] == "ms-windows-store:"

    tool = OpenApplicationTool()
    exe = tool._resolve_executable("microsoft store")
    assert exe == "ms-windows-store:"

    exe2 = tool._resolve_executable("store")
    assert exe2 == "ms-windows-store:"


def test_tesseract_ocr_path_configuration():
    """Tesseract OCR path is explicitly set on pytesseract from Settings or Windows default."""
    import pytesseract
    from friday.core.config import Settings
    from friday.tools.builtin.screen_ocr import _configure_tesseract

    test_settings = Settings(
        env="testing",
        tesseract_cmd=r"C:\Custom\Tesseract\tesseract.exe",
    )

    with mock.patch("friday.tools.builtin.screen_ocr.get_settings", return_value=test_settings):
        _configure_tesseract()
        assert pytesseract.pytesseract.tesseract_cmd == r"C:\Custom\Tesseract\tesseract.exe"

