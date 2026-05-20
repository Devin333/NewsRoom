from datetime import UTC, datetime
from zipfile import ZipFile

import pytest

from infrastructure.storage.artifacts import ArtifactWriteRequest, FilesystemArtifactStore, LocalJsonArtifactIndexStore
from infrastructure.storage.lifecycle import LocalArtifactBackupService


def test_local_artifact_backup_service_creates_and_restores_real_files(tmp_path) -> None:
    source_root = tmp_path / "runs"
    restored_root = tmp_path / "restored"
    backup_path = tmp_path / "runs-backup.zip"
    artifact_store = FilesystemArtifactStore(source_root)
    artifact_index = LocalJsonArtifactIndexStore(source_root / "_records" / "artifact_index")
    ref = artifact_store.write(
        ArtifactWriteRequest(
            run_id="run-1",
            artifact_id="raw-1",
            artifact_type="source_item",
            content="real source body",
            content_type="text/plain",
            created_at=datetime(2026, 5, 11, tzinfo=UTC),
        )
    )
    artifact_index.index_artifact(ref)

    manifest = LocalArtifactBackupService(source_root).create_backup(
        backup_path,
        now=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
    )

    assert backup_path.exists()
    assert manifest.file_count == 2
    assert manifest.total_bytes > len("real source body")
    assert {entry.path for entry in manifest.files} == {
        "_records/artifact_index/4e65d3fbe8ad/a-e72e2581cffd8fef.json",
        "run-1/artifacts/source_item/raw-1.txt",
    }
    with ZipFile(backup_path) as archive:
        assert "_backup/manifest.json" in archive.namelist()

    restored_manifest = LocalArtifactBackupService(restored_root).restore_backup(backup_path)

    assert restored_manifest == manifest
    assert FilesystemArtifactStore(restored_root).read(ref) == b"real source body"
    assert (
        LocalJsonArtifactIndexStore(restored_root / "_records" / "artifact_index")
        .get_artifact("run-1", "raw-1")
        .checksum
        == ref.checksum
    )


def test_local_artifact_backup_service_refuses_unsafe_targets(tmp_path) -> None:
    source_root = tmp_path / "runs"
    source_root.mkdir()
    (source_root / "run-1").mkdir()
    (source_root / "run-1" / "manifest.json").write_text("{}", encoding="utf-8")
    service = LocalArtifactBackupService(source_root)
    backup_path = tmp_path / "runs.zip"

    service.create_backup(backup_path)

    with pytest.raises(FileExistsError, match="backup already exists"):
        service.create_backup(backup_path)
    with pytest.raises(ValueError, match="outside artifact root"):
        service.create_backup(source_root / "backup.zip")


def test_local_artifact_backup_service_refuses_restore_overwrite_by_default(tmp_path) -> None:
    source_root = tmp_path / "runs"
    restored_root = tmp_path / "restored"
    backup_path = tmp_path / "runs.zip"
    (source_root / "run-1").mkdir(parents=True)
    (source_root / "run-1" / "manifest.json").write_text('{"status":"succeeded"}', encoding="utf-8")

    LocalArtifactBackupService(source_root).create_backup(backup_path)
    restore_service = LocalArtifactBackupService(restored_root)
    restore_service.restore_backup(backup_path)

    with pytest.raises(FileExistsError, match="target file already exists"):
        restore_service.restore_backup(backup_path)

    restore_service.restore_backup(backup_path, overwrite=True)



def test_local_artifact_backup_service_refuses_restore_into_source_root(tmp_path) -> None:
    source_root = tmp_path / "runs"
    backup_path = tmp_path / "runs.zip"
    (source_root / "run-1").mkdir(parents=True)
    (source_root / "run-1" / "manifest.json").write_text('{"status":"succeeded"}', encoding="utf-8")

    LocalArtifactBackupService(source_root).create_backup(backup_path)

    with pytest.raises(Exception, match="restore target must differ"):
        LocalArtifactBackupService(source_root).restore_backup(backup_path, overwrite=True)
