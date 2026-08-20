# -*- coding: utf-8 -*-
"""Real hardware manual verification test for Phase 6.3 Screen Understanding.

Captures the live Windows desktop and sends it to the real Google Gemini multimodal vision API
for comprehensive visual analysis (application detection, visible text, UI elements, errors).

Run manually:
    python tests/test_real_screen_understanding.py
"""

import sys
import pytest

# Mark as manual hardware/live test
pytestmark = pytest.mark.hardware

from friday.core.config import get_settings
from friday.core.logging import setup_logging
from friday.auth.credential_pool import credential_pool
from friday.vision.windows_screen import WindowsScreenCaptureProvider
from friday.vision.gemini_vision import GeminiVisionProvider
from friday.vision.screen_analyzer import ScreenAnalyzer
from friday.tools.builtin.screen_snapshot import ScreenSnapshotTool


def test_real_screen_understanding():
    """Verify live Windows desktop capture and Gemini multimodal analysis."""
    setup_logging(level="DEBUG")
    settings = get_settings()

    api_key = credential_pool.get_active_key() or settings.gemini_api_key or settings.llm_api_key
    if not api_key:
        print("\n[SKIP] No real Gemini API key configured. Skipping live screen understanding test.")
        return

    print("\n========================================================")
    print("REAL SCREEN UNDERSTANDING MANUAL TEST (PHASE 6.3)")
    print("========================================================")
    print(f"Active Vision Model: {settings.vision_model}")
    print(f"Active Credential  : {credential_pool.get_active_label()}")

    cap_prov = WindowsScreenCaptureProvider()
    vis_prov = GeminiVisionProvider(credential_pool=credential_pool, model=settings.vision_model)

    analyzer = ScreenAnalyzer(capture_provider=cap_prov, vision_provider=vis_prov)

    # 1. Ask general screen query
    print("\n1. Requesting visual analysis: 'What is currently on my screen?'...")
    ctx = analyzer.analyze_current_screen(display="primary", user_query="What is currently on my screen?")

    print(f"Status        : {'ERROR' if ctx.is_error else 'SUCCESS'}")
    print(f"Dimensions    : {ctx.width}x{ctx.height}")
    print(f"Analysis Text :\n{ctx.summary}\n")

    assert ctx.is_error is False, f"Visual analysis failed: {ctx.error_message}"
    assert len(ctx.summary) > 20, "Summary must contain detailed visual observation"

    # 2. Test via SAFE Tool get_screen_snapshot with query
    print("2. Testing SAFE Tool get_screen_snapshot with query='Summarize active windows'...")
    tool = ScreenSnapshotTool(capture_provider=cap_prov, vision_provider=vis_prov)
    res = tool.execute(display="primary", query="Summarize active windows")

    print(f"Tool Error    : {res.is_error}")
    print(f"Tool Content  :\n{res.content}")

    assert res.is_error is False
    assert "Screen Snapshot" in res.content

    print("\n[PASS] Real Screen Understanding verified successfully.")


if __name__ == "__main__":
    test_real_screen_understanding()
