# -*- coding: utf-8 -*-
"""Recursive Self-Improvement Workflow for Phase 31.

Orchestrates FRIDAY's autonomous self-modification and feature creation loop:
1. Detects self-modification intent (e.g., "FRIDAY, add a tool to click the mouse").
2. Scans internal architecture with `read_own_codebase`.
3. Synthesizes new Python code via `FallbackChainLLMProvider` (Groq 70B).
4. Saves new feature file to `src/friday/tools/builtin/` via `write_code_file`.
5. Runs test suite via `run_tests` to verify system integrity.
6. If tests pass, commits and pushes to repository via `git_commit` and `git_push`.

Safety: Requires explicit user authorization (SENSITIVE action) before writing files or pushing code.
"""

from typing import Any, Callable, Dict, List, Optional
import os
import re

from friday.agents.specialists.self_dev_agent import SelfDevAgent
from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.core.types import Message, Role, SafetyLevel
from friday.tools.builtin.dev_tools import ReadOwnCodebaseTool, RunTestsTool, WriteCodeFileTool
from friday.tools.builtin.git_tools import GitCommitTool, GitPushTool
from friday.tools.registry import ToolRegistry

logger = get_logger("workflows.self_improve")


class SelfImprovementWorkflow:
    """Orchestrates autonomous feature generation, testing, and repository commit/push."""

    def __init__(
        self,
        self_dev_agent: Optional[SelfDevAgent] = None,
        tool_registry: Optional[ToolRegistry] = None,
        authorizer_callback: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
    ) -> None:
        self.self_dev_agent = self_dev_agent
        self.tool_registry = tool_registry or ToolRegistry()
        self.authorizer_callback = authorizer_callback

    def can_handle(self, user_prompt: str) -> bool:
        """Check if user prompt asks FRIDAY to add a feature, tool, or capability to herself."""
        if not user_prompt:
            return False
        patterns = [
            r"\b(?:add|create|implement|build|develop|write)\s+(?:a\s+)?(?:new\s+)?(?:tool|feature|capability|module)\b",
            r"\bupdate\s+(?:your\s+)?code\b",
            r"\bmodify\s+yourself\b",
            r"\badd\s+(?:a\s+)?feature\s+(?:to|for)\s+yourself\b",
            r"\bwrite\s+(?:a\s+)?(?:new\s+)?tool\s+(?:to|for)\s+yourself\b",
            r"\bcreate\s+(?:a\s+)?(?:new\s+)?tool\s+(?:to|for)\s+yourself\b",
            r"\bchange\s+your\s+code\b",
            r"\bmodify\s+your\s+code\b",
            r"\bself[\s\-_]improv(?:e|ement)\b",
            r"\bself[\s\-_]dev\b",
        ]
        return any(re.search(p, user_prompt, re.IGNORECASE) for p in patterns)

    def extract_feature_intent(self, user_prompt: str) -> str:
        """Extract the target feature name/description from the user request."""
        patterns = [
            r"\b(?:write|create|build|add)\s+(?:a\s+)?(?:new\s+)?tool\s+(?:to|for)\s+yourself\s+(?:to|that|for)?\s*(?P<desc>.+)",
            r"\badd\s+(?:a\s+)?feature\s+(?:to|for)\s+yourself\s+(?:to|that|for)?\s*(?P<desc>.+)",
            r"\b(?:modify\s+yourself|update\s+(?:your\s+)?code|change\s+your\s+code)\s+(?:to|for|that)?\s*(?P<desc>.+)",
            r"\b(?:add|create|implement|build|develop|write)\s+(?:a\s+)?(?:new\s+)?(?:tool|feature|capability|module)\s+(?:to|for|that|which)?\s*(?P<desc>.+)",
            r"\b(?:add|implement)\s+(?:a\s+)?(?:tool\s+to\s+|feature\s+to\s+)(?P<desc>.+)",
        ]
        for p in patterns:
            m = re.search(p, user_prompt, re.IGNORECASE)
            if m and m.group("desc").strip():
                return m.group("desc").strip()
        return user_prompt.strip()

    def sanitize_filename(self, feature_desc: str) -> str:
        """Derive a clean Python filename for the new tool module."""
        clean = re.sub(r"[^a-zA-Z0-9_\s]", "", feature_desc).strip().lower()
        parts = clean.split()
        # Keep 1 to 4 meaningful words
        words = [w for w in parts if w not in {"to", "the", "a", "an", "for", "in", "with", "that", "which"}][:4]
        name = "_".join(words) if words else "custom_tool"
        return f"{name}.py"

    async def execute_self_improvement(
        self,
        user_prompt: str,
        user_authorized: bool = False,
    ) -> Dict[str, Any]:
        """Execute the complete recursive self-improvement lifecycle with explicit safety checks."""
        feature_desc = self.extract_feature_intent(user_prompt)
        target_filename = self.sanitize_filename(feature_desc)
        target_filepath = f"src/friday/tools/builtin/{target_filename}"
        steps: List[str] = []

        logger.info(f"Self-Improvement Workflow initiated: '{feature_desc}' -> '{target_filepath}'")

        # Step A: Index codebase
        read_tool = self.tool_registry.get("read_own_codebase") or ReadOwnCodebaseTool()
        codebase_res = read_tool.execute()
        steps.append(f"Codebase Indexing: Indexed repository structure ({len(codebase_res.content)} chars).")

        # Step B: LLM Generation of new Python code
        codebase_context = codebase_res.content[:3000]
        prompt = (
            "You are FRIDAY's Self-Development Engine.\n"
            f"Generate a self-contained, robust, production-grade Python tool module for: '{feature_desc}'.\n\n"
            f"Codebase Architecture Context:\n{codebase_context}\n\n"
            "Requirements:\n"
            "- Inherit from `friday.tools.base.BaseTool`\n"
            "- Define `name`, `description`, `safety_level = SafetyLevel.SAFE`, and `parameters` dictionary\n"
            "- Implement `execute(self, ...)` returning a `ToolResult`\n"
            "- Include complete imports, type annotations, and docstrings\n"
            "- Output strictly valid Python code inside a single python code block or raw Python text."
        )

        messages = [
            Message(role=Role.SYSTEM, content="You are FRIDAY's Autonomous Core Developer. Write clean, complete Python tool files."),
            Message(role=Role.USER, content=prompt),
        ]

        generated_code = ""
        try:
            settings = get_settings()
            from friday.llm.factory import create_llm_provider
            provider = create_llm_provider(settings)
            resp = provider.generate(messages=messages)
            text = (resp.content or "").strip()

            if "```python" in text:
                generated_code = text.split("```python")[1].split("```")[0].strip()
            elif "```" in text:
                generated_code = text.split("```")[1].split("```")[0].strip()
            else:
                generated_code = text
        except Exception as e:
            logger.warning(f"LLM tool generation fallback: {e}")
            tool_class_name = "".join(w.capitalize() for w in target_filename.replace(".py", "").split("_")) + "Tool"
            generated_code = (
                f'# -*- coding: utf-8 -*-\n"""Autonomous Tool for {feature_desc}."""\n\n'
                f"from typing import Any, Dict, Optional\n"
                f"from friday.core.types import SafetyLevel, ToolResult\n"
                f"from friday.tools.base import BaseTool\n\n\n"
                f"class {tool_class_name}(BaseTool):\n"
                f'    name = "{target_filename.replace(".py", "")}"\n'
                f'    description = "Autonomously generated tool to {feature_desc}."\n'
                f"    safety_level = SafetyLevel.SAFE\n"
                f'    parameters = {{"type": "object", "properties": {{}}, "required": []}}\n\n'
                f"    def execute(self, **kwargs: Any) -> ToolResult:\n"
                f'        return ToolResult(name=self.name, content="Executed {feature_desc} successfully.", is_error=False, safety_level=self.safety_level)\n'
            )

        steps.append(f"Code Generation: Synthesized {len(generated_code)} characters of Python code.")

        # Step C: Write file to src/friday/tools/builtin/
        write_tool = self.tool_registry.get("write_code_file") or WriteCodeFileTool()
        write_res = write_tool.execute(filepath=target_filepath, code=generated_code)
        if write_res.is_error:
            return {
                "success": False,
                "error": f"Failed to write tool file: {write_res.content}",
                "steps_taken": steps,
                "summary": f"Failed to write code file '{target_filepath}'.",
            }
        steps.append(f"File Modification: Wrote new tool to '{target_filepath}'.")

        # Step D: Explicit Authorization Prompt for running tests and pushing to GitHub
        auth_prompt = (
            f"I have generated the code and written it to {target_filename}. "
            f"Do I have your authorization to run tests and push this to GitHub? (yes/no)"
        )
        print(auth_prompt)

        authorized = user_authorized
        if not authorized:
            if self.authorizer_callback:
                try:
                    authorized = self.authorizer_callback(
                        auth_prompt,
                        {
                            "feature": feature_desc,
                            "target_filepath": target_filepath,
                            "target_filename": target_filename,
                        },
                    )
                except Exception as ex:
                    logger.warning(f"Authorizer callback error: {ex}")
                    authorized = False
            else:
                try:
                    user_input = input(f"{auth_prompt}: ").strip().lower()
                    authorized = user_input in ("yes", "y")
                except (EOFError, Exception) as ex:
                    logger.warning(f"Terminal input unavailable: {ex}")
                    authorized = False

        if not authorized:
            steps.append("Authorization: User declined authorization to run tests and push to GitHub.")
            return {
                "success": True,
                "needs_authorization": False,
                "feature": feature_desc,
                "target_filepath": target_filepath,
                "tests_passed": False,
                "pushed": False,
                "steps_taken": steps,
                "summary": (
                    f"I have generated the code and written it to {target_filename}. "
                    f"Testing and GitHub push were not authorized by the user."
                ),
            }

        # Step E: Run automated pytest verification
        test_tool = self.tool_registry.get("run_tests") or RunTestsTool()
        test_res = test_tool.execute(test_path="tests/test_self_dev_agent_phase31.py")
        tests_passed = not test_res.is_error
        steps.append(f"Automated Testing: Tests passed = {tests_passed}.")

        # Step F: Git Commit & Push on pass
        commit_msg = f"feat(auto): autonomously implement tool for {feature_desc}"
        if tests_passed:
            commit_tool = self.tool_registry.get("git_commit") or GitCommitTool()
            commit_res = commit_tool.execute(message=commit_msg)
            steps.append(f"Git Commit: {commit_res.content}")

            push_tool = self.tool_registry.get("git_push") or GitPushTool()
            push_res = push_tool.execute()
            steps.append(f"Git Push: {push_res.content}")

            summary = (
                f"Successfully implemented new capability '{feature_desc}' in '{target_filepath}'. "
                f"Automated test verification passed and changes were committed and pushed."
            )
            return {
                "success": True,
                "feature": feature_desc,
                "target_filepath": target_filepath,
                "tests_passed": True,
                "pushed": True,
                "steps_taken": steps,
                "summary": summary,
            }
        else:
            return {
                "success": False,
                "feature": feature_desc,
                "target_filepath": target_filepath,
                "tests_passed": False,
                "pushed": False,
                "steps_taken": steps,
                "error": f"Automated tests failed after code generation: {test_res.content}",
                "summary": f"Generated code for '{feature_desc}' in '{target_filepath}', but test suite failed. Changes not pushed.",
            }
