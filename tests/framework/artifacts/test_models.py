from __future__ import annotations

from datetime import UTC, datetime

from framework.artifacts import (
    Artifact,
    ArtifactContent,
    ArtifactManifest,
    ArtifactReference,
    compute_checksum,
    verify_checksum,
)


def test_artifact_content_and_checksum_round_trip() -> None:
    artifact = Artifact(
        artifact_id="a1",
        name="payload",
        content_type="application/json",
        content={"ok": True},
        created_at=datetime(2026, 5, 20, tzinfo=UTC),
    )

    data = artifact.content_bytes()

    assert ArtifactContent({"ok": True}).as_json() == {"ok": True}
    assert artifact.to_dict()["created_at"] == "2026-05-20T00:00:00Z"
    assert compute_checksum(data)
    assert verify_checksum(data, compute_checksum(data)) is True


def test_manifest_tracks_references() -> None:
    ref = ArtifactReference(
        artifact_id="a1",
        uri="objects/a1",
        content_type="text/plain",
        checksum="abc",
        metadata={"kind": "note"},
    )
    manifest = ArtifactManifest(run_id="run-1")

    manifest.add(ref)
    restored = ArtifactManifest.from_dict(manifest.to_dict())

    assert restored.get("a1") == ref
    assert [item.artifact_id for item in restored.list()] == ["a1"]
    assert ArtifactReference.from_dict({"artifact_id": "a2", "path": "x", "content_hash": "h"}).uri == "x"
