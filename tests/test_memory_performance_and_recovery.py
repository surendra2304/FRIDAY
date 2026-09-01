"""Performance, scalability, and disaster recovery tests for persistent SQLite memory."""

import concurrent.futures
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from friday.core.types import Message, Role, ToolCall
from friday.memory.sqlite import SQLiteConversationMemory


def test_database_auto_creation_on_missing_file(tmp_path):
    nested_db = str(tmp_path / "deep" / "nested" / "dir" / "friday.db")
    assert not Path(nested_db).exists()

    mem = SQLiteConversationMemory(db_path=nested_db)
    assert Path(nested_db).exists()
    assert len(mem.list_conversations()) >= 1


def test_malformed_json_row_recovery(tmp_path):
    db_file = str(tmp_path / "corrupt_row.db")
    mem = SQLiteConversationMemory(db_path=db_file)
    conv_id = mem.active_conversation_id

    # Insert raw row with malformed tool_calls JSON and invalid role string directly
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            INSERT INTO messages (id, conversation_id, role, content, name, tool_calls, tool_call_id, created_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "corrupt-msg-1",
                conv_id,
                "unknown_invalid_role",
                "Message with corrupt JSON",
                None,
                "{invalid:json:syntax",
                None,
                datetime.now(timezone.utc).isoformat(),
                "{bad-json",
            ),
        )
        conn.commit()

    # get_messages must NOT crash; it should fall back safely to Role.USER and tool_calls=None
    messages = mem.get_messages()
    assert len(messages) == 1
    assert messages[0].content == "Message with corrupt JSON"
    assert messages[0].role == Role.USER
    assert messages[0].tool_calls is None


def test_concurrent_multithreaded_reads_and_writes(tmp_path):
    db_file = str(tmp_path / "concurrent_stress.db")
    mem = SQLiteConversationMemory(db_path=db_file)
    conv_id = mem.active_conversation_id

    def worker_write(idx: int):
        msg = Message(role=Role.USER, content=f"Worker payload #{idx}")
        mem.add_message(msg, conversation_id=conv_id)
        return idx

    def worker_read(idx: int):
        msgs = mem.get_messages(conversation_id=conv_id)
        return len(msgs)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        write_futures = [executor.submit(worker_write, i) for i in range(25)]
        read_futures = [executor.submit(worker_read, i) for i in range(25)]

        concurrent.futures.wait(write_futures + read_futures)

    all_messages = mem.get_messages(conversation_id=conv_id)
    assert len(all_messages) == 25


def test_online_local_backup_creates_valid_copy(tmp_path):
    db_file = str(tmp_path / "primary.db")
    backup_file = str(tmp_path / "backups" / "primary_backup.db")

    mem = SQLiteConversationMemory(db_path=db_file)
    c1 = mem.create_conversation(title="Critical Work")
    mem.load_conversation(c1)
    mem.add_message(Message(role=Role.USER, content="Critical persistent note #42"))

    # Perform online backup
    out_path = mem.backup(backup_file)
    assert Path(out_path).exists()

    # Open backup database independently and verify contents
    backup_mem = SQLiteConversationMemory(db_path=out_path)
    backup_convs = backup_mem.list_conversations()
    assert any(c["title"] == "Critical Work" for c in backup_convs)

    backup_mem.load_conversation(c1)
    backup_msgs = backup_mem.get_messages()
    assert len(backup_msgs) == 1
    assert backup_msgs[0].content == "Critical persistent note #42"


def test_export_conversation_to_dict(tmp_path):
    db_file = str(tmp_path / "export.db")
    mem = SQLiteConversationMemory(db_path=db_file)
    c1 = mem.create_conversation(title="Exportable Session")
    mem.load_conversation(c1)
    mem.add_message(
        Message(
            role=Role.ASSISTANT,
            content="Tool executed.",
            tool_calls=[ToolCall(id="call_1", name="calculator", arguments={"expression": "2+2"})],
        )
    )

    data = mem.export_conversation_to_dict(c1)
    assert data["conversation"]["title"] == "Exportable Session"
    assert len(data["messages"]) == 1
    assert data["messages"][0]["role"] == "assistant"
    assert data["messages"][0]["tool_calls"][0]["name"] == "calculator"


def test_realistic_memory_scale_performance_benchmark(tmp_path):
    """Benchmark SQLite performance on realistic local workload: 1000 messages across 20 conversations."""
    db_file = str(tmp_path / "scale_bench.db")
    mem = SQLiteConversationMemory(db_path=db_file)

    conv_ids = []
    for c in range(20):
        cid = mem.create_conversation(title=f"Project Workspace #{c}")
        conv_ids.append(cid)

    # 1. Bulk Insert 1000 messages
    t0 = time.perf_counter()
    for i in range(1000):
        target_conv = conv_ids[i % len(conv_ids)]
        mem.add_message(
            Message(
                role=Role.USER if i % 2 == 0 else Role.ASSISTANT,
                content=f"Log telemetry data #{i} for server node #{i % 10}. Status: operational.",
            ),
            conversation_id=target_conv,
        )
    insert_duration = time.perf_counter() - t0
    avg_insert_ms = (insert_duration / 1000) * 1000
    assert avg_insert_ms < 15.0, f"Average insert took {avg_insert_ms:.2f}ms (expected <15ms)"

    # 2. Benchmark Load Conversation (50 messages)
    t0 = time.perf_counter()
    messages = mem.get_messages(conversation_id=conv_ids[0])
    load_duration_ms = (time.perf_counter() - t0) * 1000
    assert len(messages) == 50
    assert load_duration_ms < 10.0, f"Loading conversation took {load_duration_ms:.2f}ms (expected <10ms)"

    # 3. Benchmark Context Window query (last 10 messages)
    t0 = time.perf_counter()
    context = mem.get_context_window(max_messages=10)
    context_duration_ms = (time.perf_counter() - t0) * 1000
    assert len(context) <= 10
    assert context_duration_ms < 10.0, f"Context window query took {context_duration_ms:.2f}ms (expected <10ms)"

    # 4. Benchmark Full-Text Search across 1000 messages
    t0 = time.perf_counter()
    search_results = mem.search("operational node")
    search_duration_ms = (time.perf_counter() - t0) * 1000
    assert len(search_results) > 0
    assert search_duration_ms < 30.0, f"FTS search took {search_duration_ms:.2f}ms (expected <30ms)"

    # 5. Benchmark List Conversations (21 conversations)
    t0 = time.perf_counter()
    convs = mem.list_conversations()
    list_duration_ms = (time.perf_counter() - t0) * 1000
    assert len(convs) >= 20
    assert list_duration_ms < 10.0, f"Listing conversations took {list_duration_ms:.2f}ms (expected <10ms)"
