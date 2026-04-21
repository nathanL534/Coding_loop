"""Evolver gating: what the bridge will accept as a self-edit proposal.

Evolver itself runs in the container (as a subprocess, with git). This module
lives on the bridge to enforce what evolver's proposed diffs are allowed to
touch. A proposed diff is rejected outright if it modifies a protected file.

The flow (phase 5, --review mode):
  1. Agent (container) runs evolver, gets a proposed diff on branch evolve/*
  2. Agent POSTs /v1/evolve/propose with {branch, diff_summary, file_list}
  3. Bridge refuses if any file in file_list is in protected_files
  4. Otherwise bridge posts to Telegram with a /yes /no approve-required
  5. On yes, agent merges evolve/* into main; on no, branch is discarded

Auto-merge is NEVER allowed for files in protected_files, even after phase 6.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvolveProposal:
    branch: str
    diff_summary: str
    files: tuple[str, ...]


class EvolveDenied(Exception):
    pass


def evaluate_proposal(proposal: EvolveProposal, protected: tuple[str, ...]) -> None:
    protected_set = frozenset(protected)
    touched_protected = [f for f in proposal.files if f in protected_set]
    if touched_protected:
        raise EvolveDenied(
            f"proposal touches protected files (manual human edit required): {touched_protected}"
        )
