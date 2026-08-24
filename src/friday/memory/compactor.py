# -*- coding: utf-8 -*-
"""Memory Compactor for FRIDAY Phase 14 Memory 2.0.

Summarizes old episodic memories into concise semantic knowledge facts using LLM reasoning.
"""

from typing import Dict, List, Optional
from friday.core.logging import get_logger
from friday.core.types import Message, Role
from friday.llm.base import BaseLLMProvider
from friday.memory.sqlite import SQLiteConversationMemory

logger = get_logger("memory.compactor")


class MemoryCompactor:
    """Consolidates granular episodic memories into long-term semantic knowledge."""

    def __init__(
        self,
        memory: SQLiteConversationMemory,
        llm_provider: BaseLLMProvider,
        compaction_threshold: int = 20,
    ) -> None:
        self.memory = memory
        self.llm = llm_provider
        self.compaction_threshold = compaction_threshold

    def compact_episodic_memories(
        self,
        conversation_id: Optional[str] = None,
        force: bool = False,
    ) -> Optional[str]:
        """Check episodic memory count; if above threshold or forced, compact into semantic nodes."""
        episodic_nodes = self.memory.get_memory_nodes(
            memory_type="episodic",
            conversation_id=conversation_id,
            limit=100,
        )

        if len(episodic_nodes) < self.compaction_threshold and not force:
            logger.debug(
                f"Episodic memory count ({len(episodic_nodes)}) is below threshold ({self.compaction_threshold}). Skipping compaction."
            )
            return None

        if not episodic_nodes:
            return None

        logger.info(f"Starting memory compaction on {len(episodic_nodes)} episodic records...")

        # Construct summarization prompt
        memory_lines = [
            f"- [{node.get('recency', '')}] ({node.get('source', 'user')}): {node.get('content', '')}"
            for node in episodic_nodes
        ]
        prompt_content = (
            "You are the long-term memory synthesis engine for FRIDAY.\n"
            "Analyze the following episodic logs and extract enduring semantic facts, user preferences, and permanent knowledge.\n"
            "Output only concise bullet points of learned knowledge facts:\n\n"
            + "\n".join(memory_lines)
        )

        response = self.llm.generate([Message(role=Role.USER, content=prompt_content)])
        semantic_summary = response.content.strip()

        if semantic_summary:
            # Store synthesized semantic knowledge node
            semantic_id = self.memory.add_memory_node(
                content=semantic_summary,
                memory_type="semantic",
                conversation_id=conversation_id,
                source="compactor",
                importance=0.9,
                confidence=0.95,
                metadata={"compacted_from_count": len(episodic_nodes)},
            )
            logger.info(f"Created compacted semantic memory node '{semantic_id}'")
            return semantic_id

        return None
