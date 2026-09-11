# -*- coding: utf-8 -*-
"""Unit tests for TypeTextTool safety hardening."""

from unittest.mock import patch, MagicMock
import pytest

from friday.core.types import SafetyLevel
from friday.tools.builtin.type_text import TypeTextTool


def test_type_text_safety_level_and_parameters():
    """Verify tool is SENSITIVE and requires window_title."""
    tool = TypeTextTool()
    assert tool.safety_level == SafetyLevel.SENSITIVE
    assert "window_title" in tool.parameters["required"]
    assert "text" in tool.parameters["required"]


def test_type_text_rejects_missing_window_title():
    """Verify missing or empty window_title is rejected."""
    tool = TypeTextTool()
    res = tool.execute(text="hello", window_title="")
    assert res.is_error is True
    assert "window_title is required" in res.content


def test_type_text_aborts_when_target_window_not_found():
    """Verify tool aborts typing if target window cannot be found or focused."""
    tool = TypeTextTool()
    with patch("friday.tools.builtin.type_text._get_send_keys") as mock_send_keys, \
         patch("friday.tools.builtin.type_text._focus_window", return_value=False):
        res = tool.execute(text="sensitive password", window_title="NonexistentApp")
        assert res.is_error is True
        assert "could not be found or focused" in res.content
        mock_send_keys.return_value.assert_not_called()


def test_type_text_sanitizes_output():
    """Verify tool does not echo raw typed payload in successful output."""
    tool = TypeTextTool()
    mock_send = MagicMock()
    with patch("friday.tools.builtin.type_text._get_send_keys", return_value=mock_send), \
         patch("friday.tools.builtin.type_text._focus_window", return_value=True):
        secret_payload = "super_confidential_token_123"
        res = tool.execute(text=secret_payload, window_title="Notepad")
        assert res.is_error is False
        assert secret_payload not in res.content
        assert f"Successfully typed {len(secret_payload)} characters into window 'Notepad'." in res.content
        mock_send.assert_called_once()
