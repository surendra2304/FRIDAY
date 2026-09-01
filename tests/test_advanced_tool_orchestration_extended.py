"""Comprehensive unit test suite for Cognitive Task Planning.8: Advanced Tool Orchestration & Capability Routing.

Tests:
1. Capability discovery and deterministic tool selection scoring.
2. Dynamic parameter inference and multi-tool dependency chaining.
3. Unavailable tool routing and alternative tool fallbacks.
4. Tool safety disqualification under strict max_allowed_safety policies.
5. Untrusted screen / prompt injection defense preventing dynamic malicious tool creation or execution.
6. Multi-tool wave batching for DAG execution.
"""


from friday.agent.planner import PlanStep, TaskPlan
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool
from friday.tools.orchestrator import (
    CapabilityRouter,
    DataFlowResolver,
    ToolOrchestrator,
)
from friday.tools.registry import ToolRegistry


class DummySearchTool(BaseTool):
    name = "web_search"
    description = "Search the public web."
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    safety_level = SafetyLevel.SAFE

    def execute(self, query: str) -> ToolResult:
        return ToolResult(tool_call_id="", name=self.name, content=f"Results for '{query}'", safety_level=self.safety_level)


class DummyLocalSearchTool(BaseTool):
    name = "local_search"
    description = "Search local files."
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    safety_level = SafetyLevel.SAFE

    def execute(self, query: str) -> ToolResult:
        return ToolResult(tool_call_id="", name=self.name, content=f"Local matches for '{query}'", safety_level=self.safety_level)


class DummyDangerousCommandTool(BaseTool):
    name = "execute_command"
    description = "Execute system command."
    parameters = {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}
    safety_level = SafetyLevel.DANGEROUS

    def execute(self, command: str) -> ToolResult:
        return ToolResult(tool_call_id="", name=self.name, content=f"Executed: {command}", safety_level=self.safety_level)


# 1. Capability Discovery & Scoring
def test_capability_routing_scoring():
    reg = ToolRegistry()
    t1 = DummySearchTool()
    t2 = DummyLocalSearchTool()
    reg.register(t1)
    reg.register(t2)

    router = CapabilityRouter(tool_registry=reg)
    tool_name, rationale = router.route_capability("search")

    assert tool_name == "web_search"  # Primary candidate in capability map
    assert "Routed to 'web_search'" in rationale


# 2. Safety Level Disqualification
def test_safety_disqualification():
    reg = ToolRegistry()
    danger_tool = DummyDangerousCommandTool()
    reg.register(danger_tool)

    router = CapabilityRouter(tool_registry=reg)

    # When max_allowed_safety is SAFE, DANGEROUS tool must be rejected
    tool_name, err = router.route_capability("execute_command", max_allowed_safety=SafetyLevel.SAFE)
    assert tool_name is None
    assert "within safety limit 'SAFE'" in err

    # When max_allowed_safety is DANGEROUS, tool is allowed
    tool_name_ok, _ = router.route_capability("execute_command", max_allowed_safety=SafetyLevel.DANGEROUS)
    assert tool_name_ok == "execute_command"


# 3. Alternative Tool Fallback Routing
def test_alternative_tool_routing_fallback():
    reg = ToolRegistry()
    t2 = DummyLocalSearchTool()
    reg.register(t2)  # Only register fallback, not primary

    tool_fallbacks = {"web_search": "local_search"}
    router = CapabilityRouter(tool_registry=reg, tool_fallbacks=tool_fallbacks)

    tool_name, rationale = router.route_capability(
        "search",
        preferred_tool="web_search",
        available_tools_override=["local_search"],
    )

    assert tool_name == "local_search"
    assert "local_search" in rationale


# 4. Multi-Tool Parameter Inference & Data Flow
def test_multi_tool_data_flow():
    step_results = {
        "step_1": '{"url": "https://example.com/api", "status": "active"}',
        "step_2": "Processed data payload",
    }

    params = {
        "endpoint": "{{step_1.url}}",
        "body": "Prefix: {{step_2}}",
    }

    resolved, err = DataFlowResolver.resolve_parameters(params, step_results)
    assert err is None
    assert resolved["endpoint"] == "https://example.com/api"
    assert resolved["body"] == "Prefix: Processed data payload"


# 5. Untrusted Screen / Prompt Injection Defense
def test_malicious_capability_injection_defense():
    reg = ToolRegistry()
    router = CapabilityRouter(tool_registry=reg)

    # Malicious capability name containing arbitrary python code or commands
    tool_name, err = router.route_capability("eval(__import__('os').system('rm -rf'))")
    assert tool_name is None
    assert "Untrusted or invalid capability name" in err

    # Malicious command string injected into sensitive parameter template
    step_results = {"untrusted_screen_step": "format C: /y"}
    dangerous_params = {"command": "{{untrusted_screen_step}}"}
    resolved, err = DataFlowResolver.resolve_parameters(
        dangerous_params,
        step_results,
        target_safety_level=SafetyLevel.DANGEROUS,
    )
    assert resolved == dangerous_params
    assert "blocked from parameter interpolation" in err


# 6. Tool Orchestration Wave Scheduling
def test_tool_orchestration_batches():
    s1 = PlanStep(step_id="s1", description="Step 1", tool_name="t1")
    s2 = PlanStep(step_id="s2", description="Step 2", tool_name="t2")
    s3 = PlanStep(step_id="s3", description="Step 3", tool_name="t3", depends_on=["s1", "s2"])
    plan = TaskPlan(plan_id="p1", goal="Goal", steps=[s1, s2, s3])

    batches = ToolOrchestrator.compute_execution_batches(plan)
    assert len(batches) == 2
    assert set(s.step_id for s in batches[0]) == {"s1", "s2"}
    assert [s.step_id for s in batches[1]] == ["s3"]
