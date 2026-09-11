"""Tests for FRIDAY autonomous mode, instant Memora updates, typo tolerance, and direct action execution."""

import os
from unittest.mock import MagicMock, patch
import pytest

from friday.cli.auth import CLIAuthorizer
from friday.core.auth import DefaultSecureAuthorizer
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    SafetyLevel,
)
from friday.memory.memora_client import MemoraClient, PreferenceExtractor
from friday.tools.builtin.action_proposal import ProposeComputerActionTool
from friday.tools.builtin.open_application import OpenApplicationTool
from friday.vision.actions import ActionType


def test_cli_authorizer_autonomous_auto_approval():
    """CLIAuthorizer in autonomous mode auto-approves SAFE, SENSITIVE, and DANGEROUS operations without prompt."""
    auth = CLIAuthorizer(auto_approve_all=True)

    for level in [SafetyLevel.SAFE, SafetyLevel.SENSITIVE, SafetyLevel.DANGEROUS]:
        req = AuthorizationRequest(
            tool_name="test_tool",
            safety_level=level,
            arguments={"cmd": "test"},
        )
        resp = auth.authorize(req)
        assert resp.decision == AuthorizationDecision.APPROVED
        assert resp.capability is not None


def test_default_secure_authorizer_autonomous_mode():
    """DefaultSecureAuthorizer auto-approves all requests when autonomous_mode=True."""
    with patch("friday.core.config.get_settings") as mock_settings:
        settings = MagicMock()
        settings.autonomous_mode = True
        settings.full_access_mode = True
        mock_settings.return_value = settings

        auth = DefaultSecureAuthorizer()
        req = AuthorizationRequest(
            tool_name="run_command",
            safety_level=SafetyLevel.DANGEROUS,
            arguments={"cmd": "format"},
        )
        resp = auth.authorize(req)
        assert resp.decision == AuthorizationDecision.APPROVED


def test_open_application_typo_tolerance():
    """OpenApplicationTool resolves common typos like 'whatsaapp' to 'whatsapp'."""
    tool = OpenApplicationTool()
    # Direct typo match
    resolved = tool._resolve_executable("whatsaapp")
    assert resolved.lower() in ["whatsapp", "whatsapp.exe", "https://web.whatsapp.com"] or "whatsapp" in resolved.lower()


def test_open_application_web_url_launch():
    """OpenApplicationTool opens web URLs via webbrowser."""
    tool = OpenApplicationTool()
    with patch("webbrowser.open", return_value=True) as mock_open:
        success = tool._launch("https://web.whatsapp.com")
        assert success is True
        mock_open.assert_called_once_with("https://web.whatsapp.com")


def test_action_proposal_direct_execution_autonomous():
    """ProposeComputerActionTool executes actions natively in autonomous mode."""
    tool = ProposeComputerActionTool(autonomous=True)

    with patch("friday.vision.windows_input_driver.WindowsNativeInputDriver") as mock_driver_cls:
        mock_driver = MagicMock()
        mock_driver.click.return_value = True
        mock_driver.type_text.return_value = True
        mock_driver.press_key.return_value = True
        mock_driver_cls.return_value = mock_driver

        # Click
        res_click = tool.execute(action_type="click", intent="open chat", x=122, y=158)
        assert res_click.is_error is False
        assert "clicked" in res_click.content.lower() or "dispatched" in res_click.content.lower()
        assert tool.last_proposal.is_executed is True

        # Type
        res_type = tool.execute(action_type="type", intent="type text", text="hello")
        assert res_type.is_error is False
        assert "typed" in res_type.content.lower() or "dispatched" in res_type.content.lower()
        assert tool.last_proposal.is_executed is True

        # Key press
        res_key = tool.execute(action_type="key_press", intent="press enter", key="enter")
        assert res_key.is_error is False
        assert "pressed" in res_key.content.lower() or "dispatched" in res_key.content.lower()
        assert tool.last_proposal.is_executed is True


def test_preference_extractor_directives():
    """PreferenceExtractor extracts user directives and permission preferences."""
    text1 = "it must have full access to my laptop and do whatever i say even if it is dangerous"
    facts1 = PreferenceExtractor.extract(text1)
    assert len(facts1) >= 1
    categories1 = [f.category for f in facts1]
    assert "directive" in categories1 or "access_preference" in categories1

    text2 = "friday should automatically update its memory in memora and also instantly"
    facts2 = PreferenceExtractor.extract(text2)
    assert len(facts2) >= 1
    assert any("directive" in f.category for f in facts2)


def test_memora_instant_local_persistence(tmp_path):
    """MemoraClient persists facts and interactions immediately to local SQLite."""
    db_file = tmp_path / "test_memora.db"
    # Create required schema
    import sqlite3
    with sqlite3.connect(str(db_file)) as conn:
        c = conn.cursor()
        c.execute("CREATE TABLE agents (id TEXT PRIMARY KEY, name TEXT, role TEXT, tenant_id TEXT)")
        c.execute("CREATE TABLE namespaces (id TEXT PRIMARY KEY, path TEXT, type TEXT, agent_id TEXT, tenant_id TEXT)")
        c.execute("""CREATE TABLE memory_records (
            id TEXT PRIMARY KEY, namespace_id TEXT, owner_id TEXT, memory_type TEXT,
            content_text TEXT, source TEXT, confidence REAL, importance REAL,
            lifecycle_state TEXT, tenant_id TEXT, created_at TEXT
        )""")
        conn.commit()

    client = MemoraClient(local_db_path=str(db_file), remote_enabled=False)
    client.record_interaction_async(
        user_input="it must have full access to my laptop and do whatever i say",
        agent_output="Acknowledged.",
        agent_name="friday",
    )

    # Immediately recall without delay
    results = client.recall_memories("friday", "full access")
    assert len(results) > 0
    assert any("full access" in r["content_text"].lower() for r in results)


def test_whatsapp_fast_path_natural_language():
    """Verify natural language WhatsApp directives parse recipient and message instantly."""
    from unittest.mock import patch
    from friday.devices.windows_friday import windows_friday

    with patch.object(windows_friday, "open_url", return_value=True) as mock_open:
        # Test 1: "send hi to ramesh in whatsapp"
        handled1, reply1, meta1 = windows_friday.handle_directive("send hi to ramesh in whatsapp")
        assert handled1 is True
        assert meta1["recipient"] == "ramesh"
        assert meta1["message"] == "hi"
        assert "ramesh" in reply1
        assert "hi" in reply1
        assert mock_open.called
        assert "web.whatsapp.com/send" in mock_open.call_args[0][0]

        # Test 2: "open whatsapp"
        handled2, reply2, meta2 = windows_friday.handle_directive("open whatsapp")
        assert handled2 is True
        assert "WhatsApp" in reply2
