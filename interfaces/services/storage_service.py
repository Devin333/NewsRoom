from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from storage.artifacts import ArtifactRef, LocalJsonArtifactIndexStore
from storage.lifecycle import (
    ArtifactRetentionPlanner,
    BackupManifest,
    LocalArtifactBackupService,
    LocalArtifactRetentionExecutor,
    RetentionPlan,
    RetentionPolicy,
)
from storage.lineage import LineageRef, LocalJsonLineageStore
from storage.metrics import LocalStorageMetricsCollector, StorageMetrics


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


class StorageApplicationService:
    def __init__(self, artifact_root: str | Path = ".newsroom/runs") -> None:
        self.artifact_root = Path(artifact_root)
        self.artifact_index = LocalJsonArtifactIndexStore(
            self.artifact_root / "_records" / "artifact_index"
        )
        self.lineage_store = LocalJsonLineageStore(self.artifact_root / "_records" / "lineage")

    def metrics(self) -> StorageMetrics:
        return LocalStorageMetricsCollector(self.artifact_root).collect()

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
