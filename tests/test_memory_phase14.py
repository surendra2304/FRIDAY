"""Unit tests for Memory Knowledge Base Memory 2.0: 4-layer schema, bounded retrieval, compactor, and user controls."""

import json
import os

import pytest

from friday.core.types import Message, Role
from friday.llm.base import BaseLLMProvider
from friday.memory.compactor import MemoryCompactor
from friday.memory.sqlite import SQLiteConversationMemory


class MockCompactionLLM(BaseLLMProvider):
    def __init__(self, model: str = "mock-model"):
        super().__init__(model=model)

    @property
    def provider_name(self) -> str:
        return "mock_compactor"

    def generate(self, messages, tools=None):
        return Message(
            role=Role.ASSISTANT,
            content="- User prefers dark mode UI\n- User's primary coding language is Python\n- Project name is FRIDAY",
        )


def test_memory_nodes_four_types(tmp_path):
    db_file = str(tmp_path / "memory_2.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    # 1. Add 4 different memory types
    w_id = mem.add_memory_node(
        content="Current active calculation is 42",
        memory_type="working",
        importance=0.3,
    )
    e_id = mem.add_memory_node(
        content="User opened Notepad and wrote project notes",
        memory_type="episodic",
        importance=0.6,
    )
    s_id = mem.add_memory_node(
        content="User is a senior software architect",
        memory_type="semantic",
        importance=0.9,
    )
    t_id = mem.add_memory_node(
        content="Task #102 executed successfully in 1.2s",
        memory_type="task",
        importance=0.7,
    )

    assert w_id and e_id and s_id and t_id

    # 2. Retrieve by type
    working_nodes = mem.get_memory_nodes(memory_type="working")
    assert len(working_nodes) == 1
    assert "calculation is 42" in working_nodes[0]["content"]

    episodic_nodes = mem.get_memory_nodes(memory_type="episodic")
    assert len(episodic_nodes) == 1
    assert "Notepad" in episodic_nodes[0]["content"]

    semantic_nodes = mem.get_memory_nodes(memory_type="semantic")
    assert len(semantic_nodes) == 1
    assert semantic_nodes[0]["importance"] == 0.9

    mem.close()


def test_invalid_memory_type_raises(tmp_path):
    db_file = str(tmp_path / "invalid_type.db")
    mem = SQLiteConversationMemory(db_path=db_file)
    with pytest.raises(ValueError, match="Invalid memory_type"):
        mem.add_memory_node(content="Invalid", memory_type="invalid_type")
    mem.close()


def test_bounded_retrieval_fts5(tmp_path):
    db_file = str(tmp_path / "bounded.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    # Populate several memory nodes
    mem.add_memory_node(content="User likes dark theme in VSCode", memory_type="semantic", importance=0.8)
    mem.add_memory_node(content="User visited github repo yesterday", memory_type="episodic", importance=0.4)
    mem.add_memory_node(content="User requested system diagnostics run", memory_type="task", importance=0.5)
    mem.add_memory_node(content="Irrelevant random note", memory_type="episodic", importance=0.1)

    # Search for theme
    results = mem.search_bounded_memories(query="theme", top_k=2)
    assert len(results) >= 1
    assert "dark theme" in results[0]["content"]

    # Search with min_importance filter
    results_high_importance = mem.search_bounded_memories(query="User", min_importance=0.7)
    for r in results_high_importance:
        assert r["importance"] >= 0.7

    mem.close()


def test_memory_compactor(tmp_path):
    db_file = str(tmp_path / "compactor_test.db")
    mem = SQLiteConversationMemory(db_path=db_file)
    mock_llm = MockCompactionLLM()

    # Add episodic memories
    for i in range(5):
        mem.add_memory_node(
            content=f"User opened terminal and ran pytest session {i}",
            memory_type="episodic",
            importance=0.4,
        )

    compactor = MemoryCompactor(memory=mem, llm_provider=mock_llm, compaction_threshold=3)
    compacted_id = compactor.compact_episodic_memories(force=True)

    assert compacted_id is not None
    semantic_nodes = mem.get_memory_nodes(memory_type="semantic")
    assert len(semantic_nodes) == 1
    assert "Python" in semantic_nodes[0]["content"]
    assert semantic_nodes[0]["source"] == "compactor"

    mem.close()


def test_user_controls_deletion_and_export(tmp_path):
    db_file = str(tmp_path / "controls.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    node_id = mem.add_memory_node(content="Secret user note to delete", memory_type="working")
    assert len(mem.get_memory_nodes(memory_type="working")) == 1

    # Explicit deletion
    assert mem.delete_memory_node(node_id) is True
    assert len(mem.get_memory_nodes(memory_type="working")) == 0
    assert mem.delete_memory_node("non_existent_id") is False

    # Export
    mem.add_memory_node(content="Exportable preference", memory_type="semantic")
    export_file = str(tmp_path / "exported_memories.json")
    exported = mem.export_all_memories(target_path=export_file)

    assert os.path.exists(export_file)
    assert exported["memory_nodes_count"] == 1
    assert "Exportable preference" in json.dumps(exported)

    mem.close()
