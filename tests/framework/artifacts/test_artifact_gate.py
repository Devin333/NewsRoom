from __future__ import annotations

import pytest

from framework.agent.artifacts import ArtifactManager, ArtifactPathError


def test_artifact_gate_allows_relative_write(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("run-1")

    path = manager.write_json("run-1", "steps/s1/output.json", {"ok": True})

    assert path.exists()


def test_artifact_gate_blocks_parent_path(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("run-1")

    with pytest.raises(ArtifactPathError, match="invalid artifact name"):
        manager.write_text("run-1", "../escape.txt", "nope")

    assert not (tmp_path.parent / "escape.txt").exists()


def test_artifact_path_boundary_cannot_be_disabled(tmp_path) -> None:
    manager = ArtifactManager(tmp_path, gate_enabled=False)

    with pytest.raises(ArtifactPathError):
        manager.write_text("../escaped", "payload.txt", "nope")

    assert not (tmp_path.parent / "escaped" / "payload.txt").exists()


def test_artifact_gate_blocks_size_limit(tmp_path) -> None:
    manager = ArtifactManager(tmp_path, max_write_bytes=4)
    manager.start_run("run-1")

    with pytest.raises(ValueError, match="artifact gate blocked"):
        manager.write_text("run-1", "large.txt", "too large")
