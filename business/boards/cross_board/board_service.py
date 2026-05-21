from __future__ import annotations

from business.boards._service import BoardServiceBase
from business.boards.cross_board.graph_builder import CrossBoardGraphBuilder
from business.boards.cross_board.graph_models import CrossBoardGraphIntelligenceResult
from business.boards.cross_board.graph_quality import CrossBoardGraphQualityEvaluator
from business.boards.cross_board.insight_service import CrossBoardInsightService
from business.boards.cross_board.insight_ranker import CrossBoardInsightRanker
from business.boards.cross_board.path_finder import CrossBoardPathFinder
from business.boards.cross_board.policies import cross_board_policy_profile
from business.foundation import (
    BoardRunResult,
    BoardType,
    BusinessFeedbackEvent,
    BusinessQualitySnapshot,
    Relation,
    RegressionGuardRunner,
    build_policy_candidate,
    quality_snapshot_from_checks,
)
from business.foundation.feedback import FeedbackAggregator, LearningSignalBuilder


class CrossBoardService(BoardServiceBase):
    board_type = BoardType.CROSS_BOARD

    def build_board_run_result(self, signals, *, context=None):
        resolved_context = self._resolve_context(context)
        selected_signals, extraction_results, relation_result, analysis, output = self._run_pipeline_for_output(
            signals,
            context=resolved_context,
        )
        result = self._build_base_board_run_result(
            output=output,
            context=resolved_context,
            signals=selected_signals,
            extraction_results=extraction_results,
            relation_result=relation_result,
            analysis=analysis,
        )
        cross_insights = CrossBoardInsightService().build_insights(
            result.insights,
            relation_result.relations,
            analysis=analysis,
        )
        graph_result = self.build_graph_intelligence_from_processed(
            signals=selected_signals,
            extraction_results=extraction_results,
            relations=relation_result.relations,
            analysis=analysis,
            board_outputs={self.board_type.value: output},
        )
        return _attach_cross_board_intelligence(result, cross_insights, graph_result)

    def build_graph_intelligence(self, signals, *, context=None, board_outputs=None) -> CrossBoardGraphIntelligenceResult:
        resolved_context = self._resolve_context(context)
        selected_signals, extraction_results, relation_result, analysis, output = self._run_pipeline_for_output(
            signals,
            context=resolved_context,
        )
        outputs = dict(board_outputs or {})
        outputs.setdefault(self.board_type.value, output)
        return self.build_graph_intelligence_from_processed(
            signals=selected_signals,
            extraction_results=extraction_results,
            relations=relation_result.relations,
            analysis=analysis,
            board_outputs=outputs,
        )

    def build_graph_intelligence_from_processed(
        self,
        *,
        signals,
        extraction_results,
        relations,
        analysis=None,
        board_outputs=None,
    ) -> CrossBoardGraphIntelligenceResult:
        graph = CrossBoardGraphBuilder().build(
            signals=list(signals),
            extraction_results=list(extraction_results),
            relations=list(relations),
            analysis=analysis,
            board_outputs=board_outputs or {},
        )
        path_result = CrossBoardPathFinder().find_paths(graph)
        quality_summary = CrossBoardGraphQualityEvaluator().evaluate(path_result.paths)
        insights = CrossBoardInsightRanker().rank(path_result.paths)
        return CrossBoardGraphIntelligenceResult(
            graph=graph,
            paths=path_result.paths,
            insights=insights,
            quality_summary=quality_summary,
            metadata={
                "relation_count": len(relations),
                "path_count": len(path_result.paths),
                "insight_count": len(insights),
            },
        )


def _attach_cross_board_intelligence(result: BoardRunResult, cross_insights, graph_result: CrossBoardGraphIntelligenceResult | None = None) -> BoardRunResult:
    checks = []
    feedback = list(result.feedback_candidates)
    for cross_insight in cross_insights:
        if cross_insight.quality_summary is not None:
            checks.extend(cross_insight.quality_summary.checks)
        if cross_insight.guard_result is not None and not cross_insight.guard_result.passed:
            for check in cross_insight.guard_result.checks:
                if check.passed:
                    continue
                feedback.append(
                    BusinessFeedbackEvent.create(
                        target_object_type="cross_board_insight",
                        target_object_id=cross_insight.insight.insight_id,
                        target_layer="cross_board",
                        board_type=BoardType.CROSS_BOARD.value,
                        feedback_type=check.check_type,
                        severity=check.severity,
                        observed=check.observed,
                        expected=check.expected,
                        error_tags=[check.check_type],
                        evidence_refs=list(check.evidence_refs),
                        related_policy_profile_id=cross_board_policy_profile().profile_id,
                        related_policy_profile_version=cross_board_policy_profile().version,
                        metadata={"source": "cross_board_guard"},
                    )
                )
    if graph_result is not None:
        if graph_result.quality_summary is not None:
            checks.extend(graph_result.quality_summary.checks)
        feedback.extend(_feedback_from_graph_result(graph_result))
    quality = _quality_summary(result.quality_summary, checks)
    learning_signals = []
    policy_candidates = []
    regression_guard_results = []
    grouped = FeedbackAggregator().group_by_type(feedback)
    for events in grouped.values():
        for learning_signal in LearningSignalBuilder().build_from_feedback(events):
            learning_signals.append(learning_signal)
            candidate = build_policy_candidate(learning_signal, cross_board_policy_profile())
            policy_candidates.append(candidate)
            regression_guard_results.append(RegressionGuardRunner().run(candidate))
    metadata = {
        **dict(result.metadata),
        "cross_board_insights": [insight.to_dict() for insight in cross_insights],
        "cross_board_graph": graph_result.graph.to_dict() if graph_result is not None else None,
        "cross_board_paths": [path.to_dict() for path in graph_result.paths] if graph_result is not None else [],
        "cross_board_graph_insights": [insight.to_dict() for insight in graph_result.insights] if graph_result is not None else [],
        "cross_board_graph_quality": graph_result.quality_summary.to_dict() if graph_result is not None and graph_result.quality_summary is not None else None,
        "cross_board_learning_signals": [signal.to_dict() for signal in learning_signals],
        "cross_board_policy_candidates": [candidate.to_dict() for candidate in policy_candidates],
        "cross_board_regression_guard_results": [guard.to_dict() for guard in regression_guard_results],
    }
    return result.model_copy(
        update={
            "quality_summary": quality,
            "feedback_candidates": feedback,
            "metadata": metadata,
        }
    )


def _feedback_from_graph_result(graph_result: CrossBoardGraphIntelligenceResult) -> list[BusinessFeedbackEvent]:
    feedback: list[BusinessFeedbackEvent] = []
    for path in graph_result.paths:
        if path.guard_result is None or path.guard_result.passed:
            continue
        for check in path.guard_result.checks:
            if check.passed:
                continue
            feedback.append(
                BusinessFeedbackEvent.create(
                    target_object_type="cross_board_path",
                    target_object_id=path.path_id,
                    target_layer="cross_board_graph",
                    board_type=BoardType.CROSS_BOARD.value,
                    feedback_type=check.check_type,
                    severity=check.severity,
                    observed=check.observed,
                    expected=check.expected,
                    error_tags=[check.check_type],
                    evidence_refs=list(check.evidence_refs),
                    related_policy_profile_id=cross_board_policy_profile().profile_id,
                    related_policy_profile_version=cross_board_policy_profile().version,
                    metadata={"source": "cross_board_graph_guard", "technology_id": path.technology_ref.object_id},
                )
            )
    return feedback


def _quality_summary(base: BusinessQualitySnapshot | None, checks) -> BusinessQualitySnapshot | None:
    merged = list(base.checks if base is not None else [])
    merged.extend(checks)
    if not merged:
        return base
    passed = sum(1 for check in merged if check.passed)
    return quality_snapshot_from_checks(merged, score=round(passed / len(merged), 4), confidence=0.85)


def _relations_from_metadata(result: BoardRunResult):
    payload = result.metadata.get("processed_relations")
    if not isinstance(payload, list):
        return []
    relations = []
    for item in payload:
        if isinstance(item, dict):
            relations.append(Relation.model_validate(_drop_computed_fields(item)))
    return relations


def _drop_computed_fields(value):
    if isinstance(value, dict):
        return {
            key: _drop_computed_fields(item)
            for key, item in value.items()
            if key != "level"
        }
    if isinstance(value, list):
        return [_drop_computed_fields(item) for item in value]
    return value
