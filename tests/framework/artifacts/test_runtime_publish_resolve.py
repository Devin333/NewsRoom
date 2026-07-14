from __future__ import annotations

import pytest

from framework.artifacts import (
    ArtifactPathError,
    ArtifactStatus,
    LocalArtifactPublisher,
    REDACTED_METADATA_VALUE,
    WorkflowArtifactRef,
    stable_hash_bytes,
)
from framework.artifacts.observability import (
    ARTIFACT_OBSERVABILITY_LOGGER,
    ARTIFACT_RESERVED_METADATA_REJECTED_EVENT,
)


def test_local_artifact_publisher_preserves_run_scoped_recovery(tmp_path) -> None:
    publisher = LocalArtifactPublisher(tmp_path)
    result = publisher.publish_artifact(
        run_id="run-1",
        step_id="step-1",
        key="payload",
        artifact_type="json",
        content=b"{}",
        metadata={"api_key": "secret"},
    )

    assert result.succeeded is True
    assert result.artifact_ref is not None
    ref = result.artifact_ref
    assert ref.metadata["api_key"] == REDACTED_METADATA_VALUE
    assert (tmp_path / "run-1" / ref.uri).exists()
    assert publisher.verify(ref) is True
    assert publisher.recover(ref).artifact_ref.status == ArtifactStatus.RECOVERED

    (tmp_path / "run-1" / ref.uri).write_bytes(b"changed")

    recovered = publisher.recover(ref)
    assert recovered.succeeded is False
    assert recovered.metadata["artifact_status"] == ArtifactStatus.CORRUPTED.value


@pytest.mark.parametrize("key", ["publisher_id", "run_id"])
def test_local_artifact_publisher_rejects_reserved_metadata(tmp_path, key: str) -> None:
    publisher = LocalArtifactPublisher(tmp_path)

    result = publisher.publish_artifact(
        run_id="run-1",
        step_id="step-1",
        key="payload",
        artifact_type="json",
        content=b"{}",
        metadata={key: "forged"},
    )

    assert result.succeeded is False
    assert result.artifact_ref is None
    assert "reserved artifact metadata" in str(result.error)
    assert not tmp_path.exists() or not any(tmp_path.rglob("*"))


def test_local_artifact_publisher_emits_reserved_metadata_rejection_once(
    tmp_path,
    caplog,
) -> None:
    caplog.set_level("INFO", logger=ARTIFACT_OBSERVABILITY_LOGGER)

    result = LocalArtifactPublisher(tmp_path).publish_artifact(
        run_id="run-1",
        step_id="step-1",
        key="payload",
        artifact_type="json",
        content=b"{}",
        metadata={"run_id": "secret-must-not-be-logged"},
    )

    assert result.succeeded is False
    records = [
        record
        for record in caplog.records
        if record.name == ARTIFACT_OBSERVABILITY_LOGGER
    ]
    assert [record.artifact_event_name for record in records] == [
        ARTIFACT_RESERVED_METADATA_REJECTED_EVENT
    ]
    assert records[0].artifact_event_dimensions == {
        "key": "run_id",
        "publisher": "local",
    }
    assert "secret-must-not-be-logged" not in caplog.text


@pytest.mark.parametrize("run_id", ["../escaped", "C:\\escaped", "run:stream", "NUL"])
def test_local_artifact_publisher_rejects_unsafe_run_id(tmp_path, run_id: str) -> None:
    result = LocalArtifactPublisher(tmp_path).publish_artifact(
        run_id=run_id,
        step_id="step-1",
        key="payload",
        artifact_type="json",
        content=b"{}",
    )

    assert result.succeeded is False
    assert result.artifact_ref is None
    assert not tmp_path.exists() or not any(tmp_path.rglob("*"))


@pytest.mark.parametrize(
    "run_id",
    [7, True, [], {}, object()],
    ids=["number", "boolean", "list", "mapping", "object"],
)
def test_local_artifact_publisher_rejects_non_string_legacy_metadata_run_id(
    tmp_path,
    run_id,
) -> None:
    root = tmp_path / "artifacts"
    publisher = LocalArtifactPublisher(root)
    artifact_ref = _legacy_artifact_ref(metadata={"run_id": run_id})

    with pytest.raises(ArtifactPathError, match="run_id must be a string"):
        publisher.exists(artifact_ref)

    assert root.exists() is False


def test_local_artifact_publisher_preserves_legacy_ref_without_run_id(tmp_path) -> None:
    root = tmp_path / "artifacts"
    content = b"legacy"
    path = root / "legacy.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    publisher = LocalArtifactPublisher(root)
    artifact_ref = _legacy_artifact_ref(
        metadata={"source": "legacy"},
        content=content,
    )

    assert publisher.exists(artifact_ref) is True
    assert publisher.verify(artifact_ref) is True


def _legacy_artifact_ref(
    *,
    metadata,
    content: bytes = b"{}",
) -> WorkflowArtifactRef:
    return WorkflowArtifactRef(
        artifact_id="legacy-1",
        artifact_type="json",
        key="payload",
        uri="legacy.json",
        content_hash=stable_hash_bytes(content),
        size_bytes=len(content),
        media_type="application/json",
        created_by_step_id="step-1",
        created_at="2026-07-14T00:00:00Z",
        status=ArtifactStatus.PUBLISHED,
        metadata=metadata,
    )
