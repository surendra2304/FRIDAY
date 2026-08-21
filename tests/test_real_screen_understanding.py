# -*- coding: utf-8 -*-
"""Real hardware manual verification test for Screen Understanding.

Test Type: HARDWARE / LIVE

Captures the live Windows desktop and sends it to the real Google Gemini multimodal vision API
for comprehensive visual analysis (application detection, visible text, UI elements, errors).
"""

import sys
import pytest

# Mark as hardware test (opt-in only via pytest -m hardware)
pytestmark = [pytest.mark.hardware, pytest.mark.live]

from friday.core.config import get_settings
from friday.core.logging import setup_logging
from friday.auth.credential_pool import credential_pool
from friday.vision.windows_screen import WindowsScreenCaptureProvider
from friday.vision.gemini_vision import GeminiVisionProvider
from friday.vision.screen_analyzer import ScreenAnalyzer
from friday.tools.builtin.screen_snapshot import ScreenSnapshotTool


def test_hardware_screen_understanding():
    """Verify live Windows desktop capture and Gemini multimodal analysis."""
    if sys.platform != "win32":
        pytest.skip("Windows screen understanding requires Win32 platform.")

    settings = get_settings()
    api_key = credential_pool.get_active_key() or settings.gemini_api_key or settings.llm_api_key
    if not api_key:
        pytest.skip("No real Gemini API key configured in environment. Skipping live screen understanding.")

    cap_prov = WindowsScreenCaptureProvider()
    vis_prov = GeminiVisionProvider(credential_pool=credential_pool, model=settings.vision_model)
    analyzer = ScreenAnalyzer(capture_provider=cap_prov, vision_provider=vis_prov)

    # 1. Ask general screen query
    ctx = analyzer.analyze_current_screen(display="primary", user_query="What is currently on my screen?")
    assert ctx.is_error is False, f"Visual analysis failed: {ctx.error_message}"
    assert len(ctx.summary) > 20, "Summary must contain detailed visual observation"

    # 2. Test via SAFE Tool get_screen_snapshot with query
    tool = ScreenSnapshotTool(capture_provider=cap_prov, vision_provider=vis_prov)
    res = tool.execute(display="primary", query="Summarize active windows")
    assert res.is_error is False
    assert "Screen Snapshot" in res.content
