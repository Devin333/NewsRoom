from __future__ import annotations

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
