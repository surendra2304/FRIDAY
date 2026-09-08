from __future__ import annotations
import asyncio


class ThreadSafeAudioBridge:
    def __init__(self, maxsize=100):
        self.maxsize = maxsize
        self.loop = None
        self.queue = None
        self.dropped = 0

    def bind(self, loop):
        self.loop = loop
        self.queue = asyncio.Queue(maxsize=self.maxsize)

    def put_from_callback(self, item):
        if self.loop is None or self.queue is None or self.loop.is_closed():
            self.dropped += 1
            return

        def put():
            try:
                self.queue.put_nowait(item)
            except asyncio.QueueFull:
                self.dropped += 1
                try:
                    self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    self.queue.put_nowait(item)
                except asyncio.QueueFull:
                    pass

        self.loop.call_soon_threadsafe(put)

    async def get(self):
        if self.queue is None:
            raise RuntimeError("Audio bridge is not bound")
        return await self.queue.get()
