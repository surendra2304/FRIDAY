"""Comprehensive diagnostic suite for real Gemini Live Voice pipeline.

Runs:
A. Connection test (WebSocket handshake)
B. Text-to-Live-Audio test (Proves Live response stream, TTS synthesis & speaker queue)
C. Microphone Capture Metrics (5s audio capture with RMS energy measurement)
D. Device Selection & Audio Hardware Diagnostics
E. End-to-end Live interactive session with live metric telemetry
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Ensure local project environment is loaded
load_dotenv(Path('.env'), override=True)

from friday.core.config import get_settings
from friday.core.logging import setup_logging, get_logger
from friday.voice.audio_io import MicrophoneStream, SpeakerStream, compute_pcm_rms, get_audio_diagnostics
from friday.voice.gemini_live_session import GeminiLiveVoiceSession, LiveSessionState
from friday.agent import FridayAgent

logger = get_logger("diagnose_real_live_voice")


async def run_diagnostics():
    setup_logging(level="DEBUG")
    settings = get_settings()
    
    print("\n" + "=" * 60)
    print("      FRIDAY REAL GEMINI LIVE VOICE PIPELINE DIAGNOSTIC     ")
    print("=" * 60)

    # 1. Hardware & Audio Device Diagnostics
    print("\n[STEP 1: AUDIO DEVICE DIAGNOSTICS]")
    diag = get_audio_diagnostics()
    print(f"  Driver available : {diag.get('driver_available')}")
    print(f"  Device count     : {diag.get('device_count')}")
    print(f"  Default Input ID : {diag.get('default_input')}")
    print(f"  Default Output ID: {diag.get('default_output')}")
    for d in diag.get("devices", []):
        if d.get("is_default_input"):
            print(f"  -> ACTIVE INPUT : [{d['index']}] {d['name']} (Sample Rate: {d['default_samplerate']})")
        if d.get("is_default_output"):
            print(f"  -> ACTIVE OUTPUT: [{d['index']}] {d['name']} (Sample Rate: {d['default_samplerate']})")

    # 2. Microphone Capture Isolation Test
    print("\n[STEP 2: MICROPHONE CAPTURE ISOLATION TEST (5 SECONDS)]")
    print("  >>> PLEASE SPEAK INTO YOUR MICROPHONE NOW (Say 'Testing one two three')... <<<")
    
    mic = MicrophoneStream(sample_rate=16000, chunk_duration_ms=40)
    loop = asyncio.get_running_loop()
    mic.start(loop=loop)
    
    chunks = 0
    non_silent = 0
    total_bytes = 0
    max_rms = 0.0
    
    t_end = time.time() + 5.0
    while time.time() < t_end:
        chunk = await mic.read_chunk()
        if chunk:
            chunks += 1
            total_bytes += len(chunk)
            rms = compute_pcm_rms(chunk)
            if rms > max_rms:
                max_rms = rms
            if rms > 150.0:  # Voice activity threshold
                non_silent += 1
        else:
            await asyncio.sleep(0.01)
            
    mic.stop()
    print(f"  Chunks captured     : {chunks}")
    print(f"  Total audio bytes   : {total_bytes}")
    print(f"  Peak RMS Energy     : {max_rms:.2f}")
    print(f"  Non-silent chunks   : {non_silent}")
    mic_pass = chunks > 50 and non_silent > 5
    print(f"  MICROPHONE STATUS   : {'PASS (Voice Detected)' if mic_pass else 'FAIL / SILENCE DETECTED'}")

    # 3. Live Text-to-Audio Output Isolation Test
    print("\n[STEP 3: LIVE TEXT-TO-AUDIO & SPEAKER ISOLATION TEST]")
    print("  Sending text prompt 'Say hello to me' directly to Gemini Live WebSocket...")
    
    from google import genai
    from google.genai import types as genai_types
    
    api_key = settings.gemini_api_key or os.environ.get("FRIDAY_GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    spk = SpeakerStream(sample_rate=24000)
    spk.start()
    
    live_config = genai_types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=genai_types.SpeechConfig(
            voice_config=genai_types.VoiceConfig(
                prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name=settings.voice_name)
            )
        ),
        system_instruction=genai_types.Content(parts=[genai_types.Part.from_text(text="You are FRIDAY. Be concise.")]),
    )
    
    audio_received_bytes = 0
    try:
        async with client.aio.live.connect(model=settings.voice_live_model, config=live_config) as session:
            print("  Connected to Live WebSocket. Dispatching prompt...")
            await session.send_client_content(
                turns=genai_types.Content(
                    role="user",
                    parts=[genai_types.Part.from_text(text="Say hello to me in one short sentence.")]
                ),
                turn_complete=True
            )
            
            async for msg in session.receive():
                server_content = getattr(msg, "server_content", None)
                if server_content:
                    model_turn = getattr(server_content, "model_turn", None)
                    if model_turn and getattr(model_turn, "parts", None):
                        for part in model_turn.parts:
                            inline_data = getattr(part, "inline_data", None)
                            if inline_data and getattr(inline_data, "data", None):
                                audio_received_bytes += len(inline_data.data)
                                spk.play_chunk(inline_data.data)
                    if getattr(server_content, "turn_complete", False):
                        break
        # Allow audio playback buffer to drain
        await asyncio.sleep(2.0)
    finally:
        spk.stop()
        spk.close()

    print(f"  Live Audio Bytes Received: {audio_received_bytes}")
    text_to_audio_pass = audio_received_bytes > 5000
    print(f"  TEXT->LIVE->SPEAKER      : {'PASS' if text_to_audio_pass else 'FAIL'}")

    # 4. Live Full-Duplex Voice Session Test
    print("\n[STEP 4: LIVE BIDIRECTIONAL FULL-DUPLEX VOICE SESSION (15 SECONDS)]")
    print("  >>> Speak to FRIDAY now! Try saying: 'Hello FRIDAY, what time is it?' <<<")
    
    agent = FridayAgent(settings=settings)
    live_session = GeminiLiveVoiceSession(agent=agent)
    stop_event = asyncio.Event()
    
    def on_turn(user_tx, agent_tx):
        print(f"\n  [TRANSCRIPTION] USER : {user_tx}")
        print(f"  [TRANSCRIPTION] AGENT: {agent_tx}\n")

    asyncio.create_task(asyncio.sleep(15.0)).add_done_callback(lambda _: stop_event.set())
    try:
        await live_session.run_live_loop(on_turn_complete=on_turn, stop_event=stop_event)
    except Exception as e:
        print(f"  Live Session Error: {e}")

    print("\n" + "=" * 60)
    print("                 DIAGNOSTIC SUMMARY                   ")
    print("=" * 60)
    print(f"  MICROPHONE HARDWARE CAPTURE: {'PASS' if mic_pass else 'FAIL'}")
    print(f"  LIVE TEXT-TO-SPEECH OUTPUT : {'PASS' if text_to_audio_pass else 'FAIL'}")
    print(f"  LIVE MODEL                 : {settings.voice_live_model}")
    print(f"  AUDIO INPUT SAMPLE RATE    : 16000 Hz (16-bit Mono PCM)")
    print(f"  AUDIO OUTPUT SAMPLE RATE   : 24000 Hz (16-bit Mono PCM)")
    print(f"  USER INTERRUPTIONS         : {live_session.user_interruptions}")
    print(f"  SERVER VAD INTERRUPTIONS   : {live_session.server_interruptions}")
    print(f"  SPEAKER ECHO INTERRUPTIONS : {live_session.speaker_playback_interruptions}")
    print(f"  FALSE INTERRUPTIONS        : {live_session.false_interruptions}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(run_diagnostics())
    except KeyboardInterrupt:
        print("\nDiagnostic interrupted by user.")
