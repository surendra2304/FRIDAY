# -*- coding: utf-8 -*-
"""Vision memory manager for storing and recalling derived visual context safely.

Features:
- Stores derived textual observations rather than raw screenshots.
- Redacts sensitive credentials, passwords, tokens, and financial secrets before storage.
- Request deduplication to avoid storing identical visual snapshots repeatedly.
- Integrates with SQLite memory, SQLite FTS5 search, and semantic embeddings with automatic fallback.
"""

import hashlib
import re
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from friday.core.logging import get_logger
from friday.core.types import Message, Role, SafetyLevel
from friday.memory.base import BaseMemory
from friday.vision.screen_context import ScreenContext

logger = get_logger("vision.memory")

# Redaction patterns for sensitive visual text
SENSITIVE_PATTERNS = [
    (re.compile(r"(AIza" + r"Sy[a-zA-Z0-9_-]{33})", re.IGNORECASE), "[REDACTED_API_KEY]"),
    (re.compile(r"(sk-[a-zA-Z0-9]{20,})", re.IGNORECASE), "[REDACTED_API_KEY]"),
    (re.compile(r"(Bearer\s+[a-zA-Z0-9_\-\.]{20,})", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"(password|passwd|pwd)\s*[:=]\s*['\"]?([^'\"\s\n]+)['\"]?", re.IGNORECASE), r"\1: [REDACTED_PASSWORD]"),
    (re.compile(r"(api[_-]?key|secret|token)\s*[:=]\s*['\"]?([^'\"\s\n]+)['\"]?", re.IGNORECASE), r"\1: [REDACTED_SECRET]"),
    (re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "[REDACTED_CARD_NUMBER]"),  # Credit card numbers
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),              # SSN
]


def redact_sensitive_visual_text(text: str) -> str:
    """Sanitize and redact sensitive credentials and private data from visual text."""
    if not text:
        return ""
    sanitized = text
    for pattern, replacement in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


class VisionMemoryManager:
    """Manager for recording and recalling derived visual context from persistent memory."""

    def __init__(self, memory: BaseMemory) -> None:
        self.memory = memory
        self._last_stored_hash: Optional[str] = None

    def store_visual_observation(
        self,
        screen_context: ScreenContext,
        force: bool = False,
        conversation_id: Optional[str] = None,
    ) -> Optional[Message]:
        """Record derived visual context to persistent conversation memory.

        Args:
            screen_context: Analyzed screen context.
            force: Bypass duplicate suppression if explicitly requested.
            conversation_id: Target conversation session.

        Returns:
            Created Message object, or None if skipped (e.g. error context or duplicate).
        """
        if screen_context.is_error or not screen_context.summary:
            logger.debug("Skipping storage of error/empty visual context.")
            return None

        # 1. Redact any sensitive content
        clean_summary = redact_sensitive_visual_text(screen_context.summary)
        content_hash = hashlib.sha256(clean_summary.encode("utf-8")).hexdigest()

        # 2. Duplicate suppression check
        if not force and self._last_stored_hash == content_hash:
            logger.debug("Suppressed duplicate visual memory storage.")
            return None

        # 3. Format structured derived observation message
        derived_content = (
            f"[Visual Observation - {screen_context.width}x{screen_context.height} ({screen_context.display_id})]\n"
            f"{clean_summary}"
        )

        msg = Message(
            role=Role.TOOL,
            content=derived_content,
            name="screen_observation",
        )

        target_conv_id = conversation_id
        if hasattr(self.memory, "active_conversation_id") and not target_conv_id:
            target_conv_id = self.memory.active_conversation_id

        # 4. Save to persistent SQLite memory (triggers FTS and embedding indexing)
        self.memory.add_message(msg, conversation_id=target_conv_id)
        self._last_stored_hash = content_hash
        logger.info(f"Stored derived visual memory ({len(derived_content)} chars).")
        return msg

    def recall_visual_memories(
        self,
        query: str,
        limit: int = 3,
        conversation_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search historical visual memories using memory search (FTS / Semantic)."""
        target_conv_id = conversation_id
        if hasattr(self.memory, "active_conversation_id") and not target_conv_id:
            target_conv_id = self.memory.active_conversation_id

        results = self.memory.search(query=query, conversation_id=target_conv_id, limit=limit)
        visual_results = []
        for r in results:
            if "Visual Observation" in r.content or r.role == Role.TOOL:
                visual_results.append({
                    "content": r.content,
                    "score": r.score,
                    "timestamp": r.timestamp.isoformat() if hasattr(r.timestamp, "isoformat") else str(r.timestamp),
                })
        return visual_results
