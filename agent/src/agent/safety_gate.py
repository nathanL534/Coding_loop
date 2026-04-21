"""Reads safety config from read-only mount. Untrusted code cannot mutate these.

The actual host-side enforcement also happens in the bridge; this is a local
defense-in-depth check so the agent doesn't *try* to do things that would be
rejected downstream.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class ActionNotAllowed(Exception):
    pass


@dataclass(frozen=True)
class Allowlist:
    auto_approved: frozenset[str]
    require_approval: frozenset[str]
    forbidden: frozenset[str]
    research_domains: frozenset[str]

    @classmethod
    def load(cls, safety_dir: Path) -> "Allowlist":
        data = yaml.safe_load((safety_dir / "allowlist.yaml").read_text()) or {}
        return cls(
            auto_approved=frozenset(data.get("auto_approved", [])),
            require_approval=frozenset(data.get("require_approval", [])),
            forbidden=frozenset(data.get("forbidden", [])),
            research_domains=frozenset(data.get("research_domains", [])),
        )

    def classify(self, action: str) -> str:
        """Return 'forbidden' | 'approval' | 'auto' by most-specific match."""
        if _match(action, self.forbidden):
            return "forbidden"
        if _match(action, self.require_approval):
            return "approval"
        if _match(action, self.auto_approved):
            return "auto"
        # Unknown actions default to requiring approval.
        return "approval"


def _match(action: str, patterns: frozenset[str]) -> bool:
    if action in patterns:
        return True
    for p in patterns:
        if p.endswith(".*") and action.startswith(p[:-1]):
            return True
    return False
