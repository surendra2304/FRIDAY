import pytest
from friday_deep.contracts import PlanEnvelope, PlanNode
from friday_deep.planning.validator import validate_plan, PlanValidationError
from friday_deep.planning.waves import build_waves


def n(i, deps=()):
    return PlanNode(i, i, "do " + i, "general", tuple(deps))


def test_valid():
    p = PlanEnvelope("g", "p", [n("a"), n("b", ("a",))])
    validate_plan(p)
    assert [w.node_ids for w in build_waves(p.nodes)] == [("a",), ("b",)]


def test_unknown():
    with pytest.raises(PlanValidationError):
        validate_plan(PlanEnvelope("g", "p", [n("a", ("x",))]))


def test_cycle():
    with pytest.raises(PlanValidationError):
        validate_plan(PlanEnvelope("g", "p", [n("a", ("b",)), n("b", ("a",))]))


def test_self():
    with pytest.raises(PlanValidationError):
        validate_plan(PlanEnvelope("g", "p", [n("a", ("a",))]))
