import json
from datetime import UTC, datetime

import interfaces.cli.news as news_cli
from infrastructure.storage.artifacts import ArtifactWriteRequest, FilesystemArtifactStore, LocalJsonArtifactIndexStore


def test_news_cli_storage_backup_create_and_restore_json(tmp_path, capsys) -> None:
    source_root = tmp_path / "runs"
    restored_root = tmp_path / "restored"
    backup_path = tmp_path / "runs.zip"
    artifact_store = FilesystemArtifactStore(source_root)
    artifact_index = LocalJsonArtifactIndexStore(source_root / "_records" / "artifact_index")
    ref = artifact_store.write(
        ArtifactWriteRequest(
            run_id="run-1",
            artifact_id="raw-1",
            artifact_type="source_item",
            content=b"source bytes",
            content_type="text/plain",
            created_at=datetime(2026, 5, 11, tzinfo=UTC),
        )
    )
    artifact_index.index_artifact(ref)

    create_code = news_cli.main(
        [
            "storage",
            "backup",
            "create",
            "--artifact-root",
            str(source_root),
            "--backup-path",
            str(backup_path),
            "--now",
            "2026-05-11T01:00:00Z",
            "--json",
        ]
    )
    create_payload = json.loads(capsys.readouterr().out)

    restore_code = news_cli.main(
        [
            "storage",
            "backup",
            "restore",
            "--artifact-root",
            str(restored_root),
            "--backup-path",
            str(backup_path),
            "--yes",
            "--json",
        ]
    )
    restore_payload = json.loads(capsys.readouterr().out)

    assert create_code == 0
    assert create_payload["file_count"] == 2
    assert create_payload["manifest"]["created_at"] == "2026-05-11T01:00:00Z"
    assert restore_code == 0
    assert restore_payload["restored_count"] == 2
    assert FilesystemArtifactStore(restored_root).read(ref) == b"source bytes"


def test_news_cli_storage_backup_create_text(tmp_path, capsys) -> None:
    source_root = tmp_path / "runs"
    backup_path = tmp_path / "runs.zip"
    (source_root / "run-1").mkdir(parents=True)
    (source_root / "run-1" / "manifest.json").write_text("{}", encoding="utf-8")

    exit_code = news_cli.main(
        [
            "storage",
            "backup",
            "create",
            "--artifact-root",
            str(source_root),
            "--backup-path",
            str(backup_path),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert f"backup_path={backup_path}" in captured.out
    assert "file_count=1" in captured.out


def test_news_cli_storage_backup_restore_requires_yes(tmp_path, capsys) -> None:
    exit_code = news_cli.main(
        [
            "storage",
            "backup",
            "restore",
            "--artifact-root",
            str(tmp_path / "runs"),
            "--backup-path",
            str(tmp_path / "runs.zip"),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "requires --yes" in captured.out
