"""Unit tests for Behavioral Struggle Detection & Proactive Suggestion Engine."""

import pytest

from friday.awareness.struggle_detector import (
    AppCategory,
    StruggleAnalysis,
    StruggleDetector,
    classify_app,
)
from friday.awareness.suggestion_engine import (
    SuggestionEngine,
    SuggestionType,
)


def test_classify_app() -> None:
    assert classify_app("Code.exe", "main.py - Visual Studio Code") == AppCategory.CODE_EDITOR
    assert classify_app("Cursor.exe", "test.py - Cursor") == AppCategory.CODE_EDITOR
    assert classify_app("WindowsTerminal.exe", "PowerShell 7.4") == AppCategory.TERMINAL
    assert classify_app("chrome.exe", "Google Chrome - GitHub") == AppCategory.BROWSER
    assert classify_app("notepad.exe", "notes.txt") == AppCategory.GENERAL


def test_scan_errors() -> None:
    detector = StruggleDetector()

    traceback_sample = (
        "Traceback (most recent call last):\n"
        "  File 'main.py', line 42, in <module>\n"
        "    raise FileNotFoundError('config.yaml not found')\n"
        "FileNotFoundError: config.yaml not found"
    )
    has_err, summary = detector.scan_errors(traceback_sample)
    assert has_err is True
    assert "Python Traceback" in summary

    syntax_sample = "SyntaxError: invalid syntax in line 12"
    has_err2, summary2 = detector.scan_errors(syntax_sample)
    assert has_err2 is True
    assert "Syntax" in summary2

    clean_text = "Tests passed: 25 succeeded, 0 failed."
    has_err3, _ = detector.scan_errors(clean_text)
    assert has_err3 is False


def test_struggle_detector_evaluation() -> None:
    # Set grace_s=0 so test triggers immediately upon error threshold
    detector = StruggleDetector(grace_s=0.0, cooldown_s=10.0, struggle_threshold=0.3)

    err_text = "Traceback (most recent call last):\n  File 'test.py', line 1\nZeroDivisionError: division by zero"

    # Push 3 snapshots with error
    detector.evaluate(err_text, "Code.exe", "test.py - VS Code", timestamp=100.0)
    detector.evaluate(err_text, "Code.exe", "test.py - VS Code", timestamp=105.0)
    analysis = detector.evaluate(err_text, "Code.exe", "test.py - VS Code", timestamp=110.0)

    assert analysis is not None
    assert analysis.is_struggling is True
    assert analysis.app_category == AppCategory.CODE_EDITOR
    assert analysis.composite_score >= 0.3
    assert any(s.name == "persistent_errors" for s in analysis.signals)

    # Within cooldown (cooldown_s=10), immediate re-evaluation returns None
    cooldown_eval = detector.evaluate(err_text, "Code.exe", "test.py - VS Code", timestamp=112.0)
    assert cooldown_eval is None


def test_suggestion_engine_rate_limiting_and_dedup() -> None:
    engine = SuggestionEngine(default_rate_limit_s=30.0)

    struggle = StruggleAnalysis(
        is_struggling=True,
        composite_score=0.75,
        signals=[],
        app_category=AppCategory.CODE_EDITOR,
        app_name="Visual Studio Code",
        window_title="agent.py",
        duration_ms=15000.0,
        error_summary="Python Traceback: TypeError: unsupported operand",
    )

    s1 = engine.evaluate_struggle(struggle, timestamp=100.0)
    assert s1 is not None
    assert s1.type == SuggestionType.ERROR
    assert "Visual Studio Code" in s1.title

    # Immediate duplicate within rate limit is suppressed
    s2 = engine.evaluate_struggle(struggle, timestamp=105.0)
    assert s2 is None

    # After rate limit expires (15s for ERROR), same exact content is deduped
    s3 = engine.evaluate_struggle(struggle, timestamp=120.0)
    assert s3 is None  # deduped by hash

    # Break suggestion after 90+ minutes
    break_s = engine.evaluate_break(continuous_active_minutes=95.0, timestamp=200.0)
    assert break_s is not None
    assert break_s.type == SuggestionType.BREAK
