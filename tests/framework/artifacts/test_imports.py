from __future__ import annotations


def test_public_imports_are_available() -> None:
    from framework.artifacts import (  # noqa: PLC0415
        Artifact,
        ArtifactChecksumMismatchError,
        ArtifactManager,
        ArtifactManifest,
        ArtifactReference,
        ArtifactStoreMetadataError,
        ArtifactStoreRequiredError,
        DefaultArtifactPublisher,
        LocalArtifactStore,
        compute_checksum,
        validate_sha256_checksum,
        verify_sha256_checksum,
    )
    from framework.artifacts.stores import (  # noqa: PLC0415
        ArtifactChecksumMismatchError as StoreChecksumMismatchError,
        ArtifactStoreMetadataError as StoreMetadataError,
    )

    assert Artifact is not None
    assert ArtifactChecksumMismatchError is StoreChecksumMismatchError
    assert ArtifactManager is not None
    assert ArtifactManifest is not None
    assert ArtifactReference is not None
    assert DefaultArtifactPublisher is not None
    assert LocalArtifactStore is not None
    assert ArtifactStoreMetadataError is StoreMetadataError
    assert ArtifactStoreRequiredError is not None
    assert compute_checksum(b"x")
    checksum = validate_sha256_checksum(
        compute_checksum(b"x"),
        artifact_id="a1",
    )
    assert verify_sha256_checksum(b"x", checksum, artifact_id="a1") == checksum
