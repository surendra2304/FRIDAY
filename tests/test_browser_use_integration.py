"""Tests for Browser Use Integration and Browser Safety Guardrails."""

import pytest
from friday.integrations.browser_use.executor import BrowserUseExecutor
from friday.integrations.browser_use.safety import BrowserSafetyGuard, BrowserSafetyPolicy
from friday.tools.builtin.browser_tool import BrowserAutomationTool
from friday.tools.registry import ToolRegistry
from friday.core.types import SafetyLevel


def test_browser_safety_guard_blocks_restricted_domains():
    policy = BrowserSafetyPolicy(blocked_domains=["bank.com", "onion"])
    guard = BrowserSafetyGuard(policy=policy)

    is_safe, msg = guard.validate_url("https://secure.bank.com/login")
    assert not is_safe
    assert "blocked" in msg.lower()

    is_safe_onion, _ = guard.validate_url("http://testsite.onion")
    assert not is_safe_onion

    is_safe_normal, _ = guard.validate_url("https://wikipedia.org/wiki/Python")
    assert is_safe_normal


def test_browser_safety_guard_allowlist():
    policy = BrowserSafetyPolicy(allowed_domains=["github.com", "python.org"])
    guard = BrowserSafetyGuard(policy=policy)

    is_safe, _ = guard.validate_url("https://github.com/microsoft/JARVIS")
    assert is_safe

    is_unauthorized, msg = guard.validate_url("https://random-unauthorized-site.com")
    assert not is_unauthorized
    assert "allowed domains" in msg.lower()


def test_browser_safety_action_sanitization():
    policy = BrowserSafetyPolicy(allow_downloads=False, allow_file_uploads=False)
    guard = BrowserSafetyGuard(policy=policy)

    # Downloads blocked
    ok, msg, level = guard.sanitize_action("download", {})
    assert not ok
    assert level == SafetyLevel.DANGEROUS

    # Uploads blocked
    ok, msg, level = guard.sanitize_action("upload_file", {})
    assert not ok
    assert level == SafetyLevel.SENSITIVE

    # Normal navigation approved
    ok, msg, level = guard.sanitize_action("navigate", {})
    assert ok
    assert level == SafetyLevel.SAFE


def test_browser_use_executor_availability():
    executor = BrowserUseExecutor()
    # On this machine, playwright is installed
    assert executor.has_playwright_package is True
    # browser_use package is optional
    assert isinstance(executor.has_browser_use_package, bool)


def test_browser_use_executor_blocked_url():
    policy = BrowserSafetyPolicy(blocked_domains=["forbidden.com"])
    executor = BrowserUseExecutor(safety_policy=policy)

    res = executor.execute({"action": "navigate", "url": "https://forbidden.com/secret"})
    assert not res.success
    assert "Safety Block" in str(res.error)


def test_browser_automation_tool_registered_in_registry():
    tool = BrowserAutomationTool()
    assert tool.name == "browser_action"
    assert tool.safety_level == SafetyLevel.SAFE

    registry = ToolRegistry()
    registry.register(tool)
    assert registry.get("browser_action") is not None
