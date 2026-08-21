# -*- coding: utf-8 -*-
"""Real hardware manual verification test for Voice + Vision.

Test Type: HARDWARE / LIVE

Demonstrates full multimodal flow:
1. Live Windows desktop screenshot capture.
2. Gemini Multimodal visual analysis of screen contents.
3. Natural voice spoken audio synthesis of what is on screen using Gemini TTS.
"""

import sys
import pytest

# Mark as hardware test (opt-in only via pytest -m hardware)
pytestmark = [pytest.mark.hardware, pytest.mark.live]

from friday.auth.credential_pool import credential_pool
from friday.core.config import get_settings
from friday.tools.builtin.screen_snapshot import ScreenSnapshotTool
from friday.vision.gemini_vision import GeminiVisionProvider
from friday.vision.windows_screen import WindowsScreenCaptureProvider
from friday.voice.audio_io import SpeakerStream


def test_hardware_voice_vision():
    """Verify live screen capture, multimodal analysis, and spoken audio playback."""
    if sys.platform != "win32":
        pytest.skip("Windows voice-vision requires Win32 platform.")

    settings = get_settings()
    api_key = credential_pool.get_active_key() or settings.gemini_api_key or settings.llm_api_key
    if not api_key:
        pytest.skip("No real Gemini API key configured in environment. Skipping live voice+vision test.")

    cap_prov = WindowsScreenCaptureProvider()
    vis_prov = GeminiVisionProvider(credential_pool=credential_pool, model=settings.vision_model)
    tool = ScreenSnapshotTool(capture_provider=cap_prov, vision_provider=vis_prov)

    res = tool.execute(display="primary", query="Describe what is on my screen in two concise spoken sentences.")
    assert res.is_error is False, f"Vision analysis failed: {res.content}"
    assert len(res.content) > 20
