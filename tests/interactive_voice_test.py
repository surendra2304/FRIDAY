# -*- coding: utf-8 -*-
"""Standalone interactive Gemini Live voice diagnostic.

Debugs the Gemini Live connection end-to-end WITHOUT running the full
FridayAgent. Only the voice pipeline is exercised:

  1. Resolves the first active Gemini key from the credential pool.
  2. Verifies real microphone and speaker streams.
  3. Connects to the Gemini Live WebSocket (raw errors are printed verbatim).
  4. Runs a timed bidirectional audio session (speak and be heard).
  5. Prints a session summary: interruptions and turn latency.

Usage:
    python tests/interactive_voice_test.py
    python tests/interactive_voice_test.py --model gemini-1.5-flash-latest
    python tests/interactive_voice_test.py --duration 60

This script performs REAL hardware + REAL network I/O. It is a diagnostic
tool, not part of the automated test suite (do not collect with pytest:
functions are not test_-prefixed on purpose).
"""

import argparse
import asyncio
import statistics
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

# Allow running directly from a source checkout without installation
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from friday.auth.credential_pool import credential_pool, GeminiCredentialPool  # noqa: E402
from friday.voice.audio_io import MicrophoneStream, SpeakerStream  # noqa: E402
from friday.voice.gemini_live_session import GeminiLiveVoiceSession  # noqa: E402

DEFAULT_MODEL = "gemini-2.0-flash-exp"
SAMPLE_RATE_IN = 16000
SAMPLE_RATE_OUT = 24000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive Gemini Live voice diagnostic (voice pipeline only)"
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Gemini Live model name (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="Live session duration in seconds (default: 30)",
    )
    return parser.parse_args()


def resolve_api_key() -> str:
    """Take the first ACTIVE (healthy) Gemini key from the credential pool."""
    try:
        key = credential_pool.get_active_key()
        label = credential_pool.get_active_label()
    except Exception as e:
        print("\n[FAIL] Credential pool has no healthy Gemini key.")
        print(f"RAW ERROR: {e!r}")
        sys.exit(2)
    if not key:
        print("\n[FAIL] Credential pool returned an empty key.")
        sys.exit(2)
    print(f"[OK] Gemini key resolved from pool: {label} (****{key[-4:]})")
    return key


def verify_audio_devices() -> None:
    """Start, verify, and stop mic/speaker so the session can own them."""
    print("\n--- Audio device check ---")
    mic = MicrophoneStream(sample_rate=SAMPLE_RATE_IN)
    spk = SpeakerStream(sample_rate=SAMPLE_RATE_OUT)
    mic.start()
    spk.start()
    problems = []
    if not mic.is_active or mic.error:
        problems.append(f"MICROPHONE: {mic.error or 'failed to start'}")
    if not spk.is_active or spk.error:
        problems.append(f"SPEAKER: {spk.error or 'failed to start'}")
    mic.stop()
    spk.close()
    if problems:
        print("\n[FAIL] Audio hardware check failed:")
        for p in problems:
            print(f"  RAW ERROR: {p}")
        sys.exit(3)
    print(f"[OK] Microphone active at {SAMPLE_RATE_IN} Hz, speaker active at {SAMPLE_RATE_OUT} Hz.")


def print_raw_error(exc: BaseException) -> None:
    """Print the EXACT raw error chain from Google, unwrapped and unmasked."""
    print("\n" + "=" * 70)
    print("[FAIL] Gemini Live session failed. RAW error chain (outermost -> root cause):")
    print("=" * 70)
    depth = 0
    current: Optional = exc
    while current is not None:
        prefix = "  " * depth + ("ROOT CAUSE: " if depth else "EXCEPTION: ")
        print(f"{prefix}{type(current).__module__}.{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__ if depth < 10 else None
        depth += 1
    print("\nFull traceback:")
    traceback.print_exception(type(exc), exc, exc.__traceback__)


def main() -> None:
    args = parse_args()
    print("=" * 70)
    print("FRIDAY — Interactive Gemini Live Voice Diagnostic (no agent)")
    print("=" * 70)
    print(f"Model:        {args.model}")
    print(f"Duration:     {args.duration:.0f}s")

    api_key = resolve_api_key()
    verify_audio_devices()

    print("\n--- Connecting to Gemini Live ---")
    # max_retries=0: surface the first raw connection error immediately
    # instead of masking it behind reconnect attempts.
    session = GeminiLiveVoiceSession(
        api_key=api_key,
        model=args.model,
        sample_rate_in=SAMPLE_RATE_IN,
        sample_rate_out=SAMPLE_RATE_OUT,
        max_retries=0,
        credential_pool=credential_pool,
    )
    if session.model != args.model:
        print(f"[WARN] Model normalized to '{session.model}' (input was rejected as non-Live).")

    turn_log = []  # (monotonic_timestamp, user_text, agent_text)

    def on_turn_complete(user_text: str, agent_text: str) -> None:
        turn_log.append((time.perf_counter(), user_text, agent_text))
        print(f"\n[TURN {len(turn_log)}] You: {user_text or '(untranscribed)'}")
        print(f"         FRIDAY: {(agent_text or '(untranscribed)')[:120]}")

    async def run_timed_session() -> None:
        stop = asyncio.Event()

        async def timer() -> None:
            await asyncio.sleep(args.duration)
            print(f"\n--- {args.duration:.0f}s elapsed: closing live session ---")
            stop.set()

        timer_task = asyncio.create_task(timer(), name="diag_timer")
        mic = MicrophoneStream(sample_rate=SAMPLE_RATE_IN)
        spk = SpeakerStream(sample_rate=SAMPLE_RATE_OUT)
        try:
            await session.run_live_loop(
                input_stream=mic,
                output_stream=spk,
                on_turn_complete=on_turn_complete,
                stop_event=stop,
            )
        finally:
            timer_task.cancel()
            mic.stop()
            spk.close()

    started = time.perf_counter()
    try:
        asyncio.run(run_timed_session())
    except KeyboardInterrupt:
        print("\n[interrupted by user]")
    except BaseException as exc:  # noqa: BLE001 - diagnostics must show everything
        print_raw_error(exc)
        sys.exit(4)
    elapsed = time.perf_counter() - started

    print("\n" + "=" * 70)
    print("SESSION SUMMARY")
    print("=" * 70)
    print(f"Requested duration:  {args.duration:.0f}s")
    print(f"Actual duration:     {elapsed:.1f}s")
    print(f"Final state:         {session.state.value}")
    print(f"Resumption handle:   {'yes' if session.resumption_handle else 'no'}")
    print(f"Completed turns:     {len(turn_log)}")

    if len(turn_log) >= 2:
        gaps = [turn_log[i][0] - turn_log[i - 1][0] for i in range(1, len(turn_log))]
        print(f"Inter-turn gap:      avg {statistics.mean(gaps):.2f}s | "
              f"median {statistics.median(gaps):.2f}s | max {max(gaps):.2f}s")
    elif len(turn_log) == 1:
        print("Inter-turn gap:      n/a (only one completed turn)")

    print(f"User interruptions (barge-in):        {session.user_interruptions}")
    print(f"Server interruptions:                 {session.server_interruptions}")
    print(f"Speaker playback interruptions:       {session.speaker_playback_interruptions}")
    print(f"False interruptions (echo/noise):     {session.false_interruptions}")

    if not turn_log and session.user_interruptions == 0:
        print("\n[NOTE] No turns completed. If you spoke, check microphone input level "
              "and VAD sensitivity settings (FRIDAY_VOICE_VAD_*).")


if __name__ == "__main__":
    main()
