from business.agents import HistorianAgent, HistorianAgentInput
from business.memory.historical_context import HistoricalContext
from business.memory.intelligence_models import ClaimMemory


def test_historian_agent_reports_repeated_and_contradicted_history() -> None:
    agent = HistorianAgent(_ContextService())

    output = agent.analyze(HistorianAgentInput(topic="AI"))

    assert output.is_new_event is False
    assert output.repeated_claims == ["Repeated claim"]
    assert output.contradictions == ["Contradicted claim"]
    assert "Run quality gate" in output.recommendations[0]
    assert output.to_dict()["historical_context"]["query"] == "AI"


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
