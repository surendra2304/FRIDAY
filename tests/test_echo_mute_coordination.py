"""Unit tests for half-duplex echo suppression (mic muting during speaker playback)."""

import asyncio

from friday.voice.audio_io import MicrophoneStream, SpeakerStream


def _live_mic() -> MicrophoneStream:
    mic = MicrophoneStream()
    mic._active = True
    mic._queue = asyncio.Queue(maxsize=10)
    return mic


def _live_spk() -> SpeakerStream:
    spk = SpeakerStream()
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
