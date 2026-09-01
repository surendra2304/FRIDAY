"""Regression and Anti-Tampering Test Suite for Real-World Acceptance Architecture.

Proves that:
1. No hardcoded success variables (mic_success=True, etc.) exist in acceptance tests.
2. Hardware unavailability strictly resolves to BLOCKED, never falsely PASS.
3. Software logic is strictly classified as SOFTWARE_PASS.
4. Mocks are strictly classified as SIMULATED_PASS and cannot masquerade as REAL_PASS.
5. All required outcome classifications (REAL_PASS, SOFTWARE_PASS, SIMULATED_PASS, BLOCKED, FAIL, NOT_TESTED) exist.
"""

import ast
from pathlib import Path

import tests.real_world_acceptance_test as acceptance_module
from tests.real_world_acceptance_test import (
    GenuineAcceptanceRunner,
    OutcomeClassification,
)


def test_no_hardcoded_placeholder_variables_in_acceptance_test():
    """AST regression test: Assert zero dummy/hardcoded success variables exist in acceptance test."""
    test_file = Path(__file__).resolve().parent / "real_world_acceptance_test.py"
    assert test_file.exists()

    with open(test_file, "r", encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source, filename=str(test_file))

    prohibited_names = {
        "mic_success",
        "voice_success",
        "screen_success",
        "grounding_success",
        "planning_success",
        "verification_success",
        "stale_detected",
        "ambiguous_handled",
        "cancelled",
        "authorized",
    }

    found_prohibited_assignments = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if target.id in prohibited_names:
                        found_prohibited_assignments.append((target.id, node.lineno))

    assert len(found_prohibited_assignments) == 0, (
        f"Found prohibited hardcoded placeholder assignments in acceptance test: {found_prohibited_assignments}"
    )


def test_no_simulated_dummy_exceptions_in_acceptance_test():
    """AST regression test: Assert no dummy `raise RuntimeError('Simulated...')` stubs exist."""
    test_file = Path(__file__).resolve().parent / "real_world_acceptance_test.py"
    with open(test_file, "r", encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source, filename=str(test_file))

    dummy_raises = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise):
            if isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name):
                if node.exc.args and isinstance(node.exc.args[0], ast.Constant):
                    val = str(node.exc.args[0].value)
                    if "simulated" in val.lower():
                        dummy_raises.append((val, node.lineno))

    assert len(dummy_raises) == 0, f"Found dummy simulated raise stubs in acceptance test: {dummy_raises}"


def test_outcome_classification_taxonomy_completeness():
    """Verify all 6 required outcome classifications are present in OutcomeClassification."""
    required_states = {
        "REAL_PASS",
        "SOFTWARE_PASS",
        "SIMULATED_PASS",
        "BLOCKED",
        "FAIL",
        "NOT_TESTED",
    }
    actual_states = {c.value for c in OutcomeClassification}
    assert required_states.issubset(actual_states), f"Missing required classifications: {required_states - actual_states}"


def test_hardware_unavailability_never_returns_pass(monkeypatch):
    """Prove that when audio input device is missing, microphone test returns BLOCKED, never PASS."""
    runner = GenuineAcceptanceRunner()

    # Force check_device_availability in acceptance_module to return False
    monkeypatch.setattr(
        acceptance_module,
        "check_device_availability",
        lambda device_type="input": (False, "Simulated hardware unplugged"),
    )

    result = runner.evaluate_microphone_capture()
    assert result.actual_classification == OutcomeClassification.BLOCKED
    assert result.actual_classification != OutcomeClassification.REAL_PASS
    assert result.actual_classification != OutcomeClassification.SOFTWARE_PASS
    assert "BLOCKED" in result.details


def test_simulated_mock_is_never_classified_as_real_pass():
    """Prove that mock adapters produce SIMULATED_PASS, preventing silent simulation."""
    runner = GenuineAcceptanceRunner()
    result = runner.evaluate_anti_simulation_boundary()
    assert result.actual_classification == OutcomeClassification.SIMULATED_PASS
    assert result.actual_classification != OutcomeClassification.REAL_PASS


def test_genuine_safety_gate_blocks_destructive_commands():
    """Prove that safety gate blocks dangerous commands and classifies as SOFTWARE_PASS."""
    runner = GenuineAcceptanceRunner()
    result = runner.evaluate_safety_hard_blocks()
    assert result.actual_classification == OutcomeClassification.SOFTWARE_PASS
    assert "Hard blocks" in result.details
