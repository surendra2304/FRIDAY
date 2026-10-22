"""Unit tests for TaskGraph, TaskStep, and topological DAG operations."""

import pytest
from friday.planning.types import (
    RetryPolicy,
    TaskDataType,
    TaskGraph,
    TaskGraphValidationError,
    TaskStatus,
    TaskStep,
)


def test_task_graph_acyclic_waves():
    """Test that independent tasks are grouped into parallel waves and dependencies are respected."""
    # Graph structure:
    #   t1 -> t3
    #   t2 -> t3 -> t4
    t1 = TaskStep(id="t1", description="Fetch data 1")
    t2 = TaskStep(id="t2", description="Fetch data 2")
    t3 = TaskStep(id="t3", description="Merge data", dependencies=["t1", "t2"])
    t4 = TaskStep(id="t4", description="Format output", dependencies=["t3"])

    graph = TaskGraph(goal="Merge and format", tasks=[t1, t2, t3, t4])
    assert graph.detect_cycles() is None

    waves = graph.compute_waves()
    assert len(waves) == 3

    # Wave 0: t1 and t2 can run concurrently
    wave_0_ids = {t.id for t in waves[0]}
    assert wave_0_ids == {"t1", "t2"}

    # Wave 1: t3
    assert [t.id for t in waves[1]] == ["t3"]

    # Wave 2: t4
    assert [t.id for t in waves[2]] == ["t4"]


def test_task_graph_cycle_detection():
    """Test that circular dependencies are identified and rejected."""
    t1 = TaskStep(id="t1", description="Task 1", dependencies=["t3"])
    t2 = TaskStep(id="t2", description="Task 2", dependencies=["t1"])
    t3 = TaskStep(id="t3", description="Task 3", dependencies=["t2"])

    graph = TaskGraph(goal="Cyclic task", tasks=[t1, t2, t3])
    cycles = graph.detect_cycles()
    assert cycles is not None
    assert set(cycles) == {"t1", "t2", "t3"}

    with pytest.raises(TaskGraphValidationError):
        graph.compute_waves()


def test_task_graph_input_interpolation():
    """Test data passing between upstream task outputs and downstream task inputs."""
    t1 = TaskStep(id="step_a", description="Generate file name")
    t2 = TaskStep(
        id="step_b",
        description="Write content",
        dependencies=["step_a"],
        parameters={
            "filename": "<step_a>",
            "path": "/tmp/{{step_a}}",
            "nested": {"target": "{{step_a.result}}"},
        },
    )

    graph = TaskGraph(goal="Data passing", tasks=[t1, t2])
    graph.mark_completed("step_a", result="report.pdf")

    resolved = graph.resolve_inputs_for_task("step_b")
    assert resolved["filename"] == "report.pdf"
    assert resolved["path"] == "/tmp/report.pdf"
    assert resolved["nested"]["target"] == "report.pdf"


def test_task_graph_cascade_skip():
    """Test that failure in an upstream step cascades SKIPPED to all dependent steps."""
    t1 = TaskStep(id="t1", description="Download source")
    t2 = TaskStep(id="t2", description="Compile source", dependencies=["t1"])
    t3 = TaskStep(id="t3", description="Package binary", dependencies=["t2"])
    t4 = TaskStep(id="t4", description="Independent log task")

    graph = TaskGraph(goal="Build workflow", tasks=[t1, t2, t3, t4])
    graph.mark_failed("t1", error="Download timed out")
    skipped = graph.skip_downstream("t1", reason="Download timed out")

    assert set(skipped) == {"t2", "t3"}
    assert graph.get_task("t2").status == TaskStatus.SKIPPED
    assert graph.get_task("t3").status == TaskStatus.SKIPPED
    assert graph.get_task("t4").status == TaskStatus.PENDING


def test_task_graph_subgraph_replacement():
    """Test dynamic subgraph replacement when replanning a failed step."""
    t1 = TaskStep(id="t1", description="Initial preparation")
    t2 = TaskStep(id="t2", description="Primary query", dependencies=["t1"])
    t3 = TaskStep(id="t3", description="Final processing", dependencies=["t2"])

    graph = TaskGraph(goal="Replanning test", tasks=[t1, t2, t3])

    # Replace t2 with two alternative subtasks: alt_2a -> alt_2b
    alt_2a = TaskStep(id="alt_2a", description="Alternative query A")
    alt_2b = TaskStep(id="alt_2b", description="Alternative query B", dependencies=["alt_2a"])

    graph.replace_subgraph(failed_task_id="t2", replacement_tasks=[alt_2a, alt_2b])

    assert "t2" not in graph.tasks
    assert "alt_2a" in graph.tasks
    assert "alt_2b" in graph.tasks

    # alt_2a should inherit t1 dependency
    assert "t1" in graph.get_task("alt_2a").dependencies

    # t3 should now depend on alt_2b instead of t2
    assert "alt_2b" in graph.get_task("t3").dependencies
    assert "t2" not in graph.get_task("t3").dependencies

    # Valid acyclic schedule should still compute
    waves = graph.compute_waves()
    assert len(waves) == 4
    assert [t.id for t in waves[0]] == ["t1"]
    assert [t.id for t in waves[1]] == ["alt_2a"]
    assert [t.id for t in waves[2]] == ["alt_2b"]
    assert [t.id for t in waves[3]] == ["t3"]


def test_task_graph_serialization_roundtrip():
    """Test serializing TaskGraph to dict and deserializing back."""
    t1 = TaskStep(
        id="task_1",
        description="Search documentation",
        input_types=[TaskDataType.TEXT],
        output_type=TaskDataType.JSON,
        selected_executor="web_search",
        priority=2,
        retry_policy=RetryPolicy(max_retries=5, backoff_factor=2.0),
    )
    graph = TaskGraph(goal="Documentation search", tasks=[t1], metadata={"env": "test"})
    graph.mark_completed("task_1", result={"found": True})

    data = graph.to_dict()
    restored = TaskGraph.from_dict(data)

    assert restored.goal == graph.goal
    assert restored.graph_id == graph.graph_id
    assert len(restored.tasks) == 1
    r_task = restored.get_task("task_1")
    assert r_task is not None
    assert r_task.description == "Search documentation"
    assert r_task.status == TaskStatus.COMPLETED
    assert r_task.result == {"found": True}
    assert r_task.retry_policy.max_retries == 5
