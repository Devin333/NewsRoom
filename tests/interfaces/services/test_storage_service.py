from datetime import UTC, datetime

from interfaces.services.storage_service import StorageApplicationService
from storage.artifacts import ArtifactWriteRequest, FilesystemArtifactStore, LocalJsonArtifactIndexStore


def test_storage_service_plans_and_applies_retention_from_real_index(tmp_path) -> None:
    artifact_store = FilesystemArtifactStore(tmp_path)
    artifact_index = LocalJsonArtifactIndexStore(tmp_path / "_records" / "artifact_index")
    old_raw = artifact_store.write(
        ArtifactWriteRequest(
            run_id="run-1",
            artifact_id="raw-old",
            artifact_type="source_item",
            content=b"raw",
            content_type="text/plain",
            created_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
    )
    old_report = artifact_store.write(
        ArtifactWriteRequest(
            run_id="run-1",
            artifact_id="report-old",
            artifact_type="report_json",
            content=b"{}",
            content_type="application/json",
            created_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
    )
    artifact_index.index_artifact(old_raw)
    artifact_index.index_artifact(old_report)

    service = StorageApplicationService(tmp_path)
    plan_result = service.plan_retention(now=datetime(2026, 5, 11, tzinfo=UTC))

    assert plan_result.to_dict()["artifact_count"] == 2
    assert plan_result.to_dict()["delete_count"] == 1

    apply_result = service.apply_retention(now=datetime(2026, 5, 11, tzinfo=UTC))

    assert apply_result.to_dict()["deleted_count"] == 1
    assert apply_result.deleted_artifacts == [old_raw]
    assert artifact_store.exists(old_raw) is False
    assert artifact_store.exists(old_report) is True


def test_storage_service_filters_retention_by_run_id(tmp_path) -> None:
    artifact_store = FilesystemArtifactStore(tmp_path)
    artifact_index = LocalJsonArtifactIndexStore(tmp_path / "_records" / "artifact_index")
    first = artifact_store.write(
        ArtifactWriteRequest(
            run_id="run-1",
            artifact_id="raw-old-1",
            artifact_type="source_item",
            content=b"raw",
            content_type="text/plain",
            created_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
    )
    second = artifact_store.write(
        ArtifactWriteRequest(
            run_id="run-2",
            artifact_id="raw-old-2",
            artifact_type="source_item",
            content=b"raw",
            content_type="text/plain",
            created_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
    )
    artifact_index.index_artifact(first)
    artifact_index.index_artifact(second)

    result = StorageApplicationService(tmp_path).plan_retention(
        run_id="run-2",
        now=datetime(2026, 5, 11, tzinfo=UTC),
    )

    assert result.to_dict()["run_id"] == "run-2"
    assert [decision.artifact_ref.artifact_id for decision in result.plan.decisions] == ["raw-old-2"]


def test_storage_service_creates_and_restores_backup_from_real_files(tmp_path) -> None:
    source_root = tmp_path / "runs"
    restored_root = tmp_path / "restored"
    backup_path = tmp_path / "runs.zip"
    artifact_store = FilesystemArtifactStore(source_root)
    artifact_index = LocalJsonArtifactIndexStore(source_root / "_records" / "artifact_index")
    ref = artifact_store.write(
        ArtifactWriteRequest(
            run_id="run-1",
            artifact_id="report-1",
            artifact_type="report_json",
            content=b'{"title":"Report"}',
            content_type="application/json",
            created_at=datetime(2026, 5, 11, tzinfo=UTC),
        )
    )
    artifact_index.index_artifact(ref)

    backup_result = StorageApplicationService(source_root).create_backup(
        backup_path,
        now=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
    )
    restore_result = StorageApplicationService(restored_root).restore_backup(backup_path)

    assert backup_result.to_dict()["file_count"] == 2
    assert restore_result.to_dict()["restored_count"] == 2
    assert FilesystemArtifactStore(restored_root).read(ref) == b'{"title":"Report"}'
