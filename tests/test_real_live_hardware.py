"""
Real hardware test for FRIDAY Gemini Live Voice Session.
This script tests:
1. Real Gemini Live API WebSocket connection
2. Real microphone input via PyAudio
3. Real streamed audio output via PyAudio
4. Real VAD (Voice Activity Detection)
5. Real barge-in (interruption)

Run this manually with your real FRIDAY_GEMINI_API_KEY exported in your environment.
"""

import pytest
pytestmark = pytest.mark.skip(reason="Manual hardware test requiring real API keys and audio devices")

import asyncio
import os
import sys

from pydantic import ValidationError

from friday.core.config import get_settings
from friday.core.logging import setup_logging, get_logger
from friday.agent import FridayAgent
from friday.voice.gemini_live_session import GeminiLiveVoiceSession

logger = get_logger("test_live_hardware")

async def test_live_hardware():
    settings = get_settings()
    # Force live model for testing
    settings.voice_live_model = "gemini-3.1-flash-live-preview"
    
    setup_logging(level="DEBUG")
    
    print("==================================================")
    print("REAL GEMINI LIVE HARDWARE TEST")
    print("==================================================")
    
    if not settings.gemini_api_key:
        print("ERROR: FRIDAY_GEMINI_API_KEY must be set in your .env or environment.")
        sys.exit(1)

    print("Initializing FridayAgent...")
    agent = FridayAgent(settings=settings)
    
    print("Initializing GeminiLiveVoiceSession...")
    session = GeminiLiveVoiceSession(agent=agent)
    
    print("\nStarting live session...")
    print("Speak into your microphone! Try asking 'What time is it?' to test tools.")
    print("Try interrupting it while it's speaking to test barge-in.")
    print("Press Ctrl+C to terminate the test.\n")
    
    stop_event = asyncio.Event()
    duration = os.environ.get("HARDWARE_TEST_DURATION")
    if duration:
        try:
            dur_secs = float(duration)
            print(f"Running automated hardware check for {dur_secs}s...")
            asyncio.create_task(asyncio.sleep(dur_secs)).add_done_callback(lambda _: stop_event.set())
        except ValueError:
            pass

    try:
        await session.run_live_loop(stop_event=stop_event)
    except KeyboardInterrupt:
        print("\nTest terminated by user.")
    except Exception as e:
        print(f"\nSession error: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(test_live_hardware())
    except KeyboardInterrupt:
        pass
