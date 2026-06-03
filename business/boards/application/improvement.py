from __future__ import annotations

from typing import Any

from business.foundation import BusinessFeedbackEvent, BusinessLearningSignal
from business.foundation.feedback import (
    FeedbackLearningService,
    ImprovementApplicationService,
    ImprovementMeasurementBuilder,
    ImprovementProposal,
    ImprovementProposalBuilder,
    ImprovementRecommendation,
    ImprovementRecommendationBuilder,
    InMemoryImprovementProposalStore,
    PolicyExperimentApplicationContext,
    SelfImprovementReport,
    SelfImprovementReportBuilder,
)


class BoardImprovementService:
    def __init__(self, *, proposal_store: Any | None = None) -> None:
        self.proposal_store = proposal_store or InMemoryImprovementProposalStore()
        self.recommendation_builder = ImprovementRecommendationBuilder()
        self.proposal_builder = ImprovementProposalBuilder()
        self.feedback_learning_service = FeedbackLearningService()
        self.application_service = ImprovementApplicationService(proposal_store=self.proposal_store)
        self.measurement_builder = ImprovementMeasurementBuilder()
        self.report_builder = SelfImprovementReportBuilder()

    def collect_feedback(self, feedback_events: list[BusinessFeedbackEvent]) -> list[BusinessFeedbackEvent]:
        return self.feedback_learning_service.collect(feedback_events)

    def build_learning_signals(self, feedback_events: list[BusinessFeedbackEvent]) -> list[BusinessLearningSignal]:
        return self.feedback_learning_service.build_learning_signals(feedback_events)

    def build_recommendations(
        self,
        learning_signals: list[BusinessLearningSignal],
        *,
        board_type: str,
        quality_summary: Any | None = None,
    ) -> list[ImprovementRecommendation]:
        return self.recommendation_builder.build(
            learning_signals,
            board_type=board_type,
            quality_summary=quality_summary,
        )

    def build_proposals(
        self,
        recommendations: list[ImprovementRecommendation],
    ) -> list[ImprovementProposal]:
        proposals: list[ImprovementProposal] = []
        for proposal in self.proposal_builder.build_from_recommendations(recommendations):
            existing = self.proposal_store.get(proposal.proposal_id)
            proposals.append(existing or self.proposal_store.save(proposal))
        return proposals

    def apply_approved_policy_experiments(self, *, run_id: str, board_type: str) -> PolicyExperimentApplicationContext:
        return self.application_service.apply_approved_policy_experiments(run_id=run_id, board_type=board_type)

    def apply_approved_policy_profiles(self, *, run_id: str, board_type: str) -> PolicyExperimentApplicationContext:
        return self.apply_approved_policy_experiments(run_id=run_id, board_type=board_type)

    def apply_approved_overrides(self, *, run_id: str, board_type: str) -> PolicyExperimentApplicationContext:
        return self.apply_approved_policy_experiments(run_id=run_id, board_type=board_type)

    def measure(self, before: dict[str, Any] | None, after: dict[str, Any]):
        return self.measurement_builder.measure(before, after)

    def build_report(
        self,
        *,
        feedback_events: list[BusinessFeedbackEvent],
        learning_signals: list[BusinessLearningSignal],
        recommendations: list[ImprovementRecommendation],
        proposals: list[ImprovementProposal],
        measurement: Any,
        policy_experiment_application_context: PolicyExperimentApplicationContext | dict[str, Any] | None = None,
        applied_policy_experiments: list[dict[str, Any]] | None = None,
        applied_overrides: list[dict[str, Any]] | None = None,
    ) -> SelfImprovementReport:
        return self.report_builder.build(
            feedback_events=feedback_events,
            learning_signals=learning_signals,
            recommendations=recommendations,
            proposals=proposals,
            policy_experiment_application_context=policy_experiment_application_context,
            applied_policy_experiments=applied_policy_experiments,
            applied_overrides=applied_overrides,
            measurement=measurement,
        )


__all__ = ["BoardImprovementService"]
