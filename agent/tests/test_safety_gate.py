"""Unit tests for the Allowlist parser."""
from pathlib import Path

import yaml

from agent.safety_gate import Allowlist


def _write(tmp: Path, data: dict) -> Path:
    d = tmp / "safety"
    d.mkdir()
    (d / "allowlist.yaml").write_text(yaml.safe_dump(data))
    return d


def test_exact_match_auto(tmp_path: Path) -> None:
    d = _write(tmp_path, {"auto_approved": ["memory.read"]})
    a = Allowlist.load(d)
    assert a.classify("memory.read") == "auto"


def test_wildcard_match_auto(tmp_path: Path) -> None:
    d = _write(tmp_path, {"auto_approved": ["memory.*"]})
    a = Allowlist.load(d)
    assert a.classify("memory.read") == "auto"
    assert a.classify("memory.write") == "auto"


def test_forbidden_wins_over_auto(tmp_path: Path) -> None:
    d = _write(tmp_path, {"auto_approved": ["*"], "forbidden": ["oauth.*"]})
    a = Allowlist.load(d)
    assert a.classify("oauth.read") == "forbidden"


def test_require_approval_beats_auto(tmp_path: Path) -> None:
    d = _write(
        tmp_path,
        {
            "forbidden": ["bridge.*"],
            "require_approval": ["git.push"],
            "auto_approved": ["git.*"],
        },
    )
    a = Allowlist.load(d)
    assert a.classify("git.push") == "approval"
    assert a.classify("git.commit") == "auto"


def test_unknown_action_defaults_to_approval(tmp_path: Path) -> None:
    d = _write(tmp_path, {"auto_approved": ["memory.read"]})
    a = Allowlist.load(d)
    assert a.classify("some.unknown.action") == "approval"


def test_forbidden_default_not_applied_to_unlisted(tmp_path: Path) -> None:
    d = _write(tmp_path, {})
    a = Allowlist.load(d)
    # No lists at all -> everything is "approval" by default.
    assert a.classify("x") == "approval"
