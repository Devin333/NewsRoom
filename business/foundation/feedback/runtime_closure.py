from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from business.foundation.models import (
    BusinessFeedbackEvent,
    BusinessLearningSignal,
    BusinessPolicyCandidate,
    BusinessPolicyProfile,
    BusinessQualityCheck,
    BusinessQualitySnapshot,
    BusinessRegressionGuardResult,
)
from business.foundation.policies.policy_candidate import build_policy_candidate
from business.foundation.policies.regression_guard import RegressionGuardRunner
from business.foundation.feedback.feedback_aggregator import FeedbackAggregator
from business.foundation.feedback.learning_signal_builder import LearningSignalBuilder


@dataclass(frozen=True)
class RuntimeQualityClosure:
    feedback_events: list[BusinessFeedbackEvent]
    learning_signals: list[BusinessLearningSignal]
    policy_candidates: list[BusinessPolicyCandidate]
    guard_results: list[BusinessRegressionGuardResult]

    def to_dict(self) -> dict[str, object]:
        return {
            "feedback_events": [event.to_dict() for event in self.feedback_events],
            "learning_signals": [signal.to_dict() for signal in self.learning_signals],
            "policy_candidates": [candidate.to_dict() for candidate in self.policy_candidates],
            "guard_results": [guard.to_dict() for guard in self.guard_results],
        }


def build_feedback_events_from_quality(
    quality: BusinessQualitySnapshot | None,
    *,
    target_object_type: str,
    target_object_id: str | None,
    target_layer: str,
    board_type: str | None,
    policy_profile: BusinessPolicyProfile | None = None,
    existing_events: Iterable[BusinessFeedbackEvent] = (),
) -> list[BusinessFeedbackEvent]:
    events = list(existing_events)
    if quality is None:
        return _dedupe_events(events)
    for check in quality.checks:
        if check.passed:
            continue
        events.append(
            _event_from_check(
                check,
                target_object_type=target_object_type,
                target_object_id=target_object_id,
                target_layer=target_layer,
                board_type=board_type,
                policy_profile=policy_profile,
            )
        )
    return _dedupe_events(events)


def build_runtime_quality_closure(
    feedback_events: Iterable[BusinessFeedbackEvent],
    *,
    base_policy_profile: BusinessPolicyProfile | None = None,
) -> RuntimeQualityClosure:
    events = _dedupe_events(list(feedback_events))
    learning_signals: list[BusinessLearningSignal] = []
    policy_candidates: list[BusinessPolicyCandidate] = []
    guard_results: list[BusinessRegressionGuardResult] = []
    grouped = FeedbackAggregator().group_by_type(events)
    for grouped_events in grouped.values():
        learning_signals.extend(LearningSignalBuilder().build_from_feedback(grouped_events))
    if base_policy_profile is not None:
        for learning_signal in learning_signals:
            candidate = build_policy_candidate(learning_signal, base_policy_profile)
            policy_candidates.append(candidate)
            guard_results.append(RegressionGuardRunner().run(candidate))
    return RuntimeQualityClosure(
        feedback_events=events,
        learning_signals=learning_signals,
        policy_candidates=policy_candidates,
        guard_results=guard_results,
    )


def _event_from_check(
    check: BusinessQualityCheck,
    *,
    target_object_type: str,
    target_object_id: str | None,
    target_layer: str,
    board_type: str | None,
    policy_profile: BusinessPolicyProfile | None,
) -> BusinessFeedbackEvent:
    return BusinessFeedbackEvent.create(
        target_object_type=target_object_type,
        target_object_id=target_object_id,
        target_layer=target_layer,
        board_type=board_type,
        feedback_type=check.check_type,
        severity=check.severity,
        observed=check.observed,
        expected=check.expected,
        error_tags=[check.check_type],
        evidence_refs=list(check.evidence_refs),
        trace_ref=check.trace_ref,
        related_policy_profile_id=policy_profile.profile_id if policy_profile else None,
        related_policy_profile_version=policy_profile.version if policy_profile else None,
        metadata={"source": "runtime_quality_closure", **dict(check.metadata)},
    )


def _dedupe_events(events: list[BusinessFeedbackEvent]) -> list[BusinessFeedbackEvent]:
    seen: set[str] = set()
    result: list[BusinessFeedbackEvent] = []
    for event in events:
        if event.feedback_id in seen:
            continue
        seen.add(event.feedback_id)
        result.append(event)
    return result


__all__ = [
    "RuntimeQualityClosure",
    "build_feedback_events_from_quality",
    "build_runtime_quality_closure",
]
