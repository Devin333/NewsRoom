from business.memory.evaluation import MemoryEvaluationReport, MemoryEvaluationRequest
from business.memory.memory_metrics import MemoryEvaluationMetrics
from interfaces.services.memory_evaluation_service import MemoryEvaluationApplicationService


def test_memory_evaluation_service_evaluates_topic_and_entity() -> None:
    evaluator = _Evaluator()
    service = MemoryEvaluationApplicationService(evaluator)

    topic = service.evaluate_topic("AI", limit=5).to_dict()
    entity = service.evaluate_entity("entity-1", limit=7).to_dict()

    assert topic["request"]["topic"] == "AI"
    assert topic["request"]["limit"] == 5
    assert entity["request"]["entity_id"] == "entity-1"
    assert entity["request"]["limit"] == 7


class _Evaluator:
    def evaluate(self, request):
        return MemoryEvaluationReport(
            request=request,
            metrics=MemoryEvaluationMetrics(claim_support_rate=1.0),
        )
