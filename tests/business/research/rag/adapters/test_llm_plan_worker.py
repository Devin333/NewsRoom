from __future__ import annotations

from business.research.ports.llm_worker import ResearchCandidateWorkerPort
from business.research.rag.adapters.llm_plan_worker import LLMResearchRAGPlanCandidateWorker
from business.research.rag.adapters.plan_worker import ResearchRAGPlanWorker
from framework.harness.rag.fake import fake_rag_session_spec
from framework.harness.workers.result import HarnessWorkerStatus


def test_llm_research_rag_plan_worker_returns_candidate_payload() -> None:
    prompts: list[str] = []

    async def llm(prompt: str) -> str:
        prompts.append(prompt)
        return """
```json
{
  "candidate": {
    "candidate_id": "llm-plan-1",
    "queries": [
      {
        "step_id": "llm-plan-1:query",
        "operation": "search_corpus",
        "query": "experiment result table",
        "corpus": "research-papers",
        "max_results": 3,
        "metadata": {"evidence_type": "experiment"}
      }
    ],
    "expected_evidence": ["experiment"],
    "expected_gaps": [],
    "confidence": 0.72,
    "metadata": {"planner": "llm"}
  }
}
```
"""

    worker = LLMResearchRAGPlanCandidateWorker(llm)

    output = worker.generate_candidate(
        task="rag_plan_candidate",
        payload={
            "round_index": 1,
            "gap_report": {"missing_evidence_types": ["experiment"]},
            "executed_queries": ["method query"],
        },
    )

    assert isinstance(worker, ResearchCandidateWorkerPort)
    assert output["candidate"]["candidate_id"] == "llm-plan-1"
    assert output["candidate"]["queries"][0]["metadata"]["evidence_type"] == "experiment"
    assert "Do not include workflow routing" in prompts[0]
    assert "method query" in prompts[0]


def test_llm_research_rag_plan_worker_invalid_json_fails_through_adapter() -> None:
    worker = ResearchRAGPlanWorker(
        LLMResearchRAGPlanCandidateWorker(lambda prompt: "not json")
    )

    result = worker.generate({"round_index": 1})

    assert result.status == HarnessWorkerStatus.FAILED
    assert "valid JSON" in str(result.error)


def test_llm_research_rag_plan_worker_requires_candidate_object() -> None:
    worker = ResearchRAGPlanWorker(
        LLMResearchRAGPlanCandidateWorker(lambda prompt: '{"candidate": []}')
    )

    result = worker.generate({"round_index": 1})

    assert result.status == HarnessWorkerStatus.FAILED
    assert "candidate object" in str(result.error)


def test_llm_research_rag_plan_worker_forwards_execution_identity_to_llm() -> None:
    identities = []

    def llm(prompt: str, *, execution_identity=None) -> str:
        identities.append(execution_identity)
        return '{"candidate":{"candidate_id":"plan-1","queries":[]}}'

    identity = (
        fake_rag_session_spec()
        .graph_identity.with_physical_activity(
            node_id="build_evidence_context",
            node_instance_id="build-evidence-context:1",
            activity_id="activity-1",
            activity_attempt=1,
        )
        .to_graph_execution_identity()
    )
    worker = LLMResearchRAGPlanCandidateWorker(llm)

    output = worker.generate_candidate(
        task="rag_plan_candidate",
        payload={"round_index": 1},
        execution_identity=identity,
    )

    assert output["candidate"]["candidate_id"] == "plan-1"
    assert identities == [identity]
