from __future__ import annotations


def test_public_imports_are_available() -> None:
    from framework.artifacts import (  # noqa: PLC0415
        Artifact,
        ArtifactManager,
        ArtifactManifest,
        ArtifactReference,
        DefaultArtifactPublisher,
        LocalArtifactStore,
        compute_checksum,
    )

    assert Artifact is not None
    assert ArtifactManager is not None
    assert ArtifactManifest is not None
    assert ArtifactReference is not None
    assert DefaultArtifactPublisher is not None
    assert LocalArtifactStore is not None
    assert compute_checksum(b"x")
