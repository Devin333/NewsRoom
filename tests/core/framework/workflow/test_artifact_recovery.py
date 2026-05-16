from core.framework.workflow import ArtifactStatus, LocalArtifactPublisher


def test_artifact_recovery_reports_healthy_artifact(tmp_path) -> None:
    publisher = LocalArtifactPublisher(tmp_path)
    publish = publisher.publish_artifact(
        run_id="run-1",
        step_id="write",
        key="report_artifact",
        artifact_type="json",
        content=b"{}",
        metadata={"relative_path": "artifacts/write/report.json"},
    )
    assert publish.artifact_ref is not None

    recovered = publisher.recover(publish.artifact_ref)

    assert recovered.succeeded
    assert recovered.artifact_ref is not None
    assert recovered.artifact_ref.status == ArtifactStatus.RECOVERED


def test_artifact_recovery_reports_missing_artifact(tmp_path) -> None:
    publisher = LocalArtifactPublisher(tmp_path)
    publish = publisher.publish_artifact(
        run_id="run-1",
        step_id="write",
        key="report_artifact",
        artifact_type="json",
        content=b"{}",
        metadata={"relative_path": "artifacts/write/report.json"},
    )
    assert publish.artifact_ref is not None
    (tmp_path / "run-1" / publish.artifact_ref.uri).unlink()

    recovered = publisher.recover(publish.artifact_ref)

    assert not recovered.succeeded
    assert recovered.artifact_ref is not None
    assert recovered.artifact_ref.status == ArtifactStatus.FAILED
    assert recovered.metadata["artifact_status"] == ArtifactStatus.MISSING.value


def test_artifact_recovery_reports_corrupted_artifact(tmp_path) -> None:
    publisher = LocalArtifactPublisher(tmp_path)
    publish = publisher.publish_artifact(
        run_id="run-1",
        step_id="write",
        key="report_artifact",
        artifact_type="json",
        content=b"{}",
        metadata={"relative_path": "artifacts/write/report.json"},
    )
    assert publish.artifact_ref is not None
    (tmp_path / "run-1" / publish.artifact_ref.uri).write_bytes(b"changed")

    recovered = publisher.recover(publish.artifact_ref)

    assert not recovered.succeeded
    assert recovered.artifact_ref is not None
    assert recovered.artifact_ref.status == ArtifactStatus.CORRUPTED
    assert recovered.metadata["artifact_status"] == ArtifactStatus.CORRUPTED.value
