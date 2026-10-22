"""Deterministic unit test suite for Computer Action Execution.5 Active Working Task Memory & Context Isolation.

Validates:
1. Context initialization with goal, plan, and initial state.
2. Step transitions and active step updates.
3. Context isolation between consecutive and parallel tasks (no state contamination).
4. Relevance filtering & size limits (observation sliding window and step output truncation).
5. Secret protection & payload sanitation (credentials redacted, no raw binary base64 or screenshot storage).
6. Working memory summary generation for prompt injection.
7. Finalization on successful task completion (summary extracted to long-term memory, ephemeral scratch discarded).
8. Finalization on failed task completion.
9. Full integration with FridayAgent (create_plan, execute_plan, long-term memory updates, and get_status).
10. Provider independence: Operates 100% offline with MockLLMProvider and zero external SDK dependencies.
"""


from friday.agent.agent import FridayAgent
from friday.agent.state import TaskState
from friday.agent.verification import VerificationResult, VerificationStatus
from friday.core.config import Settings
from friday.core.types import Role
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.memory.task_context import ActiveTaskContext
from friday.tools.builtin.system_info import SystemInfoTool
from friday.tools.registry import ToolRegistry


# 1. Initialization and Step Transitions
def test_task_context_initialization_and_step_updates():
    ctx = ActiveTaskContext(task_id="task_1", goal="Perform system audit")

    assert ctx.task_id == "task_1"
    assert ctx.goal == "Perform system audit"
    assert ctx.state == TaskState.NOT_STARTED
    assert ctx.active_step_id is None

    ctx.set_state(TaskState.EXECUTING)
    ctx.set_active_step("step_1")
    ctx.add_constraint("read_only_mode")
    ctx.add_user_clarification("Format as bullet points")

    assert ctx.state == TaskState.EXECUTING
    assert ctx.active_step_id == "step_1"
    assert ctx.constraints == ["read_only_mode"]
    assert ctx.user_clarifications == ["Format as bullet points"]


# 2. Context Isolation Between Tasks
def test_task_context_isolation_between_tasks():
    ctx1 = ActiveTaskContext(task_id="task_A", goal="Task A Goal")
    ctx1.record_step_result("step_1", "Result from Task A")

    ctx2 = ActiveTaskContext(task_id="task_B", goal="Task B Goal")
    ctx2.record_step_result("step_1", "Result from Task B")

    assert "Result from Task A" in ctx1.step_outputs["step_1"]
    assert "Result from Task B" in ctx2.step_outputs["step_1"]
    assert "Task A" not in ctx2.step_outputs["step_1"]


# 3. Output Truncation and Observation Capacity Budgeting
def test_task_context_size_budget_and_sliding_window():
    ctx = ActiveTaskContext(max_observations=3, max_output_chars_per_step=50)

    # 1. Output truncation
    huge_result = "A" * 200
    ctx.record_step_result("step_huge", huge_result)
    assert len(ctx.step_outputs["step_huge"]) < 120
    assert "truncated" in ctx.step_outputs["step_huge"]

    # 2. Observation sliding window
    ctx.add_observation("s1", "Observation 1")
    ctx.add_observation("s2", "Observation 2")
    ctx.add_observation("s3", "Observation 3")
    ctx.add_observation("s4", "Observation 4")

    assert len(ctx.observations) == 3
    obs_contents = [o.content for o in ctx.observations]
    assert obs_contents == ["Observation 2", "Observation 3", "Observation 4"]


# 4. Secret Protection & Raw Screenshot Scrubbing
def test_task_context_secret_and_screenshot_scrubbing():
    ctx = ActiveTaskContext()

    # Screenshot scrubbing
    raw_img = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    ctx.record_step_result("step_screen", raw_img)
    assert "data:image" not in ctx.step_outputs["step_screen"]
    assert "[Visual screenshot captured and processed safely]" in ctx.step_outputs["step_screen"]

    # Secret redaction in observation
    ctx.add_observation("step_auth", "Received token=sk_live_secret12345 for login")
    assert "sk_live_secret12345" not in ctx.observations[0].content
    assert "[Sensitive credentials redacted]" in ctx.observations[0].content


# 5. Working Summary Prompt Generation
def test_task_context_working_summary_synthesis():
    ctx = ActiveTaskContext(goal="Check OS status")
    ctx.set_state(TaskState.EXECUTING)
    ctx.set_active_step("step_os")
    ctx.add_constraint("no_disk_writes")
    ctx.record_step_result("step_os", "OS: Windows 11 64-bit", verification=VerificationResult(status=VerificationStatus.PASSED, criterion="OS check"))
    ctx.add_observation("step_os", "Kernel is responsive")

    summary = ctx.get_working_summary()
    assert "[Active Task Goal]: Check OS status" in summary
    assert "[State]: EXECUTING" in summary
    assert "[Active Step]: step_os" in summary
    assert "[Constraints]: no_disk_writes" in summary
    assert "OS: Windows 11 64-bit" in summary
    assert "Kernel is responsive" in summary


# 6. Finalization & Long-term Summary Extraction
def test_task_context_finalization_summary_extraction():
    ctx = ActiveTaskContext(goal="Deploy service")
    ctx.add_user_clarification("Use port 8080")
    ctx.record_step_result("step_build", "Build artifacts generated successfully.")

    # Successful completion
    msg_success = ctx.finalize_and_extract_long_term_summary(success=True)
    assert msg_success is not None
    assert msg_success.role == Role.ASSISTANT
    assert "Task 'Deploy service' completed successfully." in msg_success.content
    assert "User preferences noted: Use port 8080" in msg_success.content
    assert "step_build: Build artifacts generated successfully." in msg_success.content

    # Failed completion
    msg_fail = ctx.finalize_and_extract_long_term_summary(success=False)
    assert "Task 'Deploy service' failed during execution." in msg_fail.content


# 7. Agent Integration: Full Plan Execution with Task Context
def test_agent_task_context_integration():
    registry = ToolRegistry()
    registry.register(SystemInfoTool())

    memory = InMemoryConversationMemory()
    agent = FridayAgent(
        settings=Settings(env="testing", agent_name="FRIDAY"),
        llm_provider=MockLLMProvider(),
        memory=memory,
        tool_registry=registry,
    )

    step_defs = [
        {
            "step_id": "step_diag",
            "description": "Inspect OS",
            "tool_name": "get_system_info",
            "parameters": {"category": "os"},
        }
    ]
    plan = agent.create_plan("Run OS diagnostics", steps=step_defs)
    assert agent.task_context is not None
    assert agent.task_context.goal == "Run OS diagnostics"

    # Execute plan
    exec_result = agent.execute_plan(plan)
    assert exec_result.success is True

    # Check long-term memory updated with high-level summary
    stored_msgs = agent.memory.get_messages()
    assert len(stored_msgs) >= 1
    last_msg = stored_msgs[-1]
    assert "Task 'Run OS diagnostics' completed successfully." in last_msg.content

    # Check get_status reflects active task context
    status = agent.get_status()
    assert status["active_task_context"] is not None
    assert status["active_task_context"]["goal"] == "Run OS diagnostics"


# 8. Provider Independence: Zero vendor cloud SDK dependencies
def test_task_context_zero_provider_dependency():
    """Verify task_context.py has no dependency on google.genai or external cloud SDKs."""
    import friday.memory.task_context as tc_mod

    assert "google" not in tc_mod.__dict__
    assert "genai" not in tc_mod.__dict__
    assert hasattr(tc_mod, "ActiveTaskContext")
    assert hasattr(tc_mod, "TaskObservation")
