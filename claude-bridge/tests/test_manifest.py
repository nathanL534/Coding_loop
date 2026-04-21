"""Tests for manifest compute/verify cycle."""
from pathlib import Path

from bridge.manifest import compute, read_manifest, verify, write_manifest


def test_compute_round_trip(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "b.txt").write_text("world")
    digests = compute(tmp_path, ["a.txt", "b.txt"])
    manifest = tmp_path / "manifest.sha256"
    write_manifest(manifest, digests)
    read_back = read_manifest(manifest)
    assert read_back == digests


def test_verify_reports_changes(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "b.txt").write_text("world")
    manifest = tmp_path / "manifest.sha256"
    write_manifest(manifest, compute(tmp_path, ["a.txt", "b.txt"]))
    (tmp_path / "a.txt").write_text("TAMPERED")
    diffs = verify(tmp_path, manifest, ["a.txt", "b.txt"])
    assert diffs == ["a.txt"]


def test_verify_reports_missing(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "b.txt").write_text("world")
    manifest = tmp_path / "manifest.sha256"
    write_manifest(manifest, compute(tmp_path, ["a.txt", "b.txt"]))
    (tmp_path / "b.txt").unlink()
    diffs = verify(tmp_path, manifest, ["a.txt", "b.txt"])
    assert "b.txt" in diffs


def test_verify_clean(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello")
    manifest = tmp_path / "manifest.sha256"
    write_manifest(manifest, compute(tmp_path, ["a.txt"]))
    assert verify(tmp_path, manifest, ["a.txt"]) == []
