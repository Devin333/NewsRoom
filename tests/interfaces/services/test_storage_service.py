import json
from datetime import UTC, datetime
from hashlib import sha256

import pytest

import interfaces.services.storage_service as storage_service_module
from interfaces.services.storage_service import StorageApplicationService
from infrastructure.storage.artifacts import (
    ArtifactRef,
    ArtifactWriteRequest,
    FilesystemArtifactStore,
    LocalJsonArtifactIndexStore,
)
from infrastructure.storage.lineage import LineageRef, LocalJsonLineageStore
from infrastructure.storage.metrics import StorageMetrics


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


def test_storage_service_queries_lineage_from_real_store(tmp_path) -> None:
    lineage_store = LocalJsonLineageStore(tmp_path / "_records" / "lineage")
    source_item = LineageRef(
        run_id="run-1",
        source_type="source_item",
        source_id="raw-1",
        target_type="evidence",
        target_id="ev-1",
        relation_type="source_to_evidence",
        created_at=datetime(2026, 5, 11, tzinfo=UTC),
    )
    ranked_item = LineageRef(
        run_id="run-1",
        source_type="ranked_source_item",
        source_id="rank-1",
        target_type="evidence",
        target_id="ev-1",
        relation_type="ranked_to_evidence",
        created_at=datetime(2026, 5, 11, tzinfo=UTC),
    )
    lineage_store.record_many([source_item, ranked_item])

    service = StorageApplicationService(tmp_path)

    assert service.list_lineage("run-1").to_dict()["lineage_count"] == 2
    assert service.lineage_upstream(
        run_id="run-1",
        target_type="evidence",
        target_id="ev-1",
    ).lineage_refs == [source_item, ranked_item]
    assert service.lineage_downstream(
        run_id="run-1",
        source_type="source_item",
        source_id="raw-1",
    ).lineage_refs == [source_item]


def test_storage_service_rejects_unsafe_run_id_before_lineage_store_call(tmp_path) -> None:
    fake_store = _FakeLineageStore([])
    service = StorageApplicationService(tmp_path, lineage_store=fake_store)

    with pytest.raises(ValueError):
        service.list_lineage("run:stream")


def test_storage_service_uses_artifact_index_factory_by_default(tmp_path, monkeypatch) -> None:
    old_ref = ArtifactRef(
        artifact_id="raw-old",
        run_id="run-1",
        artifact_type="source_item",
        path="raw.json",
        content_type="application/json",
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    fake_index = _FakeArtifactIndex([old_ref])
    monkeypatch.setattr(
        storage_service_module,
        "artifact_index_store_from_env",
        lambda *, artifact_root: fake_index,
    )

    result = StorageApplicationService(tmp_path).plan_retention(
        now=datetime(2026, 5, 11, tzinfo=UTC)
    )

    assert result.to_dict()["delete_count"] == 1
    assert fake_index.list_all_called is True


def test_storage_service_diagnoses_manifest_artifact_index_consistency(tmp_path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "output.json").write_text('{"ok": true}', encoding="utf-8")
    (run_dir / "metrics.json").write_text('{"count": 1}', encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "artifacts": {
                    "output": "output.json",
                    "metrics": "metrics.json",
                },
            }
        ),
        encoding="utf-8",
    )
    artifact_index = LocalJsonArtifactIndexStore(tmp_path / "_records" / "artifact_index")
    artifact_index.index_artifact(
        ArtifactRef(
            artifact_id="output",
            run_id="run-1",
            artifact_type="output",
            path="output.json",
            content_type="application/json",
            size_bytes=12,
            checksum=sha256(b"different").hexdigest(),
            created_at=datetime(2026, 5, 11, tzinfo=UTC),
        )
    )

    result = StorageApplicationService(tmp_path).diagnose_artifact_index("run-1")
    payload = result.to_dict()

    assert payload["valid"] is False
    assert payload["manifest_artifact_count"] == 2
    assert payload["index_artifact_count"] == 1
    assert payload["missing_index_artifacts"] == ["metrics"]
    assert payload["missing_artifact_files"] == []
    assert payload["checksum_mismatches"] == ["output"]


@pytest.mark.parametrize(
    "run_id",
    ["../secret", "C:secret", "run:stream", "CON", "run. "],
)
def test_storage_service_diagnostics_rejects_unsafe_run_id_before_reading(
    tmp_path,
    run_id,
) -> None:
    with pytest.raises(ValueError):
        StorageApplicationService(tmp_path).diagnose_artifact_index(run_id)


@pytest.mark.parametrize(
    "relative_path",
    ["../secret.json", "C:secret.json", "\\\\server\\share\\secret.json", "a:stream"],
)
def test_storage_service_diagnostics_rejects_unsafe_manifest_artifact_path(
    tmp_path,
    relative_path,
) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": "run-1", "artifacts": {"output": relative_path}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        StorageApplicationService(tmp_path).diagnose_artifact_index("run-1")


def test_storage_service_diagnostics_rejects_symlink_escape(tmp_path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text('{"leaked": true}', encoding="utf-8")
    link = run_dir / "output.json"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available")
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": "run-1", "artifacts": {"output": "output.json"}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        StorageApplicationService(tmp_path).diagnose_artifact_index("run-1")


def test_storage_service_uses_metrics_collector_factory_by_default(tmp_path, monkeypatch) -> None:
    fake_collector = _FakeMetricsCollector()
    monkeypatch.setattr(
        storage_service_module,
        "storage_metrics_collector_from_env",
        lambda *, artifact_root: fake_collector,
    )

    result = StorageApplicationService(tmp_path).metrics()

    assert result.artifacts_count == 7
    assert result.metadata["source"] == "fake"
    assert fake_collector.collect_called is True


def test_storage_service_uses_lineage_store_factory_by_default(tmp_path, monkeypatch) -> None:
    ref = LineageRef(
        run_id="run-1",
        source_type="source_item",
        source_id="raw-1",
        target_type="evidence",
        target_id="ev-1",
        relation_type="source_to_evidence",
    )
    fake_store = _FakeLineageStore([ref])
    monkeypatch.setattr(
        storage_service_module,
        "lineage_store_from_env",
        lambda *, artifact_root: fake_store,
    )

    service = StorageApplicationService(tmp_path)

    assert service.list_lineage("run-1").lineage_refs == [ref]
    assert service.lineage_upstream(
        run_id="run-1",
        target_type="evidence",
        target_id="ev-1",
    ).lineage_refs == [ref]
    assert service.lineage_downstream(
        run_id="run-1",
        source_type="source_item",
        source_id="raw-1",
    ).lineage_refs == [ref]


def test_storage_service_migrates_configured_postgres_repository(tmp_path) -> None:
    repository = _FakePostgresRepository()
    service = StorageApplicationService(tmp_path, repository=repository)

    result = service.migrate_persistence(require_postgres=True)

    payload = result.to_dict()
    assert repository.migrated is True
    assert payload["backend"] == "_FakePostgresRepository"
    assert payload["postgres_required"] is True
    assert "dsn" not in payload


def test_storage_service_require_postgres_rejects_local_repository(tmp_path) -> None:
    service = StorageApplicationService(tmp_path, repository=_FakeLocalRepository())

    with pytest.raises(ValueError, match="NEWS_DATABASE_DSN"):
        service.migrate_persistence(require_postgres=True)


class _FakeArtifactIndex:
    def __init__(self, refs) -> None:
        self.refs = refs
        self.list_all_called = False

    def list_all(self):
        self.list_all_called = True
        return list(self.refs)

    def list_by_run(self, run_id):
        return [ref for ref in self.refs if ref.run_id == run_id]


class _FakeMetricsCollector:
    def __init__(self) -> None:
        self.collect_called = False

    def collect(self):
        self.collect_called = True
        return StorageMetrics(artifacts_count=7, metadata={"source": "fake"})


class _FakeLineageStore:
    def __init__(self, refs) -> None:
        self.refs = refs

    def list_by_run(self, run_id):
        return [ref for ref in self.refs if ref.run_id == run_id]

    def upstream(self, run_id, target_type, target_id):
        return [
            ref
            for ref in self.refs
            if ref.run_id == run_id and ref.target_type == target_type and ref.target_id == target_id
        ]

    def downstream(self, run_id, source_type, source_id):
        return [
            ref
            for ref in self.refs
            if ref.run_id == run_id and ref.source_type == source_type and ref.source_id == source_id
        ]


class _FakePostgresRepository:
    def __init__(self) -> None:
        self.migrated = False

    def migrate(self) -> None:
        self.migrated = True


class _FakeLocalRepository:
    def migrate(self) -> None:
        raise AssertionError("local migration should not run when PostgreSQL is required")
