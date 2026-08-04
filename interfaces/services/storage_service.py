from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from framework.agent.artifacts.paths import (
    resolve_artifact_descendant,
    validate_artifact_path_segment,
    validate_relative_artifact_path,
)
from infrastructure.storage.artifacts import ArtifactRef, artifact_index_store_from_env
from infrastructure.storage.lifecycle import (
    ArtifactRetentionPlanner,
    BackupManifest,
    LocalArtifactBackupService,
    LocalArtifactRetentionExecutor,
    RetentionPlan,
    RetentionPolicy,
)
from infrastructure.storage.lineage import LineageRef, lineage_store_from_env
from infrastructure.storage.metrics import StorageMetrics, storage_metrics_collector_from_env
from infrastructure.storage.persistence import repository_from_env

_DEFAULT_ARTIFACT_ROOT = Path(".newsroom/runs")


@dataclass(frozen=True)
class StorageRetentionPlanResult:
    artifact_root: Path
    run_id: str | None
    policy: RetentionPolicy
    plan: RetentionPlan

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_root": str(self.artifact_root),
            "run_id": self.run_id,
            "policy": self.policy.to_dict(),
            "artifact_count": len(self.plan.decisions),
            "delete_count": len(self.plan.delete_decisions),
            "keep_count": len(self.plan.keep_decisions),
            "plan": self.plan.to_dict(),
        }


@dataclass(frozen=True)
class StorageRetentionApplyResult:
    plan_result: StorageRetentionPlanResult
    deleted_artifacts: list[ArtifactRef]

    def to_dict(self) -> dict[str, Any]:
        payload = self.plan_result.to_dict()
        payload.update(
            {
                "deleted_count": len(self.deleted_artifacts),
                "deleted_artifacts": [ref.to_dict() for ref in self.deleted_artifacts],
            }
        )
        return payload


@dataclass(frozen=True)
class StorageBackupResult:
    artifact_root: Path
    backup_path: Path
    manifest: BackupManifest

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_root": str(self.artifact_root),
            "backup_path": str(self.backup_path),
            "file_count": self.manifest.file_count,
            "total_bytes": self.manifest.total_bytes,
            "manifest": self.manifest.to_dict(),
        }


@dataclass(frozen=True)
class StorageRestoreResult:
    artifact_root: Path
    backup_path: Path
    manifest: BackupManifest

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_root": str(self.artifact_root),
            "backup_path": str(self.backup_path),
            "restored_count": self.manifest.file_count,
            "total_bytes": self.manifest.total_bytes,
            "manifest": self.manifest.to_dict(),
        }


@dataclass(frozen=True)
class StorageLineageQueryResult:
    artifact_root: Path
    run_id: str
    query_type: str
    lineage_refs: list[LineageRef]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_root": str(self.artifact_root),
            "run_id": self.run_id,
            "query_type": self.query_type,
            "lineage_count": len(self.lineage_refs),
            "lineage_refs": [ref.to_dict() for ref in self.lineage_refs],
        }


@dataclass(frozen=True)
class StorageMigrationResult:
    artifact_root: Path
    backend: str
    postgres_required: bool
    migrated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_root": str(self.artifact_root),
            "backend": self.backend,
            "postgres_required": self.postgres_required,
            "migrated": self.migrated,
        }


@dataclass(frozen=True)
class ArtifactIndexConsistencyResult:
    artifact_root: Path
    run_id: str
    manifest_path: Path
    valid: bool
    manifest_artifact_count: int
    index_artifact_count: int
    missing_index_artifacts: list[str]
    missing_artifact_files: list[str]
    checksum_mismatches: list[str]
    orphan_index_artifacts: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_root": str(self.artifact_root),
            "run_id": self.run_id,
            "manifest_path": str(self.manifest_path),
            "valid": self.valid,
            "manifest_artifact_count": self.manifest_artifact_count,
            "index_artifact_count": self.index_artifact_count,
            "missing_index_artifacts": list(self.missing_index_artifacts),
            "missing_artifact_files": list(self.missing_artifact_files),
            "checksum_mismatches": list(self.checksum_mismatches),
            "orphan_index_artifacts": list(self.orphan_index_artifacts),
        }


class StorageApplicationService:
    def __init__(
        self,
        artifact_root: str | Path = ".newsroom/runs",
        *,
        artifact_index_store: Any | None = None,
        lineage_store: Any | None = None,
        metrics_collector: Any | None = None,
        repository: Any | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        factory_env = _factory_env(self.artifact_root, env)
        self.artifact_index = artifact_index_store or _call_storage_factory(
            artifact_index_store_from_env,
            artifact_root=self.artifact_root,
            env=factory_env,
        )
        self.metrics_collector = metrics_collector or _call_storage_factory(
            storage_metrics_collector_from_env,
            artifact_root=self.artifact_root,
            env=factory_env,
        )
        self.lineage_store = lineage_store or _call_storage_factory(
            lineage_store_from_env,
            artifact_root=self.artifact_root,
            env=factory_env,
        )
        self.repository = repository or _call_storage_factory(
            repository_from_env,
            artifact_root=self.artifact_root,
            env=factory_env,
        )

    def metrics(self) -> StorageMetrics:
        return self.metrics_collector.collect()

    def migrate_persistence(self, *, require_postgres: bool = False) -> StorageMigrationResult:
        backend = self.repository.__class__.__name__
        if require_postgres and not _is_postgres_repository(self.repository):
            raise ValueError("PostgreSQL migration requires NEWS_DATABASE_DSN")
        self.repository.migrate()
        return StorageMigrationResult(
            artifact_root=self.artifact_root,
            backend=backend,
            postgres_required=require_postgres,
            migrated=True,
        )

    def diagnose_artifact_index(self, run_id: str) -> ArtifactIndexConsistencyResult:
        safe_run_id = validate_artifact_path_segment(run_id, field="run_id")
        run_dir = resolve_artifact_descendant(
            self.artifact_root,
            safe_run_id,
            field="run_id",
        )
        manifest_path = resolve_artifact_descendant(
            run_dir,
            "manifest.json",
            field="run manifest path",
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_artifacts = _manifest_artifact_paths(manifest)
        indexed_refs = self.artifact_index.list_by_run(run_id)
        indexed_by_type_path = {
            (
                ref.artifact_type,
                validate_relative_artifact_path(ref.path, field="indexed artifact path"),
            ): ref
            for ref in indexed_refs
        }
        expected_type_paths = set(_expected_index_type_paths(run_dir, manifest_artifacts))

        missing_index_artifacts: list[str] = []
        missing_artifact_files: list[str] = []
        checksum_mismatches: list[str] = []
        for artifact_key, relative_path in manifest_artifacts.items():
            normalized_path = validate_relative_artifact_path(
                relative_path,
                field="manifest artifact path",
            )
            artifact_path = resolve_artifact_descendant(
                run_dir,
                normalized_path,
                field="manifest artifact path",
            )
            ref = indexed_by_type_path.get((artifact_key, normalized_path))
            if ref is None:
                missing_index_artifacts.append(artifact_key)
            if not artifact_path.exists():
                missing_artifact_files.append(artifact_key)
                continue
            if ref is not None and ref.checksum:
                actual_checksum = sha256(artifact_path.read_bytes()).hexdigest()
                if actual_checksum != ref.checksum:
                    checksum_mismatches.append(artifact_key)

        orphan_index_artifacts = [
            ref.artifact_id
            for ref in indexed_refs
            if (
                ref.artifact_type,
                validate_relative_artifact_path(ref.path, field="indexed artifact path"),
            )
            not in expected_type_paths
        ]
        valid = not (
            missing_index_artifacts
            or missing_artifact_files
            or checksum_mismatches
            or orphan_index_artifacts
        )
        return ArtifactIndexConsistencyResult(
            artifact_root=self.artifact_root,
            run_id=run_id,
            manifest_path=manifest_path,
            valid=valid,
            manifest_artifact_count=len(manifest_artifacts),
            index_artifact_count=len(indexed_refs),
            missing_index_artifacts=missing_index_artifacts,
            missing_artifact_files=missing_artifact_files,
            checksum_mismatches=checksum_mismatches,
            orphan_index_artifacts=orphan_index_artifacts,
        )

    def create_backup(
        self,
        backup_path: str | Path,
        *,
        overwrite: bool = False,
        now: datetime | None = None,
    ) -> StorageBackupResult:
        manifest = LocalArtifactBackupService(self.artifact_root).create_backup(
            backup_path,
            overwrite=overwrite,
            now=now,
        )
        return StorageBackupResult(
            artifact_root=self.artifact_root,
            backup_path=Path(backup_path),
            manifest=manifest,
        )

    def restore_backup(
        self,
        backup_path: str | Path,
        *,
        overwrite: bool = False,
    ) -> StorageRestoreResult:
        manifest = LocalArtifactBackupService(self.artifact_root).restore_backup(
            backup_path,
            overwrite=overwrite,
        )
        return StorageRestoreResult(
            artifact_root=self.artifact_root,
            backup_path=Path(backup_path),
            manifest=manifest,
        )

    def list_lineage(self, run_id: str) -> StorageLineageQueryResult:
        validate_artifact_path_segment(run_id, field="run_id")
        refs = self.lineage_store.list_by_run(run_id)
        return StorageLineageQueryResult(
            artifact_root=self.artifact_root,
            run_id=run_id,
            query_type="list",
            lineage_refs=refs,
        )

    def lineage_upstream(
        self,
        *,
        run_id: str,
        target_type: str,
        target_id: str,
    ) -> StorageLineageQueryResult:
        validate_artifact_path_segment(run_id, field="run_id")
        refs = self.lineage_store.upstream(run_id, target_type, target_id)
        return StorageLineageQueryResult(
            artifact_root=self.artifact_root,
            run_id=run_id,
            query_type="upstream",
            lineage_refs=refs,
        )

    def lineage_downstream(
        self,
        *,
        run_id: str,
        source_type: str,
        source_id: str,
    ) -> StorageLineageQueryResult:
        validate_artifact_path_segment(run_id, field="run_id")
        refs = self.lineage_store.downstream(run_id, source_type, source_id)
        return StorageLineageQueryResult(
            artifact_root=self.artifact_root,
            run_id=run_id,
            query_type="downstream",
            lineage_refs=refs,
        )

    def plan_retention(
        self,
        *,
        policy: RetentionPolicy | None = None,
        run_id: str | None = None,
        now: datetime | None = None,
    ) -> StorageRetentionPlanResult:
        if run_id is not None:
            validate_artifact_path_segment(run_id, field="run_id")
        refs = self.artifact_index.list_by_run(run_id) if run_id else self.artifact_index.list_all()
        actual_policy = policy or RetentionPolicy()
        plan = ArtifactRetentionPlanner(actual_policy).plan(refs, now=now)
        return StorageRetentionPlanResult(
            artifact_root=self.artifact_root,
            run_id=run_id,
            policy=actual_policy,
            plan=plan,
        )

    def apply_retention(
        self,
        *,
        policy: RetentionPolicy | None = None,
        run_id: str | None = None,
        now: datetime | None = None,
    ) -> StorageRetentionApplyResult:
        plan_result = self.plan_retention(policy=policy, run_id=run_id, now=now)
        deleted = LocalArtifactRetentionExecutor(str(self.artifact_root)).delete_expired(
            plan_result.plan
        )
        return StorageRetentionApplyResult(plan_result=plan_result, deleted_artifacts=deleted)


def _is_postgres_repository(repository: Any) -> bool:
    return "Postgres" in repository.__class__.__name__


def _factory_env(artifact_root: Path, env: dict[str, str] | None) -> dict[str, str] | None:
    if env is not None:
        return env
    return None if artifact_root == _DEFAULT_ARTIFACT_ROOT else {}


def _call_storage_factory(
    factory: Any,
    *,
    artifact_root: Path,
    env: dict[str, str] | None,
) -> Any:
    if env is None or "env" not in inspect.signature(factory).parameters:
        return factory(artifact_root=artifact_root)
    return factory(artifact_root=artifact_root, env=env)


def _manifest_artifact_paths(manifest: dict[str, Any]) -> dict[str, str]:
    artifacts = manifest.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        return {}
    return {
        str(artifact_key): str(relative_path)
        for artifact_key, relative_path in artifacts.items()
        if isinstance(relative_path, str)
    }


def _expected_index_type_paths(
    run_dir: Path,
    manifest_artifacts: dict[str, str],
) -> list[tuple[str, str]]:
    expected = [
        (
            artifact_key,
            validate_relative_artifact_path(relative_path, field="manifest artifact path"),
        )
        for artifact_key, relative_path in manifest_artifacts.items()
    ]
    source_index_path = manifest_artifacts.get("source_artifacts")
    if source_index_path is None:
        return expected
    try:
        source_index = resolve_artifact_descendant(
            run_dir,
            validate_relative_artifact_path(
                source_index_path,
                field="source artifact index path",
            ),
            field="source artifact index path",
        )
        payload = json.loads(source_index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return expected
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return expected
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ref_payload = entry.get("artifact_ref")
        if not isinstance(ref_payload, dict):
            continue
        artifact_type = ref_payload.get("artifact_type")
        path = ref_payload.get("path")
        if isinstance(artifact_type, str) and isinstance(path, str):
            expected.append(
                (
                    artifact_type,
                    validate_relative_artifact_path(path, field="indexed artifact path"),
                )
            )
    return expected
