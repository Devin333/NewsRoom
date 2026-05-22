from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from framework import RunResult, WorkflowRunner
from interfaces.services.approval_service import ApprovalApplicationService
from interfaces.services.run_resolution_service import RunResolutionApplicationService
from infrastructure.storage.checkpoint import LocalJsonCheckpointStore


DEFAULT_CHECKPOINT_STORE_PATH = ".newsroom/checkpoints"


@dataclass(frozen=True)
class ApprovalWorkflowResumeResult:
    approval_context: dict[str, object]
    run_result: RunResult

    def to_dict(self) -> dict[str, object]:
        return {
            "approval_context": self.approval_context,
            "run_result": self.run_result.to_dict(),
            "run_id": self.run_result.run_id,
            "workflow_id": self.run_result.workflow_id,
            "workflow_version": self.run_result.workflow_version,
            "status": self.run_result.status.value,
            "output": self.run_result.to_dict()["output"],
            "artifact_dir": self.run_result.artifact_dir,
            "manifest_path": self.run_result.manifest_path,
            "events_path": self.run_result.events_path,
            "error": self.run_result.error,
        }


class ApprovalResumeApplicationService:
    def __init__(
        self,
        *,
        artifact_root: str | Path,
        resolution_service: RunResolutionApplicationService,
        workflow_runner_cls: Callable = WorkflowRunner,
        checkpoint_store_cls: Callable = LocalJsonCheckpointStore,
        artifact_publishers_factory: Callable | None = None,
        artifact_ref_extractors: list[Callable] | None = None,
        lineage_extractors: list[Callable] | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.resolution_service = resolution_service
        self.workflow_runner_cls = workflow_runner_cls
        self.checkpoint_store_cls = checkpoint_store_cls
        self.artifact_publishers_factory = artifact_publishers_factory
        self.artifact_ref_extractors = artifact_ref_extractors or []
        self.lineage_extractors = lineage_extractors or []

    def resume_from_approval(
        self,
        approval_id: str,
        *,
        workflow_id: str = "daily",
        profile: str | None = None,
        run_id: str | None = None,
        decision_key: str = "human_review_decision",
        approval_service: ApprovalApplicationService | None = None,
        checkpoint_store_path: str | Path = DEFAULT_CHECKPOINT_STORE_PATH,
    ) -> ApprovalWorkflowResumeResult:
        resolved = self.resolution_service.resolve_approval_resume_workflow(
            workflow_id,
            profile=profile,
        )
        context = (
            approval_service or ApprovalApplicationService()
        ).build_resume_context(approval_id, decision_key=decision_key)
        is_daily = resolved.workflow.workflow_id.startswith("daily-intelligence")
        runner = self.workflow_runner_cls(
            artifact_root=self.artifact_root,
            function_registry=resolved.registry,
            checkpoint_store=self.checkpoint_store_cls(checkpoint_store_path),
            artifact_publishers=self.artifact_publishers_factory()
            if is_daily and self.artifact_publishers_factory is not None
            else None,
            artifact_ref_extractors=self.artifact_ref_extractors if is_daily else None,
            lineage_extractors=self.lineage_extractors if is_daily else None,
        )
        run_result = runner.resume_from_approval_context(
            resolved.workflow,
            context,
            profile=resolved.profile,
            run_id=run_id,
        )
        return ApprovalWorkflowResumeResult(
            approval_context=context.to_dict(),
            run_result=run_result,
        )


def build_default_approval_resume_service(*, artifact_root: str | Path) -> ApprovalResumeApplicationService:
    from business.boards.cross_board.daily_intelligence import (
        build_daily_intelligence_artifact_publishers,
        daily_artifact_ref_extractors,
        daily_lineage_extractors,
    )

    return ApprovalResumeApplicationService(
        artifact_root=artifact_root,
        resolution_service=RunResolutionApplicationService(),
        artifact_publishers_factory=build_daily_intelligence_artifact_publishers,
        artifact_ref_extractors=daily_artifact_ref_extractors(),
        lineage_extractors=daily_lineage_extractors(),
    )


__all__ = [
    "ApprovalResumeApplicationService",
    "ApprovalWorkflowResumeResult",
    "DEFAULT_CHECKPOINT_STORE_PATH",
    "build_default_approval_resume_service",
]
