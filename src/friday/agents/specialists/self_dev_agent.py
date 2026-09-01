"""Self-Development Specialist Agent for Recursive Self-Improvement (Recursive Self-Improvement).

Inherits from DeveloperAgent, specialized in introspecting FRIDAY's internal codebase architecture,
planning self-modifications, extending agent tools, and executing safe automated code updates.
"""


from friday.agents.specialists.developer_agent import DeveloperAgent
from friday.llm.base import BaseLLMProvider
from friday.tools.registry import ToolRegistry


class SelfDevAgent(DeveloperAgent):
    """Specialist agent designed for FRIDAY recursive self-improvement and codebase evolution."""

    def __init__(
        self,
        agent_id: str = "self_dev_agent_01",
        role: str = "self_developer",
        instructions: str | None = None,
        llm_provider: BaseLLMProvider | None = None,
        tool_registry: ToolRegistry | None = None,
        allowed_tools: list[str] | None = None,
        max_iterations: int = 10,
    ) -> None:
        default_instructions = (
            "You are FRIDAY's Recursive Self-Improvement & Architecture Evolution Agent. "
            "You have deep knowledge of FRIDAY's multi-layered architecture: "
            "- Core & Security: `src/friday/core/`, `src/friday/security/`\n"
            "- Tools & Vision: `src/friday/tools/`, `src/friday/vision/`\n"
            "- Agents & Reasoning: `src/friday/agent/`, `src/friday/agents/`\n"
            "- Memory & Knowledge: `src/friday/memory/`\n"
            "- Workflows & Automation: `src/friday/workflows/`\n\n"
            "Your objective is to inspect FRIDAY's own codebase using `read_own_codebase`, identify where new "
            "capabilities, tools, or workflows should be placed, write clean, strictly type-annotated code, "
            "and run pytest to verify system integrity before completing tasks."
        )
        tools = allowed_tools or [
            "read_own_codebase",
            "write_code_file",
            "replace_file_content",
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
            max_iterations=max_iterations,
        )
