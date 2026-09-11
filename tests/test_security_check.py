# -*- coding: utf-8 -*-
"""Unit tests for security_check.py secret patterns and detection logic."""

import pytest
from security_check import SECRET_PATTERNS


def test_secret_patterns_compilation():
    """Verify all regex patterns compile without error."""
    assert len(SECRET_PATTERNS) >= 5
    for pattern, description in SECRET_PATTERNS:
        assert hasattr(pattern, "search")
        assert isinstance(description, str)


def test_openai_key_detection():
    """Verify legacy and modern OpenAI secret key patterns are detected."""
    openai_pattern = None
    for pattern, desc in SECRET_PATTERNS:
        if "OpenAI" in desc:
            openai_pattern = pattern
            break
    assert openai_pattern is not None

    legacy_key = "sk-" + "A" * 48
    proj_key = "sk-proj-" + "B" * 48

    assert openai_pattern.search(legacy_key) is not None
    assert openai_pattern.search(f"key = '{proj_key}'") is not None
    assert openai_pattern.search("not_a_key_sk-short") is None


def test_gemini_key_detection():
    """Verify Gemini API key format is detected."""
    gemini_pattern = None
    for pattern, desc in SECRET_PATTERNS:
        if "Gemini" in desc:
            gemini_pattern = pattern
            break
    assert gemini_pattern is not None

    sample_key = "AIzaSy" + "A" * 33
    assert gemini_pattern.search(sample_key) is not None
    assert gemini_pattern.search("AIzaShort") is None


def test_github_token_detection():
    """Verify GitHub personal access tokens are detected."""
    gh_pattern = None
    for pattern, desc in SECRET_PATTERNS:
        if "GitHub" in desc:
            gh_pattern = pattern
            break
    assert gh_pattern is not None

    token = "ghp_" + "C" * 36
    assert gh_pattern.search(token) is not None
    assert gh_pattern.search("ghp_short") is None
