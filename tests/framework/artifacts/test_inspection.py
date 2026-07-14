from __future__ import annotations

from dataclasses import dataclass

import pytest

from framework.artifacts import (
    Artifact,
    ArtifactChecksumMismatchError,
    ArtifactIntegrityInspector,
    ArtifactInventoryBuilder,
    ArtifactManifest,
    ArtifactNotFoundError,
    ArtifactReference,
    ArtifactReplayBundleBuilder,
    ArtifactStoreMetadataError,
    ArtifactStoreRequiredError,
    LocalArtifactStore,
    compute_checksum,
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


def test_empty_integrity_manifest_needs_no_store() -> None:
    report = ArtifactIntegrityInspector().inspect(ArtifactManifest(run_id="run-1"))

    assert report.valid is True
    assert report.checked_count == 0
    assert report.issues == []


def test_non_empty_integrity_manifest_requires_store() -> None:
    manifest = ArtifactManifest(
        run_id="run-1",
        artifacts=[ArtifactReference(artifact_id="a1", uri="objects/a1")],
    )

    with pytest.raises(ArtifactStoreRequiredError):
        ArtifactIntegrityInspector().inspect(manifest)


@dataclass
class _ClassifyingStore:
    artifacts: dict[str, Artifact | Exception | None]
    calls: list[str]

    def get(self, artifact_id: str) -> Artifact | None:
        self.calls.append(artifact_id)
        result = self.artifacts[artifact_id]
        if isinstance(result, Exception):
            raise result
        return result


def test_integrity_inspector_counts_and_classifies_every_attempt() -> None:
    valid = Artifact("valid", "valid.txt", "text/plain", b"valid")
    wrong_reference = Artifact("wrong-ref", "wrong.txt", "text/plain", b"actual")
    checksum_missing = Artifact(
        "legacy",
        "legacy.txt",
        "text/plain",
        b"legacy",
        metadata={"_artifact_integrity": "checksum_missing"},
    )
    store = _ClassifyingStore(
        artifacts={
            "missing-none": None,
            "missing-error": ArtifactNotFoundError("missing"),
            "store-mismatch": ArtifactChecksumMismatchError("mismatch"),
            "metadata": ArtifactStoreMetadataError("corrupt"),
            "legacy": checksum_missing,
            "wrong-ref": wrong_reference,
            "invalid-ref": valid,
            "valid": valid,
        },
        calls=[],
    )
    refs = [
        ArtifactReference("missing-none", "objects/missing-none", checksum=compute_checksum(b"x")),
        ArtifactReference("missing-error", "objects/missing-error", checksum=compute_checksum(b"x")),
        ArtifactReference("store-mismatch", "objects/store-mismatch", checksum=compute_checksum(b"x")),
        ArtifactReference("metadata", "objects/metadata", checksum=compute_checksum(b"x")),
        ArtifactReference("legacy", "objects/legacy", checksum=compute_checksum(b"legacy")),
        ArtifactReference("wrong-ref", "objects/wrong-ref", checksum=compute_checksum(b"expected")),
        ArtifactReference("invalid-ref", "objects/invalid-ref", checksum="not-a-checksum"),
        ArtifactReference("valid", "objects/valid", checksum=compute_checksum(b"valid")),
    ]

    report = ArtifactIntegrityInspector(store).inspect(
        ArtifactManifest(run_id="run-1", artifacts=refs)
    )

    assert report.valid is False
    assert report.checked_count == len(refs)
    assert store.calls == [ref.artifact_id for ref in refs]
    assert [issue.reason for issue in report.issues] == [
        "missing",
        "missing",
        "checksum_mismatch",
        "metadata_corrupt",
        "checksum_missing",
        "checksum_mismatch",
        "metadata_corrupt",
    ]


def test_integrity_inspector_propagates_unknown_store_failure() -> None:
    store = _ClassifyingStore(
        artifacts={"a1": PermissionError("denied")},
        calls=[],
    )
    manifest = ArtifactManifest(
        run_id="run-1",
        artifacts=[
            ArtifactReference("a1", "objects/a1", checksum=compute_checksum(b"x"))
        ],
    )

    with pytest.raises(PermissionError, match="denied"):
        ArtifactIntegrityInspector(store).inspect(manifest)

    assert store.calls == ["a1"]


def test_integrity_inspector_prefers_call_time_store() -> None:
    configured = _ClassifyingStore(artifacts={"a1": None}, calls=[])
    artifact = Artifact("a1", "a1.txt", "text/plain", b"valid")
    call_time = _ClassifyingStore(artifacts={"a1": artifact}, calls=[])
    manifest = ArtifactManifest(
        run_id="run-1",
        artifacts=[
            ArtifactReference("a1", "objects/a1", checksum=compute_checksum(b"valid"))
        ],
    )

    report = ArtifactIntegrityInspector(configured).inspect(manifest, call_time)

    assert report.valid is True
    assert report.checked_count == 1
    assert configured.calls == []
    assert call_time.calls == ["a1"]
