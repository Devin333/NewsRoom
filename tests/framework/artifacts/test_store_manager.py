from __future__ import annotations

import pytest

from framework.artifacts import (
    Artifact,
    ArtifactManager,
    ArtifactWriteRequest,
    FilesystemArtifactStore,
)


def test_artifact_manager_publishes_resolves_and_deletes(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    artifact = Artifact(
        artifact_id="a1",
        name="hello.txt",
        content_type="text/plain",
        content="hello",
    )

    ref = manager.publish(artifact)

    assert ref.artifact_id == "a1"
    assert manager.resolve(ref).content_bytes() == b"hello"
    assert [item.artifact_id for item in manager.list()] == ["a1"]

    manager.delete("a1")

    with pytest.raises(FileNotFoundError):
        manager.resolve(ref)


def test_legacy_run_write_methods_reject_unsafe_paths(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)

    manager.start_run("run-1")
    path = manager.write_json("run-1", "nested/payload.json", {"ok": True})

    assert path.relative_to(tmp_path).as_posix() == "run-1/nested/payload.json"
    with pytest.raises(ValueError):
        manager.write_text("run-1", "../secret.txt", "nope")


def test_filesystem_store_storage_compatibility(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path)

    ref = store.write(
        ArtifactWriteRequest(
            run_id="run-1",
            artifact_id="a1",
            artifact_type="report",
            step_id="draft",
            content=b"{}",
            content_type="application/json",
        )
    )

    assert ref.path == "steps/draft/artifacts/a1.json"
    assert store.read(ref) == b"{}"
    store.delete(ref)
    assert store.exists(ref) is False
