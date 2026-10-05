"""BUG-010: the loop's own repeat-guard notices were being recalled as memory.

Live evidence from the audit: recall for a brand-new question returned
``role: "tool"`` with ``content: "Error: Duplicate tool call ID 'tc1' ignored."``.
That string exists to stop a loop from repeating itself. It says nothing about
the world, and remembering it means every future question can surface a stale
error from an unrelated loop and consume recall budget with it.

These tests use the real SQLite store, the real write path, and the real search,
because the defect lived in the interaction between them - the vector index
already refused tool messages, and the lexical index did not.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from friday.core.types import Message, Role
from friday.memory.policies import is_non_informative_tool_notice
from friday.memory.sqlite import SQLiteConversationMemory


@pytest.fixture()
def memory(tmp_path: Path) -> SQLiteConversationMemory:
    return SQLiteConversationMemory(db_path=str(tmp_path / "memory.db"), conversation_id="c1")


def _stored_contents(db_path: Path) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT content FROM messages").fetchall()
    return [row[0] for row in rows]


def test_the_duplicate_id_notice_is_not_stored(memory, tmp_path: Path) -> None:
    notice = Message(
        role=Role.TOOL,
        name="call_loop",
        tool_call_id="tc1",
        content="Error: Duplicate tool call ID 'tc1' ignored.",
    )
    memory.add_message(notice)

    assert _stored_contents(tmp_path / "memory.db") == [], "the notice was written to memory"


def test_the_repeated_operation_notice_is_not_stored(memory, tmp_path: Path) -> None:
    notice = Message(
        role=Role.TOOL,
        name="terminal",
        tool_call_id="tc2",
        content="Error: repeated tool operation blocked: the same command was already run.",
    )
    memory.add_message(notice)

    assert _stored_contents(tmp_path / "memory.db") == []


def test_a_notice_is_still_left_in_the_log(memory, caplog: pytest.LogCaptureFixture) -> None:
    """It must stay traceable: it is removed from memory, not hidden."""
    caplog.set_level(logging.INFO, logger="friday.memory.sqlite")
    memory.add_message(
        Message(role=Role.TOOL, name="call_loop", content="Error: Duplicate tool call ID 'tc1' ignored.")
    )
    assert any("repeat-guard notice" in record.message for record in caplog.records)


def test_a_real_tool_result_is_still_remembered(memory, tmp_path: Path) -> None:
    """The filter is narrow: a genuine failure is still knowledge worth keeping."""
    memory.add_message(
        Message(
            role=Role.TOOL,
            name="terminal",
            tool_call_id="tc3",
            content="Command failed: the 'backup' directory does not exist on this machine.",
        )
    )
    stored = _stored_contents(tmp_path / "memory.db")
    assert stored == ["Command failed: the 'backup' directory does not exist on this machine."]


def test_a_new_question_can_no_longer_recall_the_notice(memory, tmp_path: Path, caplog) -> None:
    """The end-to-end shape of the defect: write the loop, then ask about it."""
    memory.add_message(Message(role=Role.USER, content="Please check the deployment status."))
    memory.add_message(
        Message(role=Role.TOOL, name="call_loop", content="Error: Duplicate tool call ID 'tc1' ignored.")
    )
    memory.add_message(Message(role=Role.ASSISTANT, content="I could not continue that loop."))

    recalled = memory.search("duplicate tool call id", limit=10)
    assert recalled == [], [r.content for r in recalled]


def test_substantive_history_still_round_trips(memory, tmp_path: Path) -> None:
    """The fix must not cost recall of real history - the point of the store."""
    memory.add_message(
        Message(role=Role.USER, content="My preferred deployment target is the Frankfurt region.")
    )
    memory.add_message(Message(role=Role.ASSISTANT, content="Noted, Frankfurt it is."))

    recalled = memory.search("which deployment region do I prefer", limit=5)
    assert recalled, "real history stopped being recallable"
    assert "Frankfurt" in " ".join(r.content for r in recalled)


@pytest.mark.parametrize(
    "role,content,expected",
    [
        (Role.TOOL, "Error: Duplicate tool call ID 'x' ignored.", True),
        (Role.TOOL, "Error: repeated tool operation blocked.", True),
        (Role.TOOL, "The build finished in 42 seconds.", False),
        (Role.USER, "Why did the duplicate tool call happen?", False),
        (Role.ASSISTANT, "I ignored the duplicate tool call ID.", False),
        (Role.TOOL, "", False),
    ],
)
def test_the_filter_only_touches_the_loop_s_own_notices(role, content, expected) -> None:
    assert is_non_informative_tool_notice(Message(role=role, content=content)) is expected
