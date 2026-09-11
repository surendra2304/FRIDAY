"""Tests for Continuous Learning Instinct Engine in FRIDAY.

Validates:
1. Instinct creation, confidence score adjustments (reinforce and penalize).
2. Learn from feedback logic.
3. Context-sensitive instinct recall.
4. Prompt guidelines formatting.
5. Disk persistence, JSON export, and import.
6. Integration into CognitiveIntelligenceEngine.
"""

from pathlib import Path

from friday.agent.cognitive import CognitiveIntelligenceEngine, CognitivePhase
from friday.learning.instinct_engine import Instinct, InstinctEngine


def test_instinct_model_reinforce_and_penalize():
    instinct = Instinct(
        id="test-instinct",
        trigger="when running tests",
        action="use pytest with short traceback",
        confidence=0.5,
        domain="testing",
    )
    assert instinct.confidence == 0.5

    # Reinforce
    instinct.reinforce("Test passed smoothly")
    assert instinct.confidence == 0.6
    assert len(instinct.evidence) == 1

    # Penalize
    instinct.penalize("Failed with syntax error")
    assert instinct.confidence == 0.45


def test_instinct_engine_learn_from_feedback(tmp_path: Path):
    storage = str(tmp_path / "instincts.json")
    engine = InstinctEngine(storage_path=storage)

    inst1 = engine.learn_from_feedback(
        trigger="writing async functions",
        action="prefer asyncio.gather with return_exceptions=True",
        domain="code-style",
        outcome="success",
        evidence_note="Observed clean async error handling",
    )
    assert inst1.confidence == 0.6
    assert inst1.domain == "code-style"

    # Repeated success reinforces
    inst1_updated = engine.learn_from_feedback(
        trigger="writing async functions",
        action="prefer asyncio.gather with return_exceptions=True",
        domain="code-style",
        outcome="success",
    )
    assert inst1_updated.confidence == 0.7


def test_instinct_recall_and_formatting(tmp_path: Path):
    storage = str(tmp_path / "instincts.json")
    engine = InstinctEngine(storage_path=storage)

    engine.learn_from_feedback(
        trigger="writing sqlite queries",
        action="always use parameter binding to prevent injection",
        domain="database",
        outcome="success",
    )
    engine.learn_from_feedback(
        trigger="writing python tests",
        action="use fixtures for temporary filesystem directories",
        domain="testing",
        outcome="success",
    )

    # Recall database instinct
    recalled_db = engine.recall_instincts("I need to write a sqlite query to store memory records")
    assert len(recalled_db) >= 1
    assert recalled_db[0].domain == "database"
    assert "parameter binding" in recalled_db[0].action

    # Format guidelines for prompt injection
    guidelines = engine.format_guidelines_for_prompt(recalled_db)
    assert "[Learned Behavioral Instincts]:" in guidelines
    assert "DATABASE" in guidelines
    assert "parameter binding" in guidelines


def test_instinct_persistence_and_export_import(tmp_path: Path):
    storage = str(tmp_path / "instincts.json")
    engine = InstinctEngine(storage_path=storage)

    engine.learn_from_feedback(
        trigger="handling network timeouts",
        action="apply exponential backoff with jitter",
        domain="networking",
        outcome="success",
    )

    # Verify persisted to disk
    assert Path(storage).exists()

    # Load in fresh engine
    engine2 = InstinctEngine(storage_path=storage)
    assert len(engine2.list_instincts()) == 1
    assert engine2.list_instincts()[0].id.startswith("networking-")

    # Export
    export_path = str(tmp_path / "export.json")
    assert engine2.export_to_json(export_path) is True
    assert Path(export_path).exists()

    # Import into third engine
    engine3 = InstinctEngine(storage_path=str(tmp_path / "engine3.json"))
    assert len(engine3.list_instincts()) == 0
    imported = engine3.import_from_json(export_path)
    assert imported == 1
    assert len(engine3.list_instincts()) == 1


def test_cognitive_engine_instinct_integration(tmp_path: Path):
    storage = str(tmp_path / "instincts.json")
    engine = InstinctEngine(storage_path=storage)
    engine.learn_from_feedback(
        trigger="modifying git branches",
        action="confirm working tree is clean first",
        domain="git",
        outcome="success",
    )

    cognitive = CognitiveIntelligenceEngine(instinct_engine=engine)
    decision = cognitive.evaluate_request("Please help me modify git branches for issue 42")

    assert decision.current_phase in (CognitivePhase.PLAN, CognitivePhase.CLARIFY)
    assert len(decision.recalled_instincts) >= 1
    assert decision.recalled_instincts[0].domain == "git"
