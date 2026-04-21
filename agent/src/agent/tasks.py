"""Simple persistent task queue. Tasks survive container restarts."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path


class TaskStatus(str, Enum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    BLOCKED_APPROVAL = "blocked_approval"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Task:
    id: str
    title: str
    created_ts: float
    status: TaskStatus = TaskStatus.QUEUED
    priority: int = 50  # 0 = highest
    last_update_ts: float = 0.0
    notes: str = ""
    tags: list[str] = field(default_factory=list)

    def bump(self) -> None:
        self.last_update_ts = time.time()


class TaskQueue:
    """JSON-file backed list. Good enough for hundreds of items."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._tasks: list[Task] = self._load()

    def _load(self) -> list[Task]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text())
        except json.JSONDecodeError:
            return []
        out: list[Task] = []
        for d in raw:
            # ensure enum type
            d = dict(d)
            d["status"] = TaskStatus(d.get("status", "queued"))
            out.append(Task(**d))
        return out

    def _flush(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(t) for t in self._tasks], default=str, sort_keys=True))
        tmp.replace(self._path)

    def add(self, title: str, *, priority: int = 50, tags: list[str] | None = None) -> Task:
        t = Task(
            id=str(uuid.uuid4()),
            title=title,
            created_ts=time.time(),
            last_update_ts=time.time(),
            priority=priority,
            tags=list(tags or []),
        )
        self._tasks.append(t)
        self._flush()
        return t

    def pop_next(self) -> Task | None:
        """Returns highest-priority queued task and marks it in_progress."""
        queued = [t for t in self._tasks if t.status == TaskStatus.QUEUED]
        if not queued:
            return None
        queued.sort(key=lambda t: (t.priority, t.created_ts))
        t = queued[0]
        t.status = TaskStatus.IN_PROGRESS
        t.bump()
        self._flush()
        return t

    def update_status(self, task_id: str, status: TaskStatus, *, notes: str | None = None) -> bool:
        for t in self._tasks:
            if t.id == task_id:
                t.status = status
                if notes is not None:
                    t.notes = notes
                t.bump()
                self._flush()
                return True
        return False

    def list(self, *, status: TaskStatus | None = None) -> list[Task]:
        if status is None:
            return list(self._tasks)
        return [t for t in self._tasks if t.status == status]

    def get(self, task_id: str) -> Task | None:
        for t in self._tasks:
            if t.id == task_id:
                return t
        return None

    def remove(self, task_id: str) -> bool:
        before = len(self._tasks)
        self._tasks = [t for t in self._tasks if t.id != task_id]
        if len(self._tasks) != before:
            self._flush()
            return True
        return False
