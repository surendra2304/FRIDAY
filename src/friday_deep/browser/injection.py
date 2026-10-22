from __future__ import annotations
from ..security.content_guard import ContentGuard, Decision


class BrowserContentBoundary:
    def __init__(self):
        self.guard = ContentGuard()

    def prepare(self, text: str, url: str):
        g = self.guard.guard(text, "browser")
        if g.decision is Decision.BLOCK:
            return {"usable": False, "content": "", "url": url, "hash": g.content_hash, "reasons": g.reasons}
        return {"usable": True, "content": g.content, "url": url, "hash": g.content_hash, "reasons": g.reasons}

    def can_invoke_local_tool(self, content):
        return False
