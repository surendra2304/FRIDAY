"""Research Specialist Agent for Autonomous Web Research and Synthesis."""


from friday.agents.base_agent import BaseAgent
from friday.llm.base import BaseLLMProvider
from friday.tools.registry import ToolRegistry


class ResearchAgent(BaseAgent):
    """Specialist agent designed to autonomously search the web, fetch pages, and synthesize findings."""

    def __init__(
        self,
        agent_id: str = "research_agent_01",
        role: str = "researcher",
        instructions: str | None = None,
        llm_provider: BaseLLMProvider | None = None,
        tool_registry: ToolRegistry | None = None,
        allowed_tools: list[str] | None = None,
        max_iterations: int = 8,
    ) -> None:
        default_instructions = (
            "You are FRIDAY's Autonomous Web Research Specialist Agent. "
            "Your objective is to conduct thorough, factual, and concise web investigations. "
            "1. Use 'web_search' to discover high-quality URLs matching the user's research topic. "
            "2. Use 'fetch_webpage_content' to read and extract clean text from the most relevant links. "
            "3. Use 'synthesize_information' to summarize key insights into a 3-bullet-point final report. "
            "Always present clear, well-structured, and verified answers with citations where appropriate."
        )
        tools = allowed_tools or [
            "web_search",
            "fetch_webpage_content",
            "synthesize_information",
            "fetch_webpage",
            "read_file",
            "list_files",
            "memory_search",
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
