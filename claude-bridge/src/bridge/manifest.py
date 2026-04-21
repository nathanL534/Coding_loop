"""Protected-files manifest: SHA-256 of each file the agent must not mutate.

Host-side enforcement: bridge refuses completions if the agent's current
manifest hash doesn't match the one in safety/manifest.sha256.

Usage:
    python -m bridge.manifest generate <repo_root>   # update manifest
    python -m bridge.manifest verify <repo_root>     # return 0/1
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def _hash_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute(repo_root: Path, protected: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in protected:
        p = repo_root / rel
        if p.is_file():
            out[rel] = _hash_file(p)
        else:
            out[rel] = "MISSING"
    return out


def read_manifest(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2:
            parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        digest, rel = parts
        result[rel.strip()] = digest.strip()
    return result


def write_manifest(path: Path, digests: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# sha256  path"]
    for rel in sorted(digests):
        lines.append(f"{digests[rel]}  {rel}")
    path.write_text("\n".join(lines) + "\n")


def verify(repo_root: Path, manifest_path: Path, protected: list[str]) -> list[str]:
    """Return a list of paths whose digests don't match the manifest. Empty = OK.

    A currently-missing protected file is always flagged, even if the manifest
    also records it as missing — safer default (failsafe).
    """
    current = compute(repo_root, protected)
    expected = read_manifest(manifest_path)
    diffs: list[str] = []
    for rel in protected:
        if current.get(rel) == "MISSING":
            diffs.append(rel)
            continue
        if expected.get(rel) != current.get(rel):
            diffs.append(rel)
    return diffs


def _main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: python -m bridge.manifest (generate|verify) <repo_root>", file=sys.stderr)
        return 2
    cmd, root_s = argv[1], argv[2]
    root = Path(root_s).resolve()
    protected_path = root / "safety" / "protected-files.txt"
    protected = [
        line.strip()
        for line in protected_path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    manifest_path = root / "safety" / "manifest.sha256"
    if cmd == "generate":
        write_manifest(manifest_path, compute(root, protected))
        print(f"wrote {manifest_path}")
        return 0
    if cmd == "verify":
        diffs = verify(root, manifest_path, protected)
        if diffs:
            print("manifest mismatch:", file=sys.stderr)
            for d in diffs:
                print(f"  {d}", file=sys.stderr)
            return 1
        print("manifest OK")
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
