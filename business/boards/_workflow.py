from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import Field

from business.boards._service import BoardServiceBase
from business.foundation import AnalysisContext, BoardRunResult, BoardType, PrimitiveModel

ServiceT = TypeVar("ServiceT", bound=BoardServiceBase)


class BoardWorkflowTrace(PrimitiveModel):
    board_type: BoardType
    run_id: str
    input_count: int
    selected_signal_count: int
    extraction_count: int
    relation_count: int
    rejected_relation_count: int
    card_count: int
    insight_count: int
    quality_status: str = "unchecked"
    feedback_count: int
    policy_profile_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BoardWorkflowResult(PrimitiveModel):
    result: BoardRunResult
    trace: BoardWorkflowTrace
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BoardWorkflowBase(Generic[ServiceT]):
    board_type: BoardType
    service_class: type[ServiceT]
    board_focus: str = ""
    workflow_stages: tuple[str, ...] = (
        "resolve_context",
        "select_signals",
        "run_pipeline",
        "build_board_run_result",
        "apply_board_specific_policy",
        "collect_quality_feedback",
        "return_workflow_result",
    )

    def __init__(self, service: ServiceT | None = None) -> None:
        self.service = service or self.service_class()

    def run(self, items: list[Any], *, context: AnalysisContext | None = None) -> BoardWorkflowResult:
        input_items = list(items)
        resolved_context = self.resolve_context(context)
        selected_signals = self.select_signals(input_items, context=resolved_context)
        extraction_results, relation_result, analysis, output = self.run_pipeline(
            selected_signals,
            context=resolved_context,
        )
        base_result = self.build_board_run_result(
            output=output,
            context=resolved_context,
            selected_signals=selected_signals,
            extraction_results=extraction_results,
            relation_result=relation_result,
            analysis=analysis,
        )
        result = self.apply_board_specific_policy(base_result)
        warnings = self.collect_quality_feedback(result)
        trace = self._build_trace(
            result=result,
            input_count=len(input_items),
            selected_signal_count=len(selected_signals),
            extraction_count=len(extraction_results),
            relation_count=len(relation_result.relations),
            rejected_relation_count=len(relation_result.rejected_candidates),
        )
        self._validate_result(result, trace)
        return BoardWorkflowResult(
            result=result,
            trace=trace,
            warnings=warnings,
            metadata={
                "board_type": self.board_type.value,
                "board_focus": self.board_focus or _board_focus(result),
                "stages": list(self.workflow_stages),
                "quality_status": trace.quality_status,
                "feedback_count": trace.feedback_count,
            },
        )

    def resolve_context(self, context: AnalysisContext | None) -> AnalysisContext:
        return self.service._resolve_context(context)

    def select_signals(self, items: list[Any], *, context: AnalysisContext) -> list[Any]:
        return self.service._select_signals(items, context=context)

    def run_pipeline(self, selected_signals: list[Any], *, context: AnalysisContext):
        return self.service._run_pipeline_for_selected_signals(selected_signals, context=context)

    def build_board_run_result(
        self,
        *,
        output,
        context: AnalysisContext,
        selected_signals: list[Any],
        extraction_results: list[Any],
        relation_result: Any,
        analysis: Any,
    ) -> BoardRunResult:
        return self.service._build_base_board_run_result(
            output=output,
            context=context,
            signals=selected_signals,
            extraction_results=extraction_results,
            relation_result=relation_result,
            analysis=analysis,
        )

    def apply_board_specific_policy(self, result: BoardRunResult) -> BoardRunResult:
        return self.service.apply_board_specific_policy(result)

    def collect_quality_feedback(self, result: BoardRunResult) -> list[str]:
        quality = result.quality_summary
        warnings = list(quality.warnings if quality is not None else [])
        if not result.cards:
            warnings.append("board workflow produced no cards")
        if quality is not None and quality.requires_review and quality.review_reason:
            warnings.append(quality.review_reason)
        return _dedupe_text(warnings)

    def _build_trace(
        self,
        *,
        result: BoardRunResult,
        input_count: int,
        selected_signal_count: int,
        extraction_count: int,
        relation_count: int,
        rejected_relation_count: int,
    ) -> BoardWorkflowTrace:
        policy_profile_ids = self._board_policy_summary(result)
        quality_status = result.quality_summary.status if result.quality_summary is not None else "unchecked"
        return BoardWorkflowTrace(
            board_type=self.board_type,
            run_id=result.run_id,
            input_count=input_count,
            selected_signal_count=selected_signal_count,
            extraction_count=extraction_count,
            relation_count=relation_count,
            rejected_relation_count=rejected_relation_count,
            card_count=len(result.cards),
            insight_count=len(result.insights),
            quality_status=quality_status,
            feedback_count=len(result.feedback_candidates),
            policy_profile_ids=policy_profile_ids,
            metadata={
                "board_focus": self.board_focus or _board_focus(result),
                "policy_profile_count": len(policy_profile_ids),
                "quality_score": result.quality_summary.score if result.quality_summary is not None else None,
            },
        )

    def _validate_result(self, result: BoardRunResult, trace: BoardWorkflowTrace) -> None:
        if result.board_type != self.board_type:
            raise ValueError(f"workflow result board_type mismatch: {result.board_type.value}")
        if trace.board_type != self.board_type:
            raise ValueError(f"workflow trace board_type mismatch: {trace.board_type.value}")
        if not trace.run_id:
            raise ValueError("workflow trace run_id is required")

    def _board_policy_summary(self, result: BoardRunResult) -> list[str]:
        ids: list[str] = []
        if result.policy_snapshot is not None:
            ids.extend(profile.profile_id for profile in result.policy_snapshot.profiles)
        board_intelligence = result.metadata.get("board_intelligence")
        if isinstance(board_intelligence, dict):
            policy_profile_id = board_intelligence.get("policy_profile_id")
            if policy_profile_id:
                ids.append(str(policy_profile_id))
        for card in result.cards:
            policy_profile_id = card.metadata.get("policy_profile_id") or card.ranking_features.get("policy_profile_id")
            if policy_profile_id:
                ids.append(str(policy_profile_id))
        return _dedupe_text(ids)


def _board_focus(result: BoardRunResult) -> str:
    board_intelligence = result.metadata.get("board_intelligence")
    if isinstance(board_intelligence, dict) and board_intelligence.get("focus"):
        return str(board_intelligence["focus"])
    if result.cards:
        focus = result.cards[0].metadata.get("board_focus") or result.cards[0].ranking_features.get("board_focus")
        if focus:
            return str(focus)
    return result.board_type.value


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


__all__ = ["BoardWorkflowBase", "BoardWorkflowResult", "BoardWorkflowTrace"]
