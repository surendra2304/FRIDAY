"""Unit tests for half-duplex echo suppression (mic muting during speaker playback)."""

import asyncio

from friday.voice.audio_io import MicrophoneStream, SpeakerStream


def _live_mic() -> MicrophoneStream:
    mic = MicrophoneStream()
    mic._active = True
    mic._queue = asyncio.Queue(maxsize=10)
    return mic


def _live_spk() -> SpeakerStream:
    spk = SpeakerStream(prebuffer_ms=0)  # immediate playback: prebuffering tested separately
    spk._active = True
    return spk


def test_mic_mute_drops_frames():
    mic = _live_mic()
    assert mic.is_muted is False

    mic._safe_enqueue(b"\x01\x02")
    assert mic._queue.qsize() == 1

    mic.set_muted(True)
    mic._safe_enqueue(b"\x03\x04")  # dropped, never enqueued
    assert mic.is_muted is True
    assert mic._queue.qsize() == 1
    assert mic.muted_dropped_frames == 1

    mic.set_muted(False)
    mic._safe_enqueue(b"\x05\x06")
    assert mic._queue.qsize() == 2


def test_speaker_mutes_mic_on_first_chunk():
    mic = _live_mic()
    spk = _live_spk()
    spk.set_echo_mute_target(mic)

    assert mic.is_muted is False
    spk.play_chunk(b"\x00" * 64)
    assert mic.is_muted is True  # muted the moment playback begins


def test_speaker_unmutes_after_drain_blocks():
    mic = _live_mic()
    spk = _live_spk()
    spk.set_echo_mute_target(mic)
    spk.play_chunk(b"\x00" * 64)
    assert mic.is_muted is True

    # Queue still has data: no unmute
    spk._maybe_unmute()
    assert mic.is_muted is True

    # Drain the queue, then a few empty output blocks unmuute
    spk._queue.get_nowait()
    spk._maybe_unmute()
    spk._maybe_unmute()
    assert mic.is_muted is True  # tail-latency grace blocks
    spk._maybe_unmute()
    assert mic.is_muted is False


def test_speaker_purge_unmutes_immediately():
    mic = _live_mic()
    spk = _live_spk()
    spk.set_echo_mute_target(mic)
    spk.play_chunk(b"\x00" * 64)
    assert mic.is_muted is True

    spk.stop()  # barge-in purge: playback ceased -> mic resumes now
    assert mic.is_muted is False


def test_no_echo_target_is_safe():
    spk = _live_spk()  # no mic wired
    spk.play_chunk(b"\x00" * 64)
    spk._maybe_unmute()
    spk.stop()  # must not raise


# ---------------------------------------------------------------------------
# Jitter buffer (pre-buffering before playback)
# ---------------------------------------------------------------------------


def test_jitter_buffer_holds_until_threshold():
    spk = SpeakerStream(sample_rate=24000, prebuffer_ms=100.0)  # 4800 bytes
    spk._active = True

    spk.play_chunk(b"\x00" * 2000)
    spk.play_chunk(b"\x00" * 2000)
    assert spk._queue.qsize() == 0          # still buffered
    assert len(spk._prebuffer) == 4000
    assert spk.is_playing is True           # counts as playing while buffering

    spk.play_chunk(b"\x00" * 1000)          # crosses 4800-byte threshold
    assert spk._queue.qsize() == 1          # flushed to playback queue
    assert len(spk._prebuffer) == 0


def test_jitter_buffer_disabled_when_zero():
    spk = SpeakerStream(prebuffer_ms=0)
    spk._active = True
    spk.play_chunk(b"\x00" * 64)
    assert spk._queue.qsize() == 1
    assert len(spk._prebuffer) == 0


def test_jitter_buffer_purged_on_stop():
    spk = SpeakerStream(prebuffer_ms=100.0)
    spk._active = True
    spk.play_chunk(b"\x00" * 2000)
    assert len(spk._prebuffer) == 2000
    spk.stop()
    assert len(spk._prebuffer) == 0
    assert spk._queue.qsize() == 0


def test_prebuffer_counts_for_echo_unmute_gate():
    mic = MicrophoneStream()
    mic._active = True
    mic._queue = asyncio.Queue(maxsize=10)
    spk = SpeakerStream(prebuffer_ms=100.0)
    spk._active = True
    spk.set_echo_mute_target(mic)

    spk.play_chunk(b"\x00" * 1000)          # held in prebuffer
    assert mic.is_muted is True
    for _ in range(5):
        spk._maybe_unmute()                  # prebuffer non-empty: never unmute
    assert mic.is_muted is True
