"""Unit tests for TaskQueue."""
from pathlib import Path

from agent.tasks import TaskQueue, TaskStatus


def test_add_and_list(tmp_path: Path) -> None:
    q = TaskQueue(tmp_path / "tasks.json")
    t = q.add("research entropy")
    assert t.id
    assert q.list() == [t]


def test_pop_next_prefers_priority(tmp_path: Path) -> None:
    q = TaskQueue(tmp_path / "tasks.json")
    a = q.add("a", priority=50)
    b = q.add("b", priority=10)
    q.add("c", priority=90)
    t = q.pop_next()
    assert t.id == b.id
    assert t.status == TaskStatus.IN_PROGRESS


def test_pop_next_empty(tmp_path: Path) -> None:
    q = TaskQueue(tmp_path / "tasks.json")
    assert q.pop_next() is None


def test_update_status(tmp_path: Path) -> None:
    q = TaskQueue(tmp_path / "tasks.json")
    t = q.add("x")
    assert q.update_status(t.id, TaskStatus.DONE, notes="ok")
    assert q.get(t.id).status == TaskStatus.DONE
    assert q.get(t.id).notes == "ok"


def test_persists(tmp_path: Path) -> None:
    p = tmp_path / "tasks.json"
    q1 = TaskQueue(p)
    q1.add("x")
    q2 = TaskQueue(p)
    assert len(q2.list()) == 1


def test_list_filter_by_status(tmp_path: Path) -> None:
    q = TaskQueue(tmp_path / "tasks.json")
    q.add("a")
    q.add("b")
    q.pop_next()
    assert len(q.list(status=TaskStatus.IN_PROGRESS)) == 1
    assert len(q.list(status=TaskStatus.QUEUED)) == 1


def test_remove(tmp_path: Path) -> None:
    q = TaskQueue(tmp_path / "tasks.json")
    t = q.add("x")
    assert q.remove(t.id)
    assert q.get(t.id) is None
    assert not q.remove("nonexistent")


def test_corrupt_file_recovers(tmp_path: Path) -> None:
    p = tmp_path / "tasks.json"
    p.write_text("not-json{{")
    q = TaskQueue(p)
    assert q.list() == []
