"""Tests for evolver gate."""
import pytest

from bridge.evolver_gate import EvolveDenied, EvolveProposal, evaluate_proposal


def test_non_protected_is_allowed() -> None:
    evaluate_proposal(
        EvolveProposal(branch="evolve/x", diff_summary="...", files=("agent/src/agent/foo.py",)),
        protected=("safety/allowlist.yaml", "CLAUDE.md"),
    )


def test_protected_is_denied() -> None:
    with pytest.raises(EvolveDenied, match="protected"):
        evaluate_proposal(
            EvolveProposal(
                branch="evolve/x", diff_summary="...", files=("safety/allowlist.yaml",)
            ),
            protected=("safety/allowlist.yaml", "CLAUDE.md"),
        )


def test_mixed_protected_and_ok_still_denied() -> None:
    with pytest.raises(EvolveDenied):
        evaluate_proposal(
            EvolveProposal(
                branch="evolve/x",
                diff_summary="...",
                files=("agent/src/foo.py", "CLAUDE.md"),
            ),
            protected=("CLAUDE.md",),
        )
