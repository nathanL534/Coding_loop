"""Unit tests for KillSwitch."""
from pathlib import Path

import pytest

from bridge.killswitch import KillSwitch, KillSwitchActive


def test_initially_inactive(tmp_path: Path) -> None:
    k = KillSwitch(tmp_path / "pause")
    assert not k.is_active()
    k.check()  # no raise


def test_activate_blocks(tmp_path: Path) -> None:
    k = KillSwitch(tmp_path / "pause")
    k.activate()
    assert k.is_active()
    with pytest.raises(KillSwitchActive):
        k.check()


def test_clear_unblocks(tmp_path: Path) -> None:
    k = KillSwitch(tmp_path / "pause")
    k.activate()
    k.clear()
    assert not k.is_active()
    k.check()


def test_clear_is_idempotent(tmp_path: Path) -> None:
    k = KillSwitch(tmp_path / "pause")
    k.clear()  # no raise when missing


def test_creates_parent_dir(tmp_path: Path) -> None:
    p = tmp_path / "a" / "b" / "pause"
    k = KillSwitch(p)
    k.activate()
    assert p.exists()
