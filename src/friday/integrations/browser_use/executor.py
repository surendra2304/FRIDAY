"""Browser Use Specialist Executor for FRIDAY.

Integrates browser execution capability into FRIDAY without delegating primary
planning or conversational authority. All operations pass through BrowserSafetyGuard
and adhere to FRIDAY's timeout, cancellation, and security boundaries.

Supports:
1. Browser Use Agent (if `browser_use` package is installed)
2. Direct Playwright Engine (headless/headed via installed `playwright`)
3. Native Web Tools Fallback (`fetch_webpage_content`, `web_search`)
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel
from friday.integrations.browser_use.safety import BrowserSafetyGuard, BrowserSafetyPolicy
from friday.planning.executors import BaseExecutor, ExecutorResult
from friday.planning.types import TaskDataType

logger = get_logger("integrations.browser.executor")


class BrowserUseExecutor(BaseExecutor):
    """Specialist executor for web navigation, page inspection, and browser automation."""

    def __init__(
        self,
        name: str = "browser_use",
        safety_policy: BrowserSafetyPolicy | None = None,
        llm_provider: Any = None,
        headless: bool = True,
    ) -> None:
        super().__init__(
            name=name,
            capability="browser_interaction",
            description="Executes browser automation: navigate URLs, click, type, extract content, capture screenshots, and verify page state.",
            input_types=[TaskDataType.URL, TaskDataType.TEXT, TaskDataType.STRUCTURED_DATA],
            output_types=[TaskDataType.TEXT, TaskDataType.STRUCTURED_DATA, TaskDataType.SCREENSHOT],
            provider="browser_specialist",
            model="playwright/browser-use",
            is_local=True,
            cost_profile="free",
            latency_profile="medium",
            safety_level=SafetyLevel.SAFE,
        )
        self.safety_guard = BrowserSafetyGuard(policy=safety_policy)
        self.llm_provider = llm_provider
        self.headless = headless

    @property
    def has_browser_use_package(self) -> bool:
        """Check if browser-use package is installed."""
        try:
            import browser_use  # noqa: F401
            return True
        except ImportError:
            return False

    @property
    def has_playwright_package(self) -> bool:
        """Check if playwright is installed."""
        try:
            import playwright  # noqa: F401
            return True
        except ImportError:
            return False

    def execute(self, inputs: dict[str, Any], context: dict[str, Any] | None = None) -> ExecutorResult:
        """Execute browser action or autonomous navigation task."""
        start_t = time.perf_counter()
        action = str(inputs.get("action", "navigate")).lower()
        url = inputs.get("url") or inputs.get("target_url")
        query = inputs.get("query") or inputs.get("task") or inputs.get("prompt", "")

        # 1. Validate Target URL if provided
        if url:
            is_safe, reason = self.safety_guard.validate_url(url)
            if not is_safe:
                return ExecutorResult(
                    success=False,
                    output=None,
                    error=f"Browser Safety Block: {reason}",
                    output_type=TaskDataType.TEXT,
                    duration_seconds=time.perf_counter() - start_t,
                    metadata={"blocked": True, "url": url},
                )

        # 2. Sanitize specific action
        action_safe, action_reason, safety_level = self.safety_guard.sanitize_action(action, inputs)
        if not action_safe:
            return ExecutorResult(
                success=False,
                output=None,
                error=f"Action Blocked: {action_reason}",
                output_type=TaskDataType.TEXT,
                duration_seconds=time.perf_counter() - start_t,
                metadata={"safety_level": safety_level.value},
            )

        # 3. Route Execution: Playwright / Native Fallback
        try:
            if self.has_playwright_package and (url or action in ("extract", "navigate", "screenshot")):
                res = self._execute_via_playwright(action=action, url=url, inputs=inputs)
                duration = time.perf_counter() - start_t
                return ExecutorResult(
                    success=True,
                    output=res.get("content") or res.get("text") or res,
                    output_type=TaskDataType.SCREENSHOT if action == "screenshot" else TaskDataType.TEXT,
                    duration_seconds=duration,
                    metadata={"engine": "playwright", "url": url, "action": action},
                )

            # Fallback to FRIDAY Native Tools
            return self._execute_native_fallback(action=action, url=url, query=query, start_t=start_t)

        except Exception as e:
            logger.warning(f"Browser execution error: {e}. Attempting native fallback...")
            try:
                return self._execute_native_fallback(action=action, url=url, query=query, start_t=start_t)
            except Exception as fallback_err:
                return ExecutorResult(
                    success=False,
                    output=None,
                    error=f"Browser execution failed: {e}; fallback also failed: {fallback_err}",
                    duration_seconds=time.perf_counter() - start_t,
                )

    def _execute_via_playwright(self, action: str, url: str | None, inputs: dict[str, Any]) -> dict[str, Any]:
        """Direct Playwright automation execution."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_page()
            try:
                if url:
                    page.goto(url, timeout=int(self.safety_guard.policy.max_timeout_seconds * 1000), wait_until="domcontentloaded")

                if action in ("navigate", "inspect_state", "extract"):
                    title = page.title()
                    # Extract main visible text
                    body_text = page.inner_text("body")
                    # Clean and truncate if needed
                    clean_text = "\n".join(line.strip() for line in body_text.splitlines() if line.strip())
                    return {
                        "url": page.url,
                        "title": title,
                        "content": clean_text[:4000],
                    }

                elif action == "click":
                    selector = inputs.get("selector") or inputs.get("target")
                    if selector:
                        page.click(selector, timeout=5000)
                    return {"url": page.url, "clicked": selector, "content": page.inner_text("body")[:2000]}

                elif action == "type":
                    selector = inputs.get("selector") or inputs.get("target")
                    text_to_type = inputs.get("text", "")
                    if selector:
                        page.fill(selector, text_to_type, timeout=5000)
                    return {"url": page.url, "typed": text_to_type}

                elif action == "screenshot":
                    import os
                    from pathlib import Path

                    out_dir = Path("data/screenshots")
                    out_dir.mkdir(parents=True, exist_ok=True)
                    shot_path = str(out_dir / f"browser_{int(time.time())}.png")
                    page.screenshot(path=shot_path)
                    return {"screenshot_path": shot_path, "url": page.url, "content": f"Screenshot saved to {shot_path}"}

                return {"url": page.url, "content": page.inner_text("body")[:2000]}
            finally:
                browser.close()

    def _execute_native_fallback(
        self,
        action: str,
        url: str | None,
        query: str,
        start_t: float,
    ) -> ExecutorResult:
        """Fallback to FRIDAY's built-in web and search tools."""
        if url:
            from friday.tools.builtin.web_tools import FetchWebpageContentTool

            tool = FetchWebpageContentTool()
            res = tool.execute(url=url)
            duration = time.perf_counter() - start_t
            return ExecutorResult(
                success=res.success,
                output=res.data or res.error,
                error=res.error if not res.success else None,
                output_type=TaskDataType.TEXT,
                duration_seconds=duration,
                metadata={"engine": "native_fetch", "url": url},
            )

        if query:
            from friday.tools.builtin.web_tools import WebSearchTool

            tool = WebSearchTool()
            res = tool.execute(query=query)
            duration = time.perf_counter() - start_t
            return ExecutorResult(
                success=res.success,
                output=res.data or res.error,
                error=res.error if not res.success else None,
                output_type=TaskDataType.TEXT,
                duration_seconds=duration,
                metadata={"engine": "native_search", "query": query},
            )

        return ExecutorResult(
            success=False,
            output=None,
            error="Browser executor requires either a 'url' or a 'query' input.",
            duration_seconds=time.perf_counter() - start_t,
        )
