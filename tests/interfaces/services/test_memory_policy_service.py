from backend.memory.evaluation import MemoryEvaluationReport, MemoryEvaluationRequest
from backend.memory.memory_metrics import MemoryEvaluationMetrics
from backend.memory.policy_learning import MemoryPolicyLearningService
from interfaces.services.memory_policy_service import MemoryPolicyApplicationService


def test_memory_policy_service_exposes_proposals_requiring_human_approval() -> None:
    service = MemoryPolicyApplicationService(MemoryPolicyLearningService())
    report = MemoryEvaluationReport(
        request=MemoryEvaluationRequest(topic="AI"),
        metrics=MemoryEvaluationMetrics(claim_contradiction_rate=0.4),
    )

    payload = service.propose_from_report(report).to_dict()

    assert payload["count"] >= 1
    assert payload["requires_human_approval"]
    assert any(proposal["risk_level"] == "high" for proposal in payload["requires_human_approval"])
