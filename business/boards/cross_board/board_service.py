from __future__ import annotations

from business.boards._service import BoardServiceBase
from business.boards.cross_board.insight_service import CrossBoardInsightService
from business.boards.cross_board.policies import cross_board_policy_profile
from business.foundation import (
    BoardRunResult,
    BoardType,
    BusinessFeedbackEvent,
    BusinessQualitySnapshot,
    Relation,
    build_policy_candidate,
    quality_snapshot_from_checks,
)
from business.foundation.feedback import FeedbackAggregator, LearningSignalBuilder


class CrossBoardService(BoardServiceBase):
    board_type = BoardType.CROSS_BOARD

    def build_board_run_result(self, signals, *, context=None):
        result = super().build_board_run_result(signals, context=context)
        cross_insights = CrossBoardInsightService().build_insights(
            result.insights,
            _relations_from_metadata(result),
        )
        return _attach_cross_board_intelligence(result, cross_insights)


def _attach_cross_board_intelligence(result: BoardRunResult, cross_insights) -> BoardRunResult:
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
    quality = _quality_summary(result.quality_summary, checks)
    learning_signals = []
    policy_candidates = []
    grouped = FeedbackAggregator().group_by_type(feedback)
    for events in grouped.values():
        for learning_signal in LearningSignalBuilder().build_from_feedback(events):
            learning_signals.append(learning_signal)
            policy_candidates.append(build_policy_candidate(learning_signal, cross_board_policy_profile()))
    metadata = {
        **dict(result.metadata),
        "cross_board_insights": [insight.to_dict() for insight in cross_insights],
        "cross_board_learning_signals": [signal.to_dict() for signal in learning_signals],
        "cross_board_policy_candidates": [candidate.to_dict() for candidate in policy_candidates],
    }
    return result.model_copy(
        update={
            "quality_summary": quality,
            "feedback_candidates": feedback,
            "metadata": metadata,
        }
    )


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
