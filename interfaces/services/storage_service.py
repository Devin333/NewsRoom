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


class StorageApplicationService:
    def __init__(self, artifact_root: str | Path = ".newsroom/runs") -> None:
        self.artifact_root = Path(artifact_root)
        self.artifact_index = LocalJsonArtifactIndexStore(
            self.artifact_root / "_records" / "artifact_index"
        )

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
