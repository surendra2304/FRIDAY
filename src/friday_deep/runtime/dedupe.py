from __future__ import annotations
import hashlib
import json
import threading


class DuplicateCallGuard:
    def __init__(self, limit: int = 2):
        self.limit = max(1, limit)
        self._counts = {}
        self._lock = threading.Lock()

    @staticmethod
    def fingerprint(tool, args):
        return hashlib.sha256(
            json.dumps({"tool": tool, "args": args}, sort_keys=True, default=str, separators=(",", ":")).encode()
        ).hexdigest()

    def allow(self, tool, args):
        fp = self.fingerprint(tool, args)
        with self._lock:
            c = self._counts.get(fp, 0)
            if c >= self.limit:
                return False
            self._counts[fp] = c + 1
            return True
