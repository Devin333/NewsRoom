from backend.memory.adaptive_thresholds import AdaptiveThresholdSet
from backend.memory.evaluation import MemoryEvaluationReport, MemoryEvaluationRequest
from backend.memory.memory_metrics import MemoryEvaluationMetrics
from backend.memory.policy_learning import MemoryPolicyLearningService


def test_policy_learning_generates_threshold_proposals_from_evaluation_report() -> None:
    service = MemoryPolicyLearningService(AdaptiveThresholdSet())
    report = MemoryEvaluationReport(
        request=MemoryEvaluationRequest(topic="AI"),
        metrics=MemoryEvaluationMetrics(
            claim_support_rate=0.4,
            claim_contradiction_rate=0.3,
            event_duplicate_rate=0.4,
            source_false_positive_rate=0.5,
        ),
        warnings=["memory health degraded"],
    )

    proposals = service.propose_updates(report)
    by_target = {proposal.target: proposal for proposal in proposals}

    assert {"claim_confidence_min", "contradiction_block_threshold", "duplicate_penalty_threshold", "source_reliability_min"}.issubset(
        by_target
    )
    assert by_target["contradiction_block_threshold"].risk_level == "high"
    assert by_target["contradiction_block_threshold"].requires_human_approval is True
    assert by_target["contradiction_block_threshold"].can_auto_apply() is False
    assert by_target["duplicate_penalty_threshold"].risk_level == "low"
    assert by_target["duplicate_penalty_threshold"].can_auto_apply() is True


def test_policy_learning_returns_no_proposals_for_healthy_memory() -> None:
    service = MemoryPolicyLearningService()
    report = MemoryEvaluationReport(
        request=MemoryEvaluationRequest(topic="AI"),
        metrics=MemoryEvaluationMetrics(
            claim_support_rate=0.95,
            claim_contradiction_rate=0.0,
            event_duplicate_rate=0.0,
            source_false_positive_rate=0.0,
        ),
    )

    assert service.propose_updates(report) == []
