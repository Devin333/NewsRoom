from __future__ import annotations

from hashlib import sha1
from typing import Any

from business.foundation import BusinessFeedbackEvent, BusinessLearningSignal
from business.foundation.feedback import (
    ImprovementApplier,
    ImprovementMeasurementBuilder,
    ImprovementProposal,
    ImprovementRecommendation,
    ImprovementRecommendationBuilder,
    InMemoryImprovementProposalStore,
    PolicyExperimentProfile,
    SelfImprovementReport,
)
from business.foundation.feedback.policy_experiment import (
    policy_experiment_profile_id,
    policy_experiment_target_type,
)
from business.foundation.feedback.feedback_aggregator import FeedbackAggregator
from business.foundation.feedback.learning_signal_builder import LearningSignalBuilder


class BoardImprovementService:
    def __init__(self, *, proposal_store: Any | None = None) -> None:
        self.proposal_store = proposal_store or InMemoryImprovementProposalStore()
        self.recommendation_builder = ImprovementRecommendationBuilder()
        self.applier = ImprovementApplier()
        self.measurement_builder = ImprovementMeasurementBuilder()

    def collect_feedback(self, feedback_events: list[BusinessFeedbackEvent]) -> list[BusinessFeedbackEvent]:
        seen: set[str] = set()
        result: list[BusinessFeedbackEvent] = []
        for event in feedback_events:
            if event.feedback_id in seen:
                continue
            seen.add(event.feedback_id)
            result.append(event)
        return result

    def build_learning_signals(self, feedback_events: list[BusinessFeedbackEvent]) -> list[BusinessLearningSignal]:
        signals: list[BusinessLearningSignal] = []
        grouped = FeedbackAggregator().group_by_type(feedback_events)
        for events in grouped.values():
            signals.extend(LearningSignalBuilder().build_from_feedback(events))
        return signals

    def build_recommendations(
        self,
        learning_signals: list[BusinessLearningSignal],
        *,
        board_type: str,
        quality_summary: Any | None = None,
    ) -> list[ImprovementRecommendation]:
        recommendations = self.recommendation_builder.build_from_learning_signals(
            learning_signals,
            board_type=board_type,
        )
        recommendations.extend(
            self.recommendation_builder.build_from_quality_summary(
                quality_summary,
                board_type=board_type,
            )
        )
        return _dedupe_recommendations(recommendations)

    def build_proposals(
        self,
        recommendations: list[ImprovementRecommendation],
    ) -> list[ImprovementProposal]:
        proposals: list[ImprovementProposal] = []
        for recommendation in recommendations:
            proposal = ImprovementProposal(
                proposal_id=_stable_id("proposal", recommendation.recommendation_id, recommendation.target_type, recommendation.target_id),
                recommendation_id=recommendation.recommendation_id,
                board_type=recommendation.board_type,
                change_type="policy_experiment",
                target_type=policy_experiment_target_type(recommendation.target_type),
                target_id=recommendation.target_id,
                proposed_patch={},
                risk_level=_risk_level(recommendation.severity),
                requires_approval=True,
                status="proposed",
                experiment_profile=_experiment_profile_for_recommendation(recommendation),
            )
            existing = self.proposal_store.get(proposal.proposal_id)
            proposals.append(existing or self.proposal_store.save(proposal))
        return proposals

    def apply_approved_overrides(self, *, run_id: str, board_type: str):
        proposals = [
            proposal
            for proposal in self.proposal_store.list()
            if proposal.board_type == board_type
        ]
        return self.applier.apply(proposals, run_id=run_id, board_type=board_type)

    def measure(self, before: dict[str, Any] | None, after: dict[str, Any]):
        return self.measurement_builder.measure(before, after)

    def build_report(
        self,
        *,
        feedback_events: list[BusinessFeedbackEvent],
        learning_signals: list[BusinessLearningSignal],
        recommendations: list[ImprovementRecommendation],
        proposals: list[ImprovementProposal],
        applied_overrides: list[dict[str, Any]],
        measurement: Any,
    ) -> SelfImprovementReport:
        risks = [
            f"{proposal.proposal_id}:{proposal.risk_level}"
            for proposal in proposals
            if proposal.risk_level in {"high", "critical"}
        ]
        next_actions = ["review proposed improvements"] if proposals else ["continue monitoring"]
        return SelfImprovementReport(
            feedback_events=[event.to_dict() for event in feedback_events],
            learning_signals=[signal.to_dict() for signal in learning_signals],
            recommendations=[recommendation.to_dict() for recommendation in recommendations],
            proposals=[proposal.to_dict() for proposal in proposals],
            applied_overrides=list(applied_overrides),
            measurement=measurement.to_dict() if hasattr(measurement, "to_dict") else dict(measurement or {}),
            risks=risks,
            next_actions=next_actions,
        )


def _dedupe_recommendations(recommendations: list[ImprovementRecommendation]) -> list[ImprovementRecommendation]:
    seen: set[str] = set()
    result: list[ImprovementRecommendation] = []
    for recommendation in recommendations:
        if recommendation.recommendation_id in seen:
            continue
        seen.add(recommendation.recommendation_id)
        result.append(recommendation)
    return result


def _change_type(target_type: str) -> str:
    return policy_experiment_target_type(target_type)


def _experiment_profile_for_recommendation(recommendation: ImprovementRecommendation) -> PolicyExperimentProfile:
    target_type = _change_type(recommendation.target_type)
    return PolicyExperimentProfile(
        profile_id=policy_experiment_profile_id(
            recommendation.board_type,
            recommendation.recommendation_id,
            target_type,
            recommendation.target_id,
        ),
        board_type=recommendation.board_type,
        target_type=target_type,
        target_id=recommendation.target_id,
        parameters={
            "severity": recommendation.severity,
            "evidence_count": len(recommendation.evidence),
        },
        rationale=recommendation.reason,
        suggested_action=recommendation.suggested_action,
    )


def _risk_level(severity: str) -> str:
    return {"block": "critical", "error": "high", "warning": "medium"}.get(severity, "low")


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = sha1("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


__all__ = ["BoardImprovementService"]
