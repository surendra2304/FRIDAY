"""Unit tests for SQLiteTaskStore persistence."""

import os
import tempfile
import pytest

from friday.persistence.task_store import SQLiteTaskStore, TaskItem


@pytest.fixture
def temp_task_store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = SQLiteTaskStore(db_path=path)
    yield store
    try:
        os.remove(path)
    except Exception:
        pass


def test_create_and_get_task(temp_task_store):
    task = temp_task_store.create_task(
        title="Finish project report",
        description="Include phase 7 and phase 8 details",
        priority="high",
    )
    assert task.id.startswith("task_")
    assert task.title == "Finish project report"
    assert task.priority == "high"
    assert task.status == "pending"

    fetched = temp_task_store.get_task(task.id)
    assert fetched is not None
    assert fetched.title == task.title
    assert fetched.description == task.description


def test_list_and_filter_tasks(temp_task_store):
    temp_task_store.create_task(title="Task A", priority="low")
    temp_task_store.create_task(title="Task B", priority="urgent")
    temp_task_store.create_task(title="Task C", priority="urgent")

    all_tasks = temp_task_store.list_tasks()
    assert len(all_tasks) == 3

    urgent_tasks = temp_task_store.list_tasks(priority="urgent")
    assert len(urgent_tasks) == 2


def test_complete_and_delete_task(temp_task_store):
    task = temp_task_store.create_task(title="Submit expense report")
    assert task.status == "pending"

    # Complete by title keyword
    completed = temp_task_store.complete_task("expense")
    assert completed is not None
    assert completed.status == "completed"
    assert completed.completed_at is not None

    # Delete task
    assert temp_task_store.delete_task(task.id) is True
    assert temp_task_store.get_task(task.id) is None
