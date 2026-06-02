from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business.boards.cross_board.graph_models import CrossBoardGraphIntelligenceResult
from business.boards.cross_board.policies import cross_board_policy_profile
from business.foundation import (
    BoardRunResult,
    BoardType,
    BusinessFeedbackEvent,
    BusinessQualitySnapshot,
    RegressionGuardRunner,
    build_policy_candidate,
    quality_snapshot_from_checks,
)
from business.foundation.feedback import FeedbackAggregator, LearningSignalBuilder


class CrossBoardRunResultEnricher:
    def attach(
        self,
        result: BoardRunResult,
        cross_insights: list[Any],
        graph_result: CrossBoardGraphIntelligenceResult | None = None,
    ) -> BoardRunResult:
        checks = insight_quality_checks(cross_insights)
        feedback = [*result.feedback_candidates, *feedback_from_cross_insights(cross_insights)]
        if graph_result is not None:
            if graph_result.quality_summary is not None:
                checks.extend(graph_result.quality_summary.checks)
            feedback.extend(feedback_from_graph_result(graph_result))
        quality = merged_quality_summary(result.quality_summary, checks)
        learning = cross_board_learning_closure(feedback)
        metadata = {
            **dict(result.metadata),
            "cross_board_insights": [insight.to_dict() for insight in cross_insights],
            "cross_board_graph": graph_result.graph.to_dict() if graph_result is not None else None,
            "cross_board_paths": [path.to_dict() for path in graph_result.paths] if graph_result is not None else [],
            "cross_board_graph_insights": [insight.to_dict() for insight in graph_result.insights] if graph_result is not None else [],
            "cross_board_graph_quality": graph_result.quality_summary.to_dict() if graph_result is not None and graph_result.quality_summary is not None else None,
            "cross_board_learning_signals": [signal.to_dict() for signal in learning.learning_signals],
            "cross_board_policy_candidates": [candidate.to_dict() for candidate in learning.policy_candidates],
            "cross_board_regression_guard_results": [guard.to_dict() for guard in learning.regression_guard_results],
        }
        return result.model_copy(
            update={
                "quality_summary": quality,
                "feedback_candidates": feedback,
                "metadata": metadata,
            }
        )


@dataclass(frozen=True)
class CrossBoardLearningClosure:
    learning_signals: list[Any]
    policy_candidates: list[Any]
    regression_guard_results: list[Any]


def insight_quality_checks(cross_insights: list[Any]) -> list[Any]:
    checks = []
    for cross_insight in cross_insights:
        if cross_insight.quality_summary is not None:
            checks.extend(cross_insight.quality_summary.checks)
    return checks


def feedback_from_cross_insights(cross_insights: list[Any]) -> list[BusinessFeedbackEvent]:
    feedback: list[BusinessFeedbackEvent] = []
    for cross_insight in cross_insights:
        if cross_insight.guard_result is None or cross_insight.guard_result.passed:
            continue
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
    return feedback


def feedback_from_graph_result(graph_result: CrossBoardGraphIntelligenceResult) -> list[BusinessFeedbackEvent]:
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


def merged_quality_summary(base: BusinessQualitySnapshot | None, checks: list[Any]) -> BusinessQualitySnapshot | None:
    merged = list(base.checks if base is not None else [])
    merged.extend(checks)
    if not merged:
        return base
    passed = sum(1 for check in merged if check.passed)
    return quality_snapshot_from_checks(merged, score=round(passed / len(merged), 4), confidence=0.85)


def cross_board_learning_closure(feedback: list[BusinessFeedbackEvent]) -> CrossBoardLearningClosure:
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
    return CrossBoardLearningClosure(
        learning_signals=learning_signals,
        policy_candidates=policy_candidates,
        regression_guard_results=regression_guard_results,
    )


__all__ = [
    "CrossBoardLearningClosure",
    "CrossBoardRunResultEnricher",
    "cross_board_learning_closure",
    "feedback_from_cross_insights",
    "feedback_from_graph_result",
    "insight_quality_checks",
    "merged_quality_summary",
]
