"""Comprehensive unit test suite for Goal Understanding: Autonomous Goal Understanding & Decomposition.

Tests:
1. Simple informational goals (read-only queries, low risk, single subgoal).
2. Complex multi-step requests with hierarchical subgoal decomposition and DAG dependencies.
3. Computer-control requests (classified as COMPUTER_CONTROL_REQUEST, high risk, requires auth/confirmation).
4. Long-running background requests (classified as LONG_RUNNING_TASK).
5. Ambiguous / underspecified requests triggering explicit clarification prompts.
6. Conflicting constraints detection (e.g. read-only vs write).
7. Prohibited / dangerous requests (blocked with CRITICAL risk, refusal outcome).
8. Multimodal context and secret redaction isolation.
9. Serialization and deserialization of Goal and SubGoal models.
10. Provider independence with MockLLMProvider.
"""


from friday.agent.goal import (
    Goal,
    GoalRequestType,
    GoalRiskLevel,
    GoalUnderstandingEngine,
)
from friday.llm.mock_provider import MockLLMProvider


# 1. Simple Informational Goals
def test_simple_information_goal_analysis():
    """Verify read-only questions are parsed into low-risk INFORMATION_REQUEST goals."""
    engine = GoalUnderstandingEngine()
    goal = engine.analyze_goal("What time is it right now in Tokyo?")

    assert goal.request_type == GoalRequestType.INFORMATION_REQUEST
    assert goal.risk_level == GoalRiskLevel.LOW
    assert goal.is_ambiguous is False
    assert goal.is_prohibited is False
    assert len(goal.subgoals) == 1
    assert "time" in goal.normalized_intent.lower()
    assert "USER_CONFIRMATION_REQUIRED" not in goal.authorization_requirements


# 2. Complex Multi-Step Goals & Hierarchical Decomposition
def test_complex_multi_step_goal_decomposition():
    """Verify compound goals decompose into dependency-linked subgoals."""
    engine = GoalUnderstandingEngine()
    request = "Read data.json then calculate total sales and then search memory for previous targets"
    goal = engine.analyze_goal(request)

    assert goal.request_type == GoalRequestType.MULTI_STEP_TASK
    assert len(goal.subgoals) == 3
    assert goal.subgoals[0].subgoal_id == "subgoal_1"
    assert goal.subgoals[1].dependencies == ["subgoal_1"]
    assert goal.subgoals[2].dependencies == ["subgoal_2"]
    assert "data.json" in goal.subgoals[0].description
    assert "calculate" in goal.subgoals[1].description


# 3. Computer Control Request Classification & Gating
def test_computer_control_request_classification():
    """Verify UI interaction requests are tagged high-risk and require user confirmation."""
    engine = GoalUnderstandingEngine()
    goal = engine.analyze_goal("Click the Submit button in Chrome")

    assert goal.request_type == GoalRequestType.COMPUTER_CONTROL_REQUEST
    assert goal.risk_level == GoalRiskLevel.HIGH
    assert "USER_CONFIRMATION_REQUIRED" in goal.authorization_requirements
    assert len(goal.subgoals) == 2
    assert goal.subgoals[0].required_capabilities == ["screen_capture", "ui_grounding"]
    assert goal.subgoals[1].requires_confirmation is True


# 4. Long-Running Background Tasks
def test_long_running_task_classification():
    """Verify monitoring tasks are categorized as LONG_RUNNING_TASK with background authorization."""
    engine = GoalUnderstandingEngine()
    goal = engine.analyze_goal("Monitor server logs and keep checking for 500 errors in background")

    assert goal.request_type == GoalRequestType.LONG_RUNNING_TASK
    assert goal.risk_level == GoalRiskLevel.MEDIUM
    assert "BACKGROUND_EXECUTION_AUTHORIZED" in goal.authorization_requirements
    assert len(goal.subgoals) == 2


# 5. Ambiguous & Underspecified Requests
def test_ambiguous_request_triggers_clarification():
    """Verify ambiguous requests ask for user clarification instead of guessing."""
    engine = GoalUnderstandingEngine()
    goal = engine.analyze_goal("do it")

    assert goal.request_type == GoalRequestType.AMBIGUOUS_REQUEST
    assert goal.is_ambiguous is True
    assert goal.clarification_needed is not None
    assert "clarify" in goal.clarification_needed.lower() or "ambiguous" in goal.clarification_needed.lower()


# 6. Conflicting Constraints Detection
def test_conflicting_constraints_detection():
    """Verify contradictory instructions generate clarification requests."""
    engine = GoalUnderstandingEngine()
    goal = engine.analyze_goal("In read-only mode, please overwrite output.txt with new data")

    assert goal.request_type == GoalRequestType.AMBIGUOUS_REQUEST
    assert goal.is_ambiguous is True
    assert "READ_ONLY_MODE" in goal.constraints
    assert "contradictory" in goal.clarification_needed.lower()


# 7. Prohibited & Dangerous Requests
def test_prohibited_request_refusal():
    """Verify destructive/malicious requests are blocked with CRITICAL risk."""
    engine = GoalUnderstandingEngine()
    goal = engine.analyze_goal("Format C: drive and delete System32")

    assert goal.request_type == GoalRequestType.PROHIBITED_REQUEST
    assert goal.risk_level == GoalRiskLevel.CRITICAL
    assert goal.is_prohibited is True
    assert "HARD_BLOCKED" in goal.authorization_requirements
    assert "Refusal" in goal.desired_outcome


# 8. Secret Redaction in Goal Requests
def test_secret_redaction_in_goal_parsing():
    """Verify secrets inside user requests are redacted during goal formulation."""
    engine = GoalUnderstandingEngine()
    fake_key = "AIza" + "Sy" + "D12345678901234567890123456789012"
    dirty_req = f"Save api_key: {fake_key} and password: SuperPassword99 to credentials.txt"

    goal = engine.analyze_goal(dirty_req)

    assert fake_key not in goal.original_request
    assert "SuperPassword99" not in goal.original_request
    assert "[REDACTED_PASSWORD]" in goal.original_request


# 9. Serialization & Deserialization
def test_goal_serialization_roundtrip():
    """Verify Goal and SubGoal objects serialize and deserialize losslessly."""
    engine = GoalUnderstandingEngine()
    original_goal = engine.analyze_goal("Check disk space then compile binary within 5 minutes")

    goal_dict = original_goal.to_dict()
    assert isinstance(goal_dict, dict)
    assert goal_dict["request_type"] == GoalRequestType.MULTI_STEP_TASK.value
    assert "MAX_TIMEOUT: 5 minutes" in goal_dict["constraints"]

    restored_goal = Goal.from_dict(goal_dict)
    assert restored_goal.goal_id == original_goal.goal_id
    assert restored_goal.request_type == original_goal.request_type
    assert restored_goal.risk_level == original_goal.risk_level
    assert len(restored_goal.subgoals) == len(original_goal.subgoals)


# 10. Provider Independence with MockLLM
def test_provider_independence_offline_operation():
    """Verify GoalUnderstandingEngine operates 100% offline with MockLLMProvider."""
    mock_llm = MockLLMProvider()
    engine = GoalUnderstandingEngine(llm_provider=mock_llm)

    goal = engine.analyze_goal("List files in current directory")
    assert goal.request_type == GoalRequestType.INFORMATION_REQUEST
    assert goal.risk_level == GoalRiskLevel.LOW
