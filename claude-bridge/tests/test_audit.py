"""Unit tests for AuditLog."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bridge.audit import AuditLog, _hash_prompt


async def test_writes_one_line_per_event(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.log")
    await log.write(event="ok.complete", task_id="t1", request_id="r1")
    await log.write(event="reject.budget", task_id="t2", request_id="r2", error="daily cap")
    lines = (tmp_path / "audit.log").read_text().splitlines()
    assert len(lines) == 2
    one = json.loads(lines[0])
    assert one["event"] == "ok.complete"
    assert one["task_id"] == "t1"


async def test_hashes_prompt_not_contents(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.log")
    await log.write(
        event="ok.complete",
        task_id=None,
        request_id="r1",
        messages=[{"role": "user", "content": "SECRET hello"}],
    )
    content = (tmp_path / "audit.log").read_text()
    assert "SECRET" not in content
    parsed = json.loads(content.splitlines()[0])
    assert "prompt_hash" in parsed
    assert len(parsed["prompt_hash"]) == 16


def test_hash_prompt_deterministic() -> None:
    a = _hash_prompt([{"role": "user", "content": "x"}])
    b = _hash_prompt([{"role": "user", "content": "x"}])
    assert a == b


def test_hash_prompt_changes_with_content() -> None:
    a = _hash_prompt([{"role": "user", "content": "x"}])
    b = _hash_prompt([{"role": "user", "content": "y"}])
    assert a != b


async def test_creates_parent_dir(tmp_path: Path) -> None:
    p = tmp_path / "nested" / "sub" / "audit.log"
    AuditLog(p)
    assert p.parent.exists()
