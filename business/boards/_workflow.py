from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import Field

from business.boards._service import BoardServiceBase
from business.boards._workflow_execution import BoardWorkflowRunState
from business.boards._workflow_runtime import BoardWorkflowExecution
from business.foundation import (
    AnalysisContext,
    BoardRunResult,
    BoardType,
    BusinessArtifactRef,
    BusinessFeedbackEvent,
    BusinessLearningSignal,
    BusinessMemoryRef,
    BusinessPolicyCandidate,
    BusinessRegressionGuardResult,
    PrimitiveModel,
    build_runtime_quality_closure,
)

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
    artifact_count: int = 0
    evidence_count: int = 0
    memory_ref_count: int = 0
    policy_candidate_count: int = 0
    learning_signal_count: int = 0
    guard_status: str = "unchecked"
    metadata: dict[str, Any] = Field(default_factory=dict)


class BoardWorkflowResult(PrimitiveModel):
    result: BoardRunResult
    trace: BoardWorkflowTrace
    warnings: list[str] = Field(default_factory=list)
    feedback_events: list[BusinessFeedbackEvent] = Field(default_factory=list)
    learning_signals: list[BusinessLearningSignal] = Field(default_factory=list)
    policy_candidates: list[BusinessPolicyCandidate] = Field(default_factory=list)
    guard_results: list[BusinessRegressionGuardResult] = Field(default_factory=list)
    artifact_refs: list[BusinessArtifactRef] = Field(default_factory=list)
    memory_refs: list[BusinessMemoryRef] = Field(default_factory=list)
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
        # Debug/test convenience only. Production callers should read
        # workflow_execution from BoardWorkflowResult.metadata.
        self.last_execution: BoardWorkflowExecution | None = None

    def run(self, items: list[Any], *, context: AnalysisContext | None = None) -> BoardWorkflowResult:
        input_items = list(items)
        run_state = BoardWorkflowRunState(
            execution=BoardWorkflowExecution(
                workflow_id=f"{self.board_type.value}_board_workflow",
                board_type=self.board_type.value,
                metadata={"configured_stages": list(self.workflow_stages)},
            ),
            publish=self._store_execution,
        )

        resolved_context = run_state.run_stage(
            "resolve_context",
            lambda: self.resolve_context(context),
            input_count=1 if context is not None else 0,
            output_count=1,
        )
        selected_signals = run_state.run_stage(
            "select_signals",
            lambda: self.select_signals(input_items, context=resolved_context),
            input_count=len(input_items),
            output_count=lambda signals: len(signals),
            warnings=lambda signals: [] if signals else ["board workflow selected no signals"],
        )
        extraction_results, relation_result, analysis, output = run_state.run_stage(
            "run_pipeline",
            lambda: self.run_pipeline(selected_signals, context=resolved_context),
            input_count=len(selected_signals),
            output_count=lambda pipeline_result: len(pipeline_result[0]),
            metadata=lambda pipeline_result: {
                "relation_count": len(pipeline_result[1].relations),
                "rejected_relation_count": len(pipeline_result[1].rejected_candidates),
            },
        )
        base_result = run_state.run_stage(
            "build_board_run_result",
            lambda: self.build_board_run_result(
                output=output,
                context=resolved_context,
                selected_signals=selected_signals,
                extraction_results=extraction_results,
                relation_result=relation_result,
                analysis=analysis,
            ),
            input_count=len(extraction_results),
            output_count=lambda board_result: len(board_result.cards),
            warnings=lambda board_result: [] if board_result.cards else ["board run result has no cards"],
        )
        result = run_state.run_stage(
            "apply_board_specific_policy",
            lambda: self.apply_board_specific_policy(base_result),
            input_count=len(base_result.cards),
            output_count=lambda board_result: len(board_result.cards),
            warnings=lambda board_result: [] if board_result.cards else ["board policy produced no cards"],
        )
        warnings = run_state.run_stage(
            "collect_quality_feedback",
            lambda: self.collect_quality_feedback(result),
            input_count=len(result.cards),
            output_count=lambda quality_warnings: len(quality_warnings),
            warnings=lambda quality_warnings: quality_warnings,
        )
        workflow_result = run_state.run_stage(
            "return_workflow_result",
            lambda: self._build_workflow_result(
                result=result,
                warnings=warnings,
                input_count=len(input_items),
                selected_signal_count=len(selected_signals),
                extraction_count=len(extraction_results),
                relation_count=len(relation_result.relations),
                rejected_relation_count=len(relation_result.rejected_candidates),
            ),
            input_count=len(result.cards),
            output_count=1,
        )
        execution = run_state.finish()
        return workflow_result.model_copy(
            update={
                "metadata": {
                    **workflow_result.metadata,
                    **execution.to_metadata(),
                }
            }
        )

    def _store_execution(self, execution: BoardWorkflowExecution) -> None:
        self.last_execution = execution

    def _build_workflow_result(
        self,
        *,
        result: BoardRunResult,
        warnings: list[str],
        input_count: int,
        selected_signal_count: int,
        extraction_count: int,
        relation_count: int,
        rejected_relation_count: int,
    ) -> BoardWorkflowResult:
        closure = self._build_runtime_closure(result)
        trace = self._build_trace(
            result=result,
            closure=closure,
            input_count=input_count,
            selected_signal_count=selected_signal_count,
            extraction_count=extraction_count,
            relation_count=relation_count,
            rejected_relation_count=rejected_relation_count,
        )
        self._validate_result(result, trace)
        return BoardWorkflowResult(
            result=result,
            trace=trace,
            warnings=warnings,
            feedback_events=closure.feedback_events,
            learning_signals=closure.learning_signals,
            policy_candidates=closure.policy_candidates,
            guard_results=closure.guard_results,
            artifact_refs=list(result.artifact_refs),
            memory_refs=list(result.memory_refs),
            metadata={
                "board_type": self.board_type.value,
                "board_focus": self.board_focus or _board_focus(result),
                "stages": list(self.workflow_stages),
                "quality_status": trace.quality_status,
                "feedback_count": trace.feedback_count,
                "learning_signal_count": trace.learning_signal_count,
                "policy_candidate_count": trace.policy_candidate_count,
                "guard_status": trace.guard_status,
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
        closure,
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
            feedback_count=len(closure.feedback_events),
            policy_profile_ids=policy_profile_ids,
            artifact_count=len(result.artifact_refs),
            evidence_count=len(result.evidence_refs),
            memory_ref_count=len(result.memory_refs),
            policy_candidate_count=len(closure.policy_candidates),
            learning_signal_count=len(closure.learning_signals),
            guard_status=_guard_status(closure.guard_results),
            metadata={
                "board_focus": self.board_focus or _board_focus(result),
                "policy_profile_count": len(policy_profile_ids),
                "quality_score": result.quality_summary.score if result.quality_summary is not None else None,
                "trace_ref": result.trace_ref.to_dict() if result.trace_ref is not None else None,
                "manifest_ref": result.manifest_ref.to_dict() if result.manifest_ref is not None else None,
            },
        )

    def _build_runtime_closure(self, result: BoardRunResult):
        base_profile = result.policy_snapshot.profiles[0] if result.policy_snapshot is not None and result.policy_snapshot.profiles else None
        return build_runtime_quality_closure(result.feedback_candidates, base_policy_profile=base_profile)

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


def _guard_status(guards: list[BusinessRegressionGuardResult]) -> str:
    if not guards:
        return "unchecked"
    if any(guard.status == "block" or not guard.passed for guard in guards):
        return "block"
    if any(guard.warnings for guard in guards):
        return "warning"
    return "pass"

__all__ = ["BoardWorkflowBase", "BoardWorkflowResult", "BoardWorkflowTrace"]
