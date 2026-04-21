"""Unit tests for AgentState load/save."""
from pathlib import Path

from agent.state import AgentState, load, save


def test_default_state_when_missing(tmp_path: Path) -> None:
    s = load(tmp_path / "state.json")
    assert s.status == "idle"
    assert s.step == 0
    assert s.task_id is None


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    s1 = AgentState(task_id="x", status="in_progress", step=3, next_action="run tests")
    save(p, s1)
    s2 = load(p)
    assert s2 == s1


def test_save_is_atomic(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    save(p, AgentState(status="idle"))
    save(p, AgentState(status="in_progress", step=1))
    # no .tmp left behind
    assert not p.with_suffix(".tmp").exists()
    assert load(p).status == "in_progress"


def test_corrupt_file_returns_default(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    p.write_text("not-json{{")
    s = load(p)
    assert s.status == "idle"


def test_save_creates_parent_dir(tmp_path: Path) -> None:
    p = tmp_path / "a" / "b" / "state.json"
    save(p, AgentState(status="idle"))
    assert p.exists()
