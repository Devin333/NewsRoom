from __future__ import annotations

from pathlib import Path
from typing import Any

from framework import RunResult, WorkflowRunner
from framework.skills import SkillRunner
from framework.workflow.runners.function import FunctionStepRegistry

from business.boards._artifact_publisher import BoardArtifactPublisher
from business.boards._feedback import BoardFeedbackService
from business.boards._improvement import BoardImprovementService
from business.boards._productized_steps import ProductizedBoardSteps, build_productized_board_workflow
from business.boards._service import BoardServiceBase
from business.foundation import BoardType
from business.foundation.skills import BusinessSkillRuntime


class ProductizedBoardRunnerBase:
    board_type: BoardType
    service_class: type[BoardServiceBase]

    def __init__(
        self,
        *,
        artifact_root: str | Path = ".newsroom/runs",
        board_service: BoardServiceBase | None = None,
        skill_runner: SkillRunner | None = None,
        feedback_service: BoardFeedbackService | None = None,
        improvement_service: BoardImprovementService | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.board_service = board_service or self.service_class()
        self.skill_runner = skill_runner
        self.feedback_service = feedback_service or BoardFeedbackService()
        self.improvement_service = improvement_service or BoardImprovementService()
        self.skill_runtime = BusinessSkillRuntime(skill_runner)
        self.workflow = build_productized_board_workflow(self.board_type)

    def run(
        self,
        *,
        signals: list[dict],
        topic: str | None = None,
        run_id: str | None = None,
    ) -> RunResult:
        resolved_run_id = run_id or f"{self.board_type.value}-productized-run"
        registry = FunctionStepRegistry()
        ProductizedBoardSteps(
            board_type=self.board_type,
            board_service=self.board_service,
            skill_runtime=self.skill_runtime,
            feedback_service=self.feedback_service,
            improvement_service=self.improvement_service,
        ).register(registry)
        runner = WorkflowRunner(
            artifact_root=self.artifact_root,
            function_registry=registry,
            artifact_publishers=[BoardArtifactPublisher(self.board_type.value)],
        )
        return runner.run(
            self.workflow,
            {
                "signals": list(signals),
                "topic": topic,
                "run_id": resolved_run_id,
            },
            profile="business-productized",
            run_id=resolved_run_id,
        )


def runner_for_board_type(
    board_type: str | BoardType,
    *,
    artifact_root: str | Path = ".newsroom/runs",
    board_service: BoardServiceBase | None = None,
    skill_runner: SkillRunner | None = None,
    feedback_service: BoardFeedbackService | None = None,
    improvement_service: BoardImprovementService | None = None,
) -> ProductizedBoardRunnerBase:
    resolved = _board_type(board_type)
    if resolved == BoardType.AI_NEWS:
        from business.boards.ai_news.runner import AINewsRunner

        return AINewsRunner(
            artifact_root=artifact_root,
            board_service=board_service,
            skill_runner=skill_runner,
            feedback_service=feedback_service,
            improvement_service=improvement_service,
        )
    if resolved == BoardType.PROJECT_RADAR:
        from business.boards.project_radar.runner import ProjectRadarRunner

        return ProjectRadarRunner(
            artifact_root=artifact_root,
            board_service=board_service,
            skill_runner=skill_runner,
            feedback_service=feedback_service,
            improvement_service=improvement_service,
        )
    if resolved == BoardType.PAPER_RADAR:
        from business.boards.paper_radar.runner import PaperRadarRunner

        return PaperRadarRunner(
            artifact_root=artifact_root,
            board_service=board_service,
            skill_runner=skill_runner,
            feedback_service=feedback_service,
            improvement_service=improvement_service,
        )
    if resolved == BoardType.COMMUNITY_PULSE:
        from business.boards.community_pulse.runner import CommunityPulseRunner

        return CommunityPulseRunner(
            artifact_root=artifact_root,
            board_service=board_service,
            skill_runner=skill_runner,
            feedback_service=feedback_service,
            improvement_service=improvement_service,
        )
    raise ValueError(f"productized runner is not supported for {resolved.value}")


def _board_type(value: str | BoardType) -> BoardType:
    if isinstance(value, BoardType):
        return value
    normalized = str(value).strip().lower().replace("-", "_")
    try:
        return BoardType(normalized)
    except ValueError as exc:
        raise ValueError(f"unsupported board_type: {value}") from exc


__all__ = ["ProductizedBoardRunnerBase", "runner_for_board_type"]
