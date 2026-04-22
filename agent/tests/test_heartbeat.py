"""Heartbeat integration tests. Uses a fake BridgeClient to avoid network."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from agent.bridge_client import CompleteResult
from agent.heartbeat import classify_wake, run_once
from agent.tasks import TaskQueue, TaskStatus


@dataclass
class _FakeBridge:
    inbox_queue: list[dict] = None
    complete_log: list[dict] = None
    notify_log: list[str] = None
    kill_switch: bool = False

    def __post_init__(self) -> None:
        self.inbox_queue = self.inbox_queue or []
        self.complete_log = self.complete_log or []
        self.notify_log = self.notify_log or []

    async def health(self) -> dict:
        return {"ok": True, "kill_switch": self.kill_switch}

    async def inbox(self, timeout: float = 0.5) -> dict | None:
        if self.inbox_queue:
            return self.inbox_queue.pop(0)
        return None

    async def complete(self, *, prompt: str, **kw: Any) -> CompleteResult:
        self.complete_log.append({"prompt": prompt, **kw})
        return CompleteResult(
            request_id="r", content=f"result: {prompt}", model="stub", cost_usd=0.01, duration_ms=5
        )

    async def notify(self, text: str, *, voice: bool = False) -> dict:
        self.notify_log.append({"text": text, "voice": voice})
        return {"ok": True, "sent_as": "voice" if voice else "text"}


def _ts(hour: int) -> datetime:
    return datetime(2025, 1, 1, hour, 0, 0)


# ---- classify_wake ----

def test_classify_wake() -> None:
    assert classify_wake(_ts(3)) == "quiet"
    assert classify_wake(_ts(8)) == "morning-brief"
    assert classify_wake(_ts(14)) == "awake"
    assert classify_wake(_ts(22)) == "evening-wrap"


# ---- run_once ----

async def test_run_once_handles_inbox(tmp_path: Path) -> None:
    br = _FakeBridge(inbox_queue=[{"text": "hello", "ts": 1234567890.0}])
    queue = TaskQueue(tmp_path / "tasks.json")
    res = await run_once(
        bridge=br, tasks=queue, state_path=tmp_path / "state.json", dry_run=False, now=_ts(14)
    )
    assert res.messages_handled == 1
    assert len(br.complete_log) == 1
    assert br.notify_log  # response sent
    assert br.notify_log[0]["voice"] is False


async def test_voice_in_gets_voice_out(tmp_path: Path) -> None:
    br = _FakeBridge(inbox_queue=[{"text": "hello", "ts": 1.0, "from_voice": True}])
    queue = TaskQueue(tmp_path / "tasks.json")
    await run_once(
        bridge=br, tasks=queue, state_path=tmp_path / "state.json", dry_run=False, now=_ts(14)
    )
    assert br.notify_log
    assert br.notify_log[0]["voice"] is True


async def test_run_once_dry_run_does_not_call_complete(tmp_path: Path) -> None:
    br = _FakeBridge(inbox_queue=[{"text": "hi", "ts": 0.0}])
    queue = TaskQueue(tmp_path / "tasks.json")
    queue.add("do the thing")
    res = await run_once(
        bridge=br, tasks=queue, state_path=tmp_path / "state.json", dry_run=True, now=_ts(14)
    )
    assert res.messages_handled == 1
    # complete was not called for either task or message
    assert br.complete_log == []
    assert br.notify_log == []


async def test_run_once_processes_one_task(tmp_path: Path) -> None:
    br = _FakeBridge()
    queue = TaskQueue(tmp_path / "tasks.json")
    queue.add("task A")
    queue.add("task B")
    res = await run_once(
        bridge=br, tasks=queue, state_path=tmp_path / "state.json", dry_run=False, now=_ts(14)
    )
    assert res.tasks_processed == 1
    assert len(br.complete_log) == 1
    done = queue.list(status=TaskStatus.DONE)
    assert len(done) == 1


async def test_run_once_skips_tasks_in_quiet_hours(tmp_path: Path) -> None:
    br = _FakeBridge()
    queue = TaskQueue(tmp_path / "tasks.json")
    queue.add("nightly thing")
    res = await run_once(
        bridge=br, tasks=queue, state_path=tmp_path / "state.json", dry_run=False, now=_ts(3)
    )
    assert res.tasks_processed == 0


async def test_run_once_aborts_on_kill_switch(tmp_path: Path) -> None:
    br = _FakeBridge(kill_switch=True)
    queue = TaskQueue(tmp_path / "tasks.json")
    queue.add("x")
    res = await run_once(
        bridge=br, tasks=queue, state_path=tmp_path / "state.json", dry_run=False, now=_ts(14)
    )
    assert res.aborted == "kill_switch"
    assert res.tasks_processed == 0


async def test_morning_brief_sent(tmp_path: Path) -> None:
    br = _FakeBridge()
    queue = TaskQueue(tmp_path / "tasks.json")
    queue.add("study entropy")
    res = await run_once(
        bridge=br, tasks=queue, state_path=tmp_path / "state.json", dry_run=False, now=_ts(8)
    )
    assert res.briefings_sent == 1
    # morning brief included in notify_log
    assert any("Morning" in m["text"] for m in br.notify_log)


async def test_evening_wrap_sent(tmp_path: Path) -> None:
    br = _FakeBridge()
    queue = TaskQueue(tmp_path / "tasks.json")
    res = await run_once(
        bridge=br, tasks=queue, state_path=tmp_path / "state.json", dry_run=False, now=_ts(22)
    )
    assert res.briefings_sent == 1
    assert any("wrap" in m["text"].lower() for m in br.notify_log)


async def test_task_failure_marks_failed(tmp_path: Path) -> None:
    class _Raising(_FakeBridge):
        async def complete(self, **kw: Any) -> CompleteResult:
            raise RuntimeError("boom")

    br = _Raising()
    queue = TaskQueue(tmp_path / "tasks.json")
    queue.add("broken")
    res = await run_once(
        bridge=br, tasks=queue, state_path=tmp_path / "state.json", dry_run=False, now=_ts(14)
    )
    assert res.tasks_processed == 1
    failed = queue.list(status=TaskStatus.FAILED)
    assert len(failed) == 1
