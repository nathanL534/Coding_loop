"""Kill switch: bridge refuses every request while the pause file exists."""
from __future__ import annotations

from pathlib import Path


class KillSwitchActive(Exception):
    pass


class KillSwitch:
    def __init__(self, flag_path: Path) -> None:
        self._path = flag_path

    def is_active(self) -> bool:
        return self._path.exists()

    def check(self) -> None:
        if self.is_active():
            raise KillSwitchActive(f"kill switch active: {self._path}")

    def activate(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch()

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()
