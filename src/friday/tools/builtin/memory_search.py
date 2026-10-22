"""Tool for searching historical conversation messages across persistent memory."""

from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.memory.base import BaseMemory
from friday.tools.base import BaseTool

logger = get_logger("tools.memory_search")


class MemorySearchTool(BaseTool):
    """Search stored conversation history for past topics, preferences, or details."""

    def __init__(self, memory: BaseMemory) -> None:
        self.memory = memory

    @property
    def name(self) -> str:
        return "search_memory"

    @property
    def description(self) -> str:
        return (
            "Search previous conversation history across all sessions (or within a specific conversation) "
            "for facts, topics, user preferences, past questions, or context discussed earlier."
        )

    @property
    def safety_level(self) -> SafetyLevel:
        return SafetyLevel.SAFE

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords or phrase to search for in past messages",
                },
                "conversation_id": {
                    "type": "string",
                    "description": "Optional conversation ID to restrict search scope",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of search results to return (default: 5, max: 20)",
                },
            },
            "required": ["query"],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return ToolResult(
                name=self.name,
                content="Error: Search query cannot be empty.",
                is_error=True,
                safety_level=self.safety_level,
            )

        conversation_id: str | None = kwargs.get("conversation_id")
        limit = min(20, max(1, int(kwargs.get("limit", 5))))

        try:
            results = self.memory.search(
                query=query,
                conversation_id=conversation_id,
                limit=limit,
            )
            if not results:
                scope_info = f" in conversation '{conversation_id}'" if conversation_id else ""
                return ToolResult(
                    name=self.name,
                    content=f"No historical messages found matching query '{query}'{scope_info}.",
                    is_error=False,
                    safety_level=self.safety_level,
                )

            output_lines = [f"Found {len(results)} relevant message(s) for query '{query}':\n"]
            for idx, r in enumerate(results, 1):
                time_str = r.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                output_lines.append(
                    f"[{idx}] Conversation: '{r.conversation_title}' (ID: {r.conversation_id[:8]})\n"
                    f"     Date: {time_str} | Role: {r.role.value.upper()}\n"
                    f"     Content: {r.content}\n"
                )
            return ToolResult(
                name=self.name,
                content="\n".join(output_lines).strip(),
                is_error=False,
                safety_level=self.safety_level,
            )
        except Exception as e:
            logger.error(f"Failed to execute memory search for '{query}': {e}", exc_info=True)
            return ToolResult(
                name=self.name,
                content=f"Error executing memory search: {e}",
                is_error=True,
                safety_level=self.safety_level,
            )
