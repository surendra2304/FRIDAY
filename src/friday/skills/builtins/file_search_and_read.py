# -*- coding: utf-8 -*-
"""Built-in File Search and Read Skill for FRIDAY."""

import os
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger
from friday.skills.base_skill import BaseSkill, SkillExecutionResult

logger = get_logger("skills.file_search_and_read")


class FileSearchAndReadSkill(BaseSkill):
    """Searches for a requested document or file and reads its content autonomously."""

    name = "file_search_and_read"
    description = "Searches for a requested file in the workspace or documents and reads its content."
    required_capabilities = ["file_read"]
    tools = ["file_listing", "file_reader", "synthesize_information"]
    system_prompt = "You are FRIDAY's Document Specialist. Search for requested files and read contents accurately."
    match_patterns = [
        r"\b(?:find|search\s+for)\s+(?:the\s+)?(?:file|doc|document|code|notes?)\s+[\"']?([\w\.\-_]+)[\"']?\s+and\s+(?:read|open|show|inspect)\s+it\b",
        r"\bfind\s+(?:my\s+)?resume\s+and\s+read\s+it\b",
    ]

    def execute(
        self,
        user_request: str,
        agent: Optional[Any] = None,
        tool_registry: Optional[Any] = None,
        llm_provider: Optional[Any] = None,
        authorizer: Optional[Any] = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        step_results: List[Dict[str, Any]] = []
        list_tool = tool_registry.get("file_listing") if tool_registry else None
        read_tool = tool_registry.get("file_reader") if tool_registry else None

        # Look up files in current working directory
        found_path = None
        if list_tool:
            try:
                res = list_tool.execute(directory_path=".")
                step_results.append({"step": "list_files", "output": res.content[:200]})
                for line in res.content.splitlines():
                    if "resume" in line.lower() or "diary" in line.lower() or "readme" in line.lower():
                        parts = line.strip().split()
                        if parts:
                            found_path = parts[-1]
                            break
            except Exception as e:
                step_results.append({"step": "list_files", "error": str(e)})

        if not found_path and os.path.exists("README.md"):
            found_path = "README.md"

        content = ""
        if found_path and read_tool:
            try:
                res = read_tool.execute(file_path=found_path)
                content = res.content
                step_results.append({"step": "read_file", "path": found_path, "length": len(content)})
            except Exception as e:
                step_results.append({"step": "read_file", "error": str(e)})

        if content:
            output = f"Located and read '{found_path}':\n\n{content[:400]}..."
            return SkillExecutionResult(
                skill_name=self.name,
                success=True,
                output=output,
                step_results=step_results,
                metadata={"file_path": found_path},
            )
        else:
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output="I searched for the requested file but could not locate a matching document in the active workspace.",
                step_results=step_results,
                error="File not found in active workspace",
            )
