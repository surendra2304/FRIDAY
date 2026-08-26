# -*- coding: utf-8 -*-
"""Proactive Screen Reading (The Watcher) for Proactive Screen Reading.

Passively reads active screen context via local OCR (Tesseract) and active window tracking,
evaluating screen text using a fast Groq LLM call (or active provider) to offer proactive
assistance (e.g. debugging code errors, proofreading email drafts).
"""

import json
import re
from typing import Any, Dict, Optional

from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.core.types import Message, Role
from friday.observability.notifications import NotificationManager
from friday.tools.builtin.screen_ocr import ReadScreenTextTool
from friday.vision.active_context import get_active_window_context

logger = get_logger("vision.screen_watcher")


class ScreenWatcherService:
    """Passively analyzes foreground screen text to surface proactive assistance notifications."""

    def __init__(
        self,
        notification_manager: Optional[NotificationManager] = None,
        llm_provider: Optional[Any] = None,
    ) -> None:
        self.notification_manager = notification_manager
        self.llm_provider = llm_provider

    def _get_llm(self) -> Any:
        """Resolve fast Groq LLM provider or fallback."""
        if self.llm_provider is not None:
            return self.llm_provider
        
        settings = get_settings()
        # Fast-path: Instantiate GroqLLMProvider if groq key present, else general factory
        from friday.llm.factory import create_llm_provider
        return create_llm_provider(settings)

    def analyze_screen_text(self, screen_text: str, window_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Classify intent from screen text via fast LLM call.

        Prompt:
        "Analyze this screen text. If you see a code error, return JSON {'action': 'offer_debug'}.
        If it's an email draft, return {'action': 'offer_proofread'}. Otherwise, return {'action': 'none'}."
        """
        clean_text = (screen_text or "").strip()
        if not clean_text or len(clean_text) < 15:
            return {"action": "none"}

        # Truncate text if excessively long for fast processing
        truncated_text = clean_text[:3000]

        prompt = (
            "Analyze this screen text. If you see a code error or traceback, return JSON {'action': 'offer_debug'}.\n"
            "If it's an email draft or composition, return JSON {'action': 'offer_proofread'}.\n"
            "Otherwise, return JSON {'action': 'none'}.\n\n"
            f"Screen Text:\n{truncated_text}\n\n"
            "Respond ONLY with a valid JSON object matching: {\"action\": \"offer_debug\" | \"offer_proofread\" | \"none\"}"
        )

        messages = [
            Message(role=Role.SYSTEM, content="You are a fast JSON screen intent classifier assistant."),
            Message(role=Role.USER, content=prompt),
        ]

        try:
            llm = self._get_llm()
            resp = llm.generate(messages=messages)
            raw_content = (resp.content or "").strip()
            
            match = re.search(r"\{.*\}", raw_content, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
            else:
                data = json.loads(raw_content)

            action = data.get("action", "none").lower().strip()
            if action not in ("offer_debug", "offer_proofread", "none"):
                action = "none"
            return {"action": action}
        except Exception as e:
            logger.debug(f"Screen watcher LLM classification error: {e}")
            # Fallback simple heuristic
            lower = clean_text.lower()
            if "traceback (most recent call last)" in lower or "error:" in lower or "exception:" in lower:
                return {"action": "offer_debug"}
            return {"action": "none"}

    def check_and_notify(self) -> Optional[Dict[str, Any]]:
        """Perform one screen observation cycle and post notification if actionable."""
        try:
            ctx = get_active_window_context()
            win_title = ctx.get("title", "")
            app_name = ctx.get("process_name", "your active app")

            ocr_res = ReadScreenTextTool().execute()
            if ocr_res.is_error or not ocr_res.content:
                return None

            screen_text = ocr_res.content
            classification = self.analyze_screen_text(screen_text, window_context=ctx)
            action = classification.get("action", "none")

            if action == "offer_debug":
                clean_app = "VS Code" if "code" in app_name.lower() or "code" in win_title.lower() else app_name
                msg = f"I noticed you hit an error in {clean_app}. Would you like me to analyze it?"
                if self.notification_manager is not None:
                    self.notification_manager.post_notification(
                        message=msg,
                        category="screen_watcher",
                        severity="info",
                        metadata={"action": action, "app": clean_app, "window": win_title},
                    )
                logger.info(f"[ScreenWatcher] Posted debug offer notification: '{msg}'")
                return {"action": action, "message": msg}

            elif action == "offer_proofread":
                clean_app = "your email draft"
                msg = "I noticed you're drafting an email. Would you like me to proofread it?"
                if self.notification_manager is not None:
                    self.notification_manager.post_notification(
                        message=msg,
                        category="screen_watcher",
                        severity="info",
                        metadata={"action": action, "app": clean_app, "window": win_title},
                    )
                logger.info(f"[ScreenWatcher] Posted proofread offer notification: '{msg}'")
                return {"action": action, "message": msg}

            return None
        except Exception as e:
            logger.debug(f"Screen watcher check failed: {e}")
            return None
