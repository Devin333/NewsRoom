from __future__ import annotations

from framework.artifacts import (
    Artifact,
    ArtifactIntegrityInspector,
    ArtifactInventoryBuilder,
    ArtifactManifest,
    ArtifactReplayBundleBuilder,
    LocalArtifactStore,
)


def test_inventory_integrity_and_replay(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path)
    ref = store.put(
        Artifact(
            artifact_id="a1",
            name="payload.txt",
            content_type="text/plain",
            content="hello",
        )
    )
    manifest = ArtifactManifest(run_id="run-1", artifacts=[ref])

    inventory = ArtifactInventoryBuilder().build(store)
    integrity = ArtifactIntegrityInspector(store).inspect(manifest)
    bundle = ArtifactReplayBundleBuilder(store).build(manifest)

    assert inventory.artifact_count == 1
    assert integrity.valid is True
    assert bundle.contents == {"a1": b"hello"}
