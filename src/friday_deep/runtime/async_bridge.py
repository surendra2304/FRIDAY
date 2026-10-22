from __future__ import annotations
import asyncio
from concurrent.futures import ThreadPoolExecutor


def run_async_from_sync(awaitable):
    """Bridge sync callers to async tools without nesting asyncio.run()."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    def worker():
        return asyncio.run(awaitable)

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="friday-async-bridge") as pool:
        return pool.submit(worker).result()
