"""Browser Use Bridge for FRIDAY.

Connects to BrowserUseExecutor and BrowserSafetyGuard, ensuring all browser automation
remains strictly under FRIDAY's control and security boundaries.
"""

from __future__ import annotations

from typing import Any

from friday.integrations.browser_use.executor import BrowserUseExecutor
from friday.integrations.browser_use.safety import BrowserSafetyGuard, BrowserSafetyPolicy


class BrowserUseBridge:
    """Bridge interface to FRIDAY's BrowserUseExecutor."""

    def __init__(self, headless: bool = True, timeout: int = 120) -> None:
        self.executor = BrowserUseExecutor(headless=headless)
        self.timeout = timeout

    def available(self) -> bool:
        """Check if any browser automation engine (browser-use or playwright) is available."""
        return self.executor.has_browser_use_package or self.executor.has_playwright_package

    def run(self, task: str, url: str | None = None) -> dict[str, Any]:
        """Execute a browser automation task through FRIDAY's executor."""
        res = self.executor.execute({"action": "navigate" if url else "extract", "url": url, "query": task})
        return {
            "success": res.success,
            "output": res.output,
            "error": res.error,
            "metadata": res.metadata,
        }
