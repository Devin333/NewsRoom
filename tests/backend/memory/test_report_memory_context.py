from backend.memory.intelligence_context import IntelligenceMemoryContext
from backend.memory.intelligence_models import ClaimMemory
from backend.memory.report_memory_context import ReportMemoryContextRequest, ReportMemoryContextService


def test_report_memory_context_service_builds_prompt_context() -> None:
    service = ReportMemoryContextService(_FakeRecallService())

    result = service.build_context(ReportMemoryContextRequest(topic="AI", run_id="run-1"))

    assert result.topic == "AI"
    assert result.context.topic == "AI"
    assert "Known claims:" in result.prompt_context
    assert result.to_dict()["context"]["claims"][0]["text"] == "Known historical claim"


class _FakeRecallService:
    def recall_for_topic(self, topic: str, *, limit: int = 8) -> IntelligenceMemoryContext:
        return IntelligenceMemoryContext(
            query=topic,
            topic=topic,
            claims=[
                ClaimMemory(
                    claim_id="claim-1",
                    run_id="run-1",
                    text="Known historical claim",
                )
            ],
            metadata={"memory_available": True},
        )
