from __future__ import annotations

import pytest

from framework.artifacts import ArtifactStatus, LocalArtifactPublisher, REDACTED_METADATA_VALUE


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
