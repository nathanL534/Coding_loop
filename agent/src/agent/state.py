"""Crash-safe state.json used to resume mid-task across wakes."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AgentState:
    task_id: str | None = None
    status: str = "idle"             # idle | in_progress | waiting_approval | done
    step: int = 0
    next_action: str | None = None
    branch: str | None = None
    budget_used_usd: float = 0.0
    last_update_ts: float | None = None
    context: dict[str, Any] = field(default_factory=dict)


def load(path: Path) -> AgentState:
    if not path.exists():
        return AgentState()
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return AgentState()
    return AgentState(**data)


def save(path: Path, state: AgentState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(state), sort_keys=True))
    os.replace(tmp, path)
