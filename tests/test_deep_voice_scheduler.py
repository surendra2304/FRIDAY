from friday_deep.contracts import Status
from friday_deep.voice.bridge import ThreadSafeAudioBridge
from friday_deep.voice.session import VoiceSession


def test_bridge_unbound_drops():
    b = ThreadSafeAudioBridge()
    b.put_from_callback(b"x")
    assert b.dropped == 1


def test_voice_sync_active_loop_is_not_silent():
    import asyncio

    async def outer():
        async def c():
            return 1

        coro = c()
        try:
            VoiceSession().run_sync(coro)
        except RuntimeError as e:
            coro.close()
            return "async" in str(e)
        return False

    assert asyncio.run(outer())
