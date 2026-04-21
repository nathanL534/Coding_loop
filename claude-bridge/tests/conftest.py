"""Shared fixtures for bridge tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make src/bridge importable without installing.
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("PYTEST_CURRENT_TEST_BRIDGE", "1")
