"""Standalone interactive Gemini Live voice diagnostic.

Debugs the Gemini Live connection end-to-end WITHOUT running the full
FridayAgent. Only the voice pipeline is exercised:

  1. Resolves the first active Gemini key from the credential pool.
  2. Verifies real microphone and speaker streams.
  3. Connects to the Gemini Live WebSocket (raw errors are printed verbatim).
  4. Runs an indefinite bidirectional audio session until Ctrl+C.
  5. Prints a session summary: interruptions and turn latency.

Key rotation: if Google denies the connection with a 1008 policy violation
("Your project has been denied access") or a "not supported" error, the
offending key is marked unhealthy in the pool and the connection is retried
with the next active key (up to MAX_KEY_ROTATIONS attempts).

Usage:
    python tests/interactive_voice_test.py
    python tests/interactive_voice_test.py --model gemini-3.1-flash-live-preview

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

# Allow running directly from a source checkout without installation
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from friday.auth.credential_pool import credential_pool
from friday.voice.audio_io import MicrophoneStream, SpeakerStream
from friday.voice.gemini_live_session import GeminiLiveVoiceSession

DEFAULT_MODEL = "gemini-3.1-flash-live-preview"
SAMPLE_RATE_IN = 16000
SAMPLE_RATE_OUT = 24000
MAX_KEY_ROTATIONS = 5
MAX_RECONNECTS = 3

# Error markers that indicate the API KEY (not the model/request) is denied;
# only these trigger key rotation. "quota" covers exhausted-key denials that
# surface as quota errors on the Live endpoint.
_ACCESS_DENIED_MARKERS = ("1008", "denied access", "not supported", "quota")

# Markers for a dropped session (normal closure / timeout) that should be
# retried with the SAME healthy key.
_SESSION_DROP_MARKERS = ("1000", "normal closure", "connection closed", "timeout", "timed out")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive Gemini Live voice diagnostic (voice pipeline only)"
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Gemini Live model name (default: {DEFAULT_MODEL})",
    )
    return parser.parse_args()


def _is_access_denied(exc: BaseException) -> bool:
    """True if the exception chain indicates the API key's project is denied."""
    return _chain_matches(exc, _ACCESS_DENIED_MARKERS)


def _is_session_drop(exc: BaseException) -> bool:
    """True if the exception chain indicates a dropped session (normal closure/timeout)."""
    return _chain_matches(exc, _SESSION_DROP_MARKERS)


def _chain_matches(exc: BaseException, markers: tuple) -> bool:
    """Walk the exception chain (cause/context) looking for any marker."""
    current: BaseException | None = exc
    depth = 0
    while current is not None and depth < 10:
        text = str(current).lower()
        if any(marker in text for marker in markers):
            return True
        current = current.__cause__ or current.__context__
        depth += 1
    return False


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
    current: BaseException | None = exc
    while current is not None and depth < 10:
        prefix = "  " * depth + ("ROOT CAUSE: " if depth else "EXCEPTION: ")
        print(f"{prefix}{type(current).__module__}.{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__
        depth += 1
    print("\nFull traceback:")
    traceback.print_exception(type(exc), exc, exc.__traceback__)


def attempt_session(api_key: str, model: str, turn_log: list):
    """Run ONE indefinite live session attempt (Ctrl+C to end); raises on failure."""
    session = GeminiLiveVoiceSession(
        api_key=api_key,
        model=model,
        sample_rate_in=SAMPLE_RATE_IN,
        sample_rate_out=SAMPLE_RATE_OUT,
        max_retries=0,  # surface the first raw connection error immediately
        credential_pool=credential_pool,
        # Echo control: disable ALL client-side RMS barge-in (server VAD is the
        # sole authority) and mute the mic while the speaker plays FRIDAY's voice.
        barge_in_rms_threshold=float("inf"),
        local_barge_in_during_playback=False,
        headphones_mode=False,
    )
    if session.model != model:
        print(f"[WARN] Model normalized to '{session.model}' (input was rejected as non-Live).")

    # Live transcripts via the shared printer (same implementation as the CLI)
    from friday.voice.transcripts import LiveTranscriptPrinter

    printer = LiveTranscriptPrinter(turn_log=turn_log)
    on_server_content = printer.on_server_content
    on_turn_complete = printer.on_turn_complete

    async def run_indefinite() -> None:
        mic = MicrophoneStream(sample_rate=SAMPLE_RATE_IN)
        spk = SpeakerStream(sample_rate=SAMPLE_RATE_OUT)

        async def announce_connected() -> None:
            await session._connected_event.wait()
            print("\nCONNECTED! You can speak now. Press Ctrl+C to exit.")
            # Make FRIDAY speak first with a brief opening greeting.
            try:
                await session.send_text("Start the conversation by greeting me briefly.")
                print("[SENT initial greeting prompt]")
            except Exception as e:
                print(f"[WARN] Could not send initial greeting prompt: {e}")

        connected_task = asyncio.create_task(announce_connected(), name="diag_connected")
        try:
            await session.run_live_loop(
                input_stream=mic,
                output_stream=spk,
                on_turn_complete=on_turn_complete,
                on_server_content=on_server_content,
                echo_mute=True,
            )
        finally:
            connected_task.cancel()
            mic.stop()
            spk.close()

    asyncio.run(run_indefinite())
    return session


def print_summary(session, turn_log: list, elapsed: float) -> None:
    print("\n" + "=" * 70)
    print("SESSION SUMMARY")
    print("=" * 70)
    print(f"Session duration:    {elapsed:.1f}s")
    print(f"Model:               {session.model}")
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


def main() -> None:
    args = parse_args()
    print("=" * 70)
    print("FRIDAY — Interactive Gemini Live Voice Diagnostic (no agent)")
    print("=" * 70)
    print(f"Model:        {args.model}")
    print("Mode:         indefinite session (Ctrl+C to exit)")
    print(f"Key rotation: up to {MAX_KEY_ROTATIONS} attempts on 1008/'denied access'/'not supported'/quota")

    verify_audio_devices()

    session = None
    turn_log: list = []
    started = time.perf_counter()

    api_key = None
    reconnects_used = 0
    attempt = 0
    while True:
        attempt += 1
        if api_key is None or reconnects_used == 0:
            # Fresh key resolution (first attempt, or after a key rotation)
            print(f"\n--- Connection attempt {attempt} (key rotations used: {attempt - 1}/{MAX_KEY_ROTATIONS}) ---")
            api_key = resolve_api_key()
        turn_log = []
        try:
            session = attempt_session(api_key, args.model, turn_log)
            break  # session ended normally (Ctrl+C)
        except KeyboardInterrupt:
            print("\n[interrupted by user]")
            if session is None:
                sys.exit(0)
            break
        except BaseException as exc:  # noqa: BLE001 - diagnostics must show everything
            if _is_access_denied(exc) and attempt < MAX_KEY_ROTATIONS:
                print("Key denied access. Rotating to next key...")
                credential_pool.mark_key_unhealthy(api_key, error=exc)
                api_key = None
                reconnects_used = 0
                continue
            if _is_session_drop(exc) and reconnects_used < MAX_RECONNECTS:
                reconnects_used += 1
                print(f"Session dropped. Reconnecting with same key "
                      f"({reconnects_used}/{MAX_RECONNECTS})...")
                continue
            print_raw_error(exc)
            sys.exit(4)

    if session is not None:
        print_summary(session, turn_log, time.perf_counter() - started)


if __name__ == "__main__":
    main()
