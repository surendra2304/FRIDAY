from __future__ import annotations
import asyncio


class VoiceSession:
    """Lifecycle guard preventing silent background task creation in sync APIs."""

    async def run_async(self, coro):
        return await coro

    def run_sync(self, coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError("Use the async voice API inside a running event loop")
