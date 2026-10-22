from __future__ import annotations
import threading
from collections import defaultdict
from contextlib import contextmanager


class ResourceLocks:
    def __init__(self):
        self._locks = defaultdict(threading.RLock)

    @contextmanager
    def acquire(self, resources):
        keys = sorted({x for x in resources if x})
        locks = [self._locks[k] for k in keys]
        for l in locks:
            l.acquire()
        try:
            yield
        finally:
            for l in reversed(locks):
                l.release()
