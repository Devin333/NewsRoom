from __future__ import annotations

from business.research.rag.adapters.plan_worker import ResearchRAGPlanWorker
from framework.harness.workers.result import HarnessWorkerStatus


def test_research_rag_plan_worker_calls_candidate_worker_with_planner_task() -> None:
    worker = _CandidateWorker({"candidate": {"candidate_id": "plan-1", "queries": []}})
    adapter = ResearchRAGPlanWorker(worker)

    result = adapter.generate({"round_index": 1})

    assert result.status == HarnessWorkerStatus.SUCCEEDED
    assert result.output["candidate"]["candidate_id"] == "plan-1"
    assert worker.calls == [("rag_plan_candidate", {"round_index": 1})]


def test_research_rag_plan_worker_failed_result_on_exception() -> None:
    adapter = ResearchRAGPlanWorker(_FailingCandidateWorker())

    result = adapter.generate({"round_index": 1})

    assert result.status == HarnessWorkerStatus.FAILED
    assert "boom" in str(result.error)


def test_research_rag_plan_worker_failed_result_on_non_dict_payload() -> None:
    adapter = ResearchRAGPlanWorker(_CandidateWorker(["not", "a", "dict"]))

    result = adapter.generate({"round_index": 1})

    assert result.status == HarnessWorkerStatus.FAILED
    assert "non-dict" in str(result.error)


class _CandidateWorker:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls = []

    def generate_candidate(self, *, task: str, payload: dict):
        self.calls.append((task, payload))
        return self.payload


class _FailingCandidateWorker:
    def generate_candidate(self, *, task: str, payload: dict):
        raise RuntimeError("boom")
