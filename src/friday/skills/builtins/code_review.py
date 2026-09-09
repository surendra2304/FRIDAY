"""Code Review Built-in Skill for FRIDAY (Adapted from ECC code-review)."""

from typing import Any

from friday.core.logging import get_logger
from friday.skills.base_skill import BaseSkill, SkillExecutionResult

logger = get_logger("skills.code_review")



class CodeReviewSkill(BaseSkill):
    """Executes multi-pass code review across files, diffs, or code snippets."""

    name = "code_review"
    description = "Performs multi-pass code review evaluating logic correctness, style, architecture, and edge cases."
    required_capabilities = ["file_read"]
    tools = ["read_file", "list_files", "execute_command", "synthesize_information"]
    system_prompt = (
        "You are FRIDAY's Code Reviewer. Inspect code for bugs, missing error handling, "
        "type annotations, and architectural consistency. Categorize findings into BLOCKER, WARNING, and NIT."
    )
    match_patterns = [
        r"\b(?:review|inspect|audit)\s+(?:the\s+)?(?:code|changes|diff|file|pr|pull\s*request)\b",
        r"\bcode\s+review\b",
        r"\bcheck\s+(?:this|my)\s+code\b",
    ]

    def execute(
        self,
        user_request: str,
        agent: Any | None = None,
        tool_registry: Any | None = None,
        llm_provider: Any | None = None,
        authorizer: Any | None = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        step_results: list[dict[str, Any]] = []
        from friday.agents.specialists.developer_agent import DeveloperAgent

        reviewer = DeveloperAgent(
            agent_id="code_reviewer_01",
            role="code_reviewer",
            instructions=(
                "Perform rigorous code review. Inspect for logic correctness, error handling, "
                "type annotations, and architectural consistency. Categorize into BLOCKER, WARNING, NIT."
            ),
            llm_provider=llm_provider,
            tool_registry=tool_registry,
        )


        # Basic review dispatch
        task_prompt = f"Perform code review for: {user_request}"
        try:
            review_task = reviewer.run(task_prompt)
            output = getattr(review_task, "output", str(review_task))
            step_results.append({"step": "code_review_dispatch", "status": "completed"})
            return SkillExecutionResult(
                skill_name=self.name,
                success=True,
                output=output,
                step_results=step_results,
            )

        except Exception as err:
            logger.error(f"CodeReviewSkill execution error: {err}")
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output="",
                error=str(err),
                step_results=step_results,
            )
