from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business.boards.domain import BoardRunReferences
from business.foundation import (
    AnalysisContext,
    BoardRunPipelineSnapshot,
    BoardRunResult,
    BoardType,
    BusinessFeedbackEvent,
    BusinessPolicySnapshot,
    BusinessQualitySnapshot,
    PolicyLoader,
    Report,
    Signal,
    create_policy_snapshot,
)
from business.layers.output import BoardOutput


@dataclass(frozen=True)
class BoardReportExtractionResult:
    reports: list[Report]
    payloads: list[dict[str, Any]]


@dataclass(frozen=True)
class BoardRunApplicationResult:
    board_type: BoardType
    run_id: str
    output: BoardOutput
    board_output: dict[str, Any]
    report_extraction: BoardReportExtractionResult
    policy_snapshot: BusinessPolicySnapshot
    quality_summary: BusinessQualitySnapshot
    feedback_candidates: list[BusinessFeedbackEvent]
    refs: BoardRunReferences
    pipeline_snapshot: BoardRunPipelineSnapshot

    @property
    def reports(self) -> list[Report]:
        return list(self.report_extraction.reports)

    @property
    def report_payloads(self) -> list[dict[str, Any]]:
        return [dict(payload) for payload in self.report_extraction.payloads]

    def to_board_run_result(self, *, metadata: dict[str, object] | None = None) -> BoardRunResult:
        return BoardRunResult(
            board_type=self.board_type,
            run_id=self.run_id,
            cards=list(self.output.cards),
            detail_pages=list(self.output.detail_pages),
            insights=list(self.output.insights),
            reports=self.reports,
            board_output=dict(self.board_output),
            report_payloads=self.report_payloads,
            pipeline_snapshot=self.pipeline_snapshot,
            policy_snapshot=self.policy_snapshot,
            quality_summary=self.quality_summary,
            feedback_candidates=list(self.feedback_candidates),
            trace_ref=self.refs.trace_ref,
            manifest_ref=self.refs.manifest_ref,
            artifact_refs=list(self.refs.artifact_refs),
            evidence_refs=list(self.refs.evidence_refs),
            memory_refs=list(self.refs.memory_refs),
            metadata=dict(metadata or {}),
        )


class BoardRunApplicationResultBuilder:
    def __init__(
        self,
        *,
        board_type: BoardType,
        policy_loader: PolicyLoader,
        quality_service: Any,
        reference_service: Any,
        report_service: Any,
    ) -> None:
        self.board_type = board_type
        self.policy_loader = policy_loader
        self.quality_service = quality_service
        self.reference_service = reference_service
        self.report_service = report_service

    def build(
        self,
        *,
        output: BoardOutput,
        context: AnalysisContext,
        signals: list[Signal],
        relations,
        pipeline_snapshot: BoardRunPipelineSnapshot,
    ) -> BoardRunApplicationResult:
        run_id = run_id_from_context(context, self.board_type)
        policy_snapshot = self.policy_snapshot(run_id)
        extract = getattr(self.report_service, "extract", None)
        if callable(extract):
            report_extraction = extract(output)
        else:
            report_extraction = BoardReportExtractionResult(
                reports=list(self.report_service.extract_reports(output)),
                payloads=[],
            )
        quality_summary = self.quality_service.build_summary(output)
        feedback_candidates = self.quality_service.feedback_candidates(output, quality_summary, policy_snapshot)
        refs = self.reference_service.build(
            run_id=run_id,
            board_type=self.board_type,
            context=context,
            signals=signals,
            relations=relations,
        )
        return BoardRunApplicationResult(
            board_type=self.board_type,
            run_id=run_id,
            output=output,
            board_output=output.to_dict(),
            report_extraction=report_extraction,
            policy_snapshot=policy_snapshot,
            quality_summary=quality_summary,
            feedback_candidates=feedback_candidates,
            refs=refs,
            pipeline_snapshot=pipeline_snapshot,
        )

    def policy_snapshot(self, run_id: str) -> BusinessPolicySnapshot:
        return create_policy_snapshot(
            run_id,
            self.policy_loader.active_profiles(board_type=self.board_type),
        )


def run_id_from_context(context: AnalysisContext, board_type: BoardType) -> str:
    run_context = getattr(context, "run_context", None)
    if run_context is not None and getattr(run_context, "run_id", None):
        return str(run_context.run_id)
    return f"{board_type.value}-run"


__all__ = [
    "BoardReportExtractionResult",
    "BoardRunApplicationResult",
    "BoardRunApplicationResultBuilder",
    "run_id_from_context",
]
