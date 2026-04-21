"""One-time bootstrap of L2 from a profile YAML.

Run on first start (or on demand) to seed the user's stable facts.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .store import Layer, MemoryStore, TrustLevel


def bootstrap_l2(store: MemoryStore, profile_yaml: Path) -> int:
    """Load `profile_yaml` and insert each top-level key as an L2 entry.

    Returns number of entries inserted.
    """
    if not profile_yaml.exists():
        return 0
    data = yaml.safe_load(profile_yaml.read_text()) or {}
    count = 0
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            content = yaml.safe_dump(value, sort_keys=False).strip()
        else:
            content = str(value)
        # Only (re)insert if the key isn't already populated.
        if store.by_key(Layer.L2, key) is None:
            store.put(
                layer=Layer.L2,
                trust=TrustLevel.SYSTEM,
                key=str(key),
                content=content,
                source=str(profile_yaml),
            )
            count += 1
    return count
