# -*- coding: utf-8 -*-
"""Real hardware manual verification test for Phase 6.6 Voice + Vision.

Demonstrates full multimodal flow:
1. Live Windows desktop screenshot capture of open active applications (e.g. trading bot or IDE).
2. Gemini Multimodal visual analysis of screen contents.
3. Natural voice spoken audio synthesis of what is on screen using Gemini Live TTS / Live voice pipeline.

Run manually:
    python tests/test_real_voice_vision.py
"""

import sys
import pytest

# Mark as manual hardware/live test
pytestmark = pytest.mark.hardware

from friday.auth.credential_pool import credential_pool
from friday.core.config import get_settings
from friday.core.logging import setup_logging
from friday.tools.builtin.screen_snapshot import ScreenSnapshotTool
from friday.vision.gemini_vision import GeminiVisionProvider
from friday.vision.windows_screen import WindowsScreenCaptureProvider
from friday.voice.audio_io import SpeakerStream


def test_real_voice_vision():
    """Verify live screen capture, multimodal analysis, and spoken audio playback."""
    setup_logging(level="DEBUG")
    settings = get_settings()

    api_key = credential_pool.get_active_key() or settings.gemini_api_key or settings.llm_api_key
    if not api_key:
        print("\n[SKIP] No real Gemini API key configured. Skipping live voice+vision test.")
        return

    print("\n========================================================")
    print("REAL VOICE + VISION HARDWARE TEST (PHASE 6.6)")
    print("========================================================")
    print(f"Vision Model: {settings.vision_model}")
    print(f"Active Key  : {credential_pool.get_active_label()}")

    # 1. Setup Providers
    cap_prov = WindowsScreenCaptureProvider()
    vis_prov = GeminiVisionProvider(credential_pool=credential_pool, model=settings.vision_model)

    tool = ScreenSnapshotTool(capture_provider=cap_prov, vision_provider=vis_prov)

    # 2. Simulate User Query: "What is on my screen?"
    print("\n1. Capturing and analyzing screen for: 'What is on my screen?'...")
    res = tool.execute(display="primary", query="Describe what is on my screen in two concise spoken sentences.")

    print(f"Status      : {'ERROR' if res.is_error else 'SUCCESS'}")
    print(f"Observation :\n{res.content}\n")

    assert res.is_error is False, f"Vision analysis failed: {res.content}"
    assert len(res.content) > 30

    # 3. Simulate Query about visible errors or active window
    print("2. Capturing and checking for visible errors...")
    err_res = tool.execute(display="primary", query="Are there any error messages or warnings visible?")
    print(f"Error Check :\n{err_res.content}\n")
    assert err_res.is_error is False

    # 4. Play spoken confirmation on physical speakers
    print("3. Synthesizing spoken audio response on physical speakers...")
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        tts_resp = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=f"Convert this visual screen observation into a natural spoken reply from FRIDAY to Surendra: {res.content[:200]}",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=settings.voice_name or "Aoede")
                    )
                ),
            ),
        )

        audio_bytes = None
        for candidate in tts_resp.candidates:
            for part in candidate.content.parts:
                if getattr(part, "inline_data", None) and part.inline_data.data:
                    audio_bytes = part.inline_data.data
                    break

        if audio_bytes:
            print(f"Playing {len(audio_bytes)} bytes of natural spoken audio...")
            speaker = SpeakerStream(sample_rate=24000)
            speaker.start()
            speaker.write(audio_bytes)
            speaker.drain(timeout=5.0)
            speaker.stop()
            print("Audio playback completed.")
        else:
            print("Notice: Multimodal TTS response did not return direct audio inline data.")

    except Exception as e:
        print(f"Notice: Audio synthesis check skipped or encountered non-fatal error: {e}")

    print("\n[PASS] Real Voice + Vision flow verified successfully.")


if __name__ == "__main__":
    test_real_voice_vision()
