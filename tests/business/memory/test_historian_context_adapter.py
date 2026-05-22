from business.agents.historian_agent import HistorianAgent
from business.memory.historical_context import HistoricalContext
from business.memory.historian_context_adapter import HistorianContextAdapter, HistorianContextRequest
from business.memory.intelligence_models import ClaimMemory


def test_historian_context_adapter_builds_prompt_context_and_metadata() -> None:
    adapter = HistorianContextAdapter(HistorianAgent(_ContextService()))

    result = adapter.build_context(HistorianContextRequest(topic="AI"))

    assert result.metadata["is_new_event"] is False
    assert result.metadata["repeated_claim_count"] == 1
    assert result.metadata["contradiction_count"] == 1
    assert "Historical analysis:" in result.prompt_context
    assert "Repeated claims:" in result.prompt_context
    assert result.to_dict()["output"]["contradictions"] == ["Contradicted claim"]


class _ContextService:
    def build_context(self, request):
        return HistoricalContext(
            query=request.topic,
            topic=request.topic,
            repeated_claims=[ClaimMemory(claim_id="claim-1", run_id="run-1", text="Repeated claim")],
            contradictions=[
                ClaimMemory(
                    claim_id="claim-2",
                    run_id="run-1",
                    text="Contradicted claim",
                    status="contradicted",
                )
            ],
            timeline_summary="AI timeline",
        )
