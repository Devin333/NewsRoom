from __future__ import annotations

from typing import Any

from business.boards._workflow import BoardWorkflowResult
from business.boards.cross_board import CrossBoardGraphIntelligenceResult
from business.foundation import (
    BoardType,
    BusinessFeedbackEvent,
    BusinessQualityCheck,
    BusinessQualitySnapshot,
    build_runtime_quality_closure,
    quality_snapshot_from_checks,
)


class FinalBusinessRunBuilder:
    def __init__(self, result_type: type[Any]) -> None:
        self.result_type = result_type

    def build(
        self,
        workflow_results: dict[str, BoardWorkflowResult],
        cross_board_result: CrossBoardGraphIntelligenceResult,
    ) -> Any:
        feedback_events = _dedupe_feedback(
            [
                event
                for workflow_result in workflow_results.values()
                for event in workflow_result.feedback_events
            ]
            + _feedback_from_cross_board_paths(cross_board_result)
        )
        base_profile = _first_policy_profile(workflow_results)
        final_closure = build_runtime_quality_closure(feedback_events, base_policy_profile=base_profile)
        learning_signals = _dedupe_by_id(
            [
                signal
                for workflow_result in workflow_results.values()
                for signal in workflow_result.learning_signals
            ]
            + final_closure.learning_signals,
            "signal_id",
        )
        policy_candidates = _dedupe_by_id(
            [
                candidate
                for workflow_result in workflow_results.values()
                for candidate in workflow_result.policy_candidates
            ]
            + final_closure.policy_candidates,
            "candidate_id",
        )
        guard_results = _dedupe_by_id(
            [
                guard
                for workflow_result in workflow_results.values()
                for guard in workflow_result.guard_results
            ]
            + [path.guard_result for path in cross_board_result.paths if path.guard_result is not None]
            + final_closure.guard_results,
            "guard_id",
        )
        artifacts = _dedupe_by_id(
            [
                artifact
                for workflow_result in workflow_results.values()
                for artifact in workflow_result.artifact_refs
            ],
            "artifact_id",
        )
        quality_summary = _final_quality_summary(workflow_results, cross_board_result)
        return self.result_type(
            board_workflow_results=workflow_results,
            cross_board_result=cross_board_result,
            cross_board_graph=cross_board_result.graph,
            cross_board_paths=list(cross_board_result.paths),
            cross_board_insights=list(cross_board_result.insights),
            policy_snapshot_refs=_policy_snapshot_refs(workflow_results),
            quality_summary=quality_summary,
            feedback_events=feedback_events,
            learning_signals=learning_signals,
            policy_candidates=policy_candidates,
            regression_guard_results=guard_results,
            artifacts=artifacts,
            metadata={
                "board_count": len(workflow_results),
                "cross_board_path_count": len(cross_board_result.paths),
                "feedback_count": len(feedback_events),
                "learning_signal_count": len(learning_signals),
                "policy_candidate_count": len(policy_candidates),
                "guard_result_count": len(guard_results),
                "artifact_count": len(artifacts),
            },
        )


def _feedback_from_cross_board_paths(cross_board_result: CrossBoardGraphIntelligenceResult) -> list[BusinessFeedbackEvent]:
    events: list[BusinessFeedbackEvent] = []
    for path in cross_board_result.paths:
        if path.guard_result is None or path.guard_result.passed:
            continue
        for check in path.guard_result.checks:
            if check.passed:
                continue
            events.append(
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
                    metadata={"source": "board_workflow_application_service"},
                )
            )
    return events


def _first_policy_profile(workflow_results: dict[str, BoardWorkflowResult]):
    for workflow_result in workflow_results.values():
        snapshot = workflow_result.result.policy_snapshot
        if snapshot is not None and snapshot.profiles:
            return snapshot.profiles[0]
    return None


def _policy_snapshot_refs(workflow_results: dict[str, BoardWorkflowResult]) -> list[str]:
    refs: list[str] = []
    for workflow_result in workflow_results.values():
        snapshot = workflow_result.result.policy_snapshot
        if snapshot is not None:
            refs.append(snapshot.snapshot_id)
    return sorted(set(refs))


def _final_quality_summary(
    workflow_results: dict[str, BoardWorkflowResult],
    cross_board_result: CrossBoardGraphIntelligenceResult,
) -> BusinessQualitySnapshot:
    checks: list[BusinessQualityCheck] = []
    for workflow_result in workflow_results.values():
        quality = workflow_result.result.quality_summary
        if quality is not None:
            checks.extend(quality.checks)
    if cross_board_result.quality_summary is not None:
        checks.extend(cross_board_result.quality_summary.checks)
    checks.append(
        BusinessQualityCheck.create(
            "final_business_run_has_all_boards",
            passed=len(workflow_results) == 4,
            severity="block",
            reason="Final business run must include four board workflows.",
            observed={"board_count": len(workflow_results)},
        )
    )
    checks.append(
        BusinessQualityCheck.create(
            "final_business_run_has_cross_board_graph",
            passed=bool(cross_board_result.graph.nodes),
            severity="block",
            reason="Final business run must include cross-board graph nodes.",
            observed={"node_count": len(cross_board_result.graph.nodes)},
        )
    )
    passed = sum(1 for check in checks if check.passed)
    return quality_snapshot_from_checks(checks, score=round(passed / len(checks), 4), confidence=0.85)


def _dedupe_feedback(events: list[BusinessFeedbackEvent]) -> list[BusinessFeedbackEvent]:
    return _dedupe_by_id(events, "feedback_id")


def _dedupe_by_id(values: list[Any], attr: str) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        if value is None:
            continue
        identifier = str(getattr(value, attr))
        if identifier in seen:
            continue
        seen.add(identifier)
        result.append(value)
    return result


__all__ = [
    "FinalBusinessRunBuilder",
]
