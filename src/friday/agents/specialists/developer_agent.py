# -*- coding: utf-8 -*-
"""Developer Specialist Agent for Phase 26: Autonomous Self-Coding."""

from typing import Any, Dict, List, Optional

from friday.agents.base_agent import BaseAgent
from friday.llm.base import BaseLLMProvider
from friday.tools.registry import ToolRegistry


class DeveloperAgent(BaseAgent):
    """Specialist agent designed to autonomously inspect, write, test, and branch Python code."""

    def __init__(
        self,
        agent_id: str = "dev_agent_01",
        role: str = "developer",
        instructions: Optional[str] = None,
        llm_provider: Optional[BaseLLMProvider] = None,
        tool_registry: Optional[ToolRegistry] = None,
        allowed_tools: Optional[List[str]] = None,
        max_iterations: int = 8,
    ) -> None:
        default_instructions = (
            "You are FRIDAY's Autonomous Developer Specialist Agent. "
            "Your objective is to inspect issues, write clean, maintainable, and type-annotated Python code, "
            "run automated pytest suites to verify fixes, and manage git branches and commits safely. "
            "Always verify changes by running tests before finishing tasks."
        )
        tools = allowed_tools or [
            "write_code_file",
            "run_tests",
            "create_git_branch",
            "read_file",
            "list_files",
            "file_operations",
            "git_status",
            "git_commit",
            "git_push",
            "list_github_issues",
            "execute_command",
        ]
        super().__init__(
            agent_id=agent_id,
            role=role,
            instructions=instructions or default_instructions,
            llm_provider=llm_provider,
            tool_registry=tool_registry,
            allowed_tools=tools,
            memory_scope="task",
            max_iterations=max_iterations,
        )
