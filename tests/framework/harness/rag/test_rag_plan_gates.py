from __future__ import annotations

from framework.harness import (
    DeterministicRAGPlanner,
    WorkerRAGPlanner,
    RAGBudget,
    RAGBudgetSnapshot,
    RAGExecutionPolicy,
    RAGGateSuite,
    RetrievalOperation,
    RetrievalPlanCandidate,
    RetrievalStepSpec,
    fake_rag_session_spec,
)
from framework.harness.workers.result import HarnessWorkerResult, HarnessWorkerStatus


def test_plan_gates_reject_duplicate_queries() -> None:
    spec = fake_rag_session_spec()
    policy = RAGExecutionPolicy.from_session_spec(spec)
    plan = RetrievalPlanCandidate(
        candidate_id="duplicate-query-plan",
        queries=(
            RetrievalStepSpec(
                step_id="query-1",
                operation=RetrievalOperation.SEARCH_CORPUS,
                query="Reader repair method evidence",
                corpus="research-papers",
            ),
        ),
    )

    results = RAGGateSuite().verify_plan(
        plan,
        spec=spec,
        policy=policy,
        executed_queries={"reader repair method evidence"},
        projected_snapshot=RAGBudgetSnapshot(queries_used=1, worker_calls_used=1),
    )

    failed = {result.gate_name: result for result in results if not result.passed}
    assert failed["rag_query_dedup"].details["duplicates"] == ["query-1"]


def test_plan_gates_reject_unauthorized_corpus_and_memory_namespace() -> None:
    spec = fake_rag_session_spec()
    policy = RAGExecutionPolicy.from_session_spec(spec)
    plan = RetrievalPlanCandidate(
        candidate_id="unauthorized-plan",
        queries=(
            RetrievalStepSpec(
                step_id="query-private",
                operation=RetrievalOperation.SEARCH_CORPUS,
                query="private notes about reader repair",
                corpus="private-corpus",
            ),
        ),
        memory_recall_plan=(
            RetrievalStepSpec(
                step_id="memory-private",
                operation=RetrievalOperation.RECALL_MEMORY,
                query="reader repair memory",
                memory_namespace="research.private_notes",
            ),
        ),
    )

    result = RAGGateSuite().tool_allowlist.evaluate(plan, policy)

    assert result.passed is False
    assert {item["step_id"] for item in result.details["violations"]} == {"query-private", "memory-private"}


def test_budget_gate_rejects_projected_plan_over_limits() -> None:
    spec = fake_rag_session_spec(budget=RAGBudget(max_rounds=1, max_replans=0, max_queries=0, max_source_reads=0, max_memory_hits=0, max_context_items=2, max_context_tokens=200, max_worker_calls=0))
    policy = RAGExecutionPolicy.from_session_spec(spec)

    result = RAGGateSuite().budget.evaluate(RAGBudgetSnapshot(rounds_used=1, queries_used=1, worker_calls_used=1), policy)

    assert result.passed is False
    assert set(result.details["violations"]) == {"queries", "worker_calls"}


def test_deterministic_planner_marks_initial_query_with_required_evidence_type() -> None:
    spec = fake_rag_session_spec(required_evidence_types=("method", "figure"))

    plan = DeterministicRAGPlanner().plan(spec, round_index=0, gap_report={})

    assert plan.queries[0].metadata["evidence_type"] == "method"


def test_deterministic_planner_prefers_missing_evidence_type_when_replanning() -> None:
    spec = fake_rag_session_spec(required_evidence_types=("method", "figure"))

    plan = DeterministicRAGPlanner().plan(
        spec,
        round_index=1,
        gap_report={"missing_evidence_types": ["figure"]},
    )

    assert plan.queries[0].metadata["evidence_type"] == "figure"
    assert plan.queries[0].query is not None
    assert "figure" in plan.queries[0].query


def test_deterministic_planner_includes_unsupported_claims_in_replan_query() -> None:
    spec = fake_rag_session_spec()

    plan = DeterministicRAGPlanner().plan(
        spec,
        round_index=1,
        gap_report={"unsupported_claims": [{"claim_id": "c1", "text": "experiment table accuracy"}]},
    )

    assert plan.queries[0].query is not None
    assert "experiment table accuracy" in plan.queries[0].query


def test_worker_rag_planner_uses_fallback_before_min_round_index() -> None:
    worker = _Worker({
        "candidate": _candidate_payload("worker-plan", "worker query"),
    })
    spec = fake_rag_session_spec()

    plan = WorkerRAGPlanner(worker, min_round_index=1).plan(
        spec,
        round_index=0,
        gap_report={},
    )

    assert plan.metadata["planner"] == "deterministic"
    assert worker.requests == []


def test_worker_rag_planner_passes_gap_and_executed_queries_to_worker() -> None:
    worker = _Worker({
        "candidate": _candidate_payload("worker-plan", "new query"),
    })
    spec = fake_rag_session_spec()

    plan = WorkerRAGPlanner(worker, min_round_index=1).plan(
        spec,
        round_index=1,
        gap_report={"missing_evidence_types": ["experiment"]},
        executed_queries=("old query",),
    )

    assert plan.candidate_id == "worker-plan"
    assert worker.requests[0]["task_type"] == "rag_plan_candidate"
    assert worker.requests[0]["gap_report"] == {"missing_evidence_types": ["experiment"]}
    assert worker.requests[0]["executed_queries"] == ["old query"]
    assert "halt_workflow" in worker.requests[0]["forbidden_fields"]


def test_worker_rag_planner_falls_back_when_worker_fails() -> None:
    spec = fake_rag_session_spec(required_evidence_types=("method", "experiment"))

    plan = WorkerRAGPlanner(_Worker({}, status=HarnessWorkerStatus.FAILED), min_round_index=0).plan(
        spec,
        round_index=1,
        gap_report={"missing_evidence_types": ["experiment"]},
    )

    assert plan.metadata["planner"] == "deterministic"
    assert plan.queries[0].metadata["evidence_type"] == "experiment"


def _candidate_payload(candidate_id: str, query: str) -> dict:
    return {
        "candidate_id": candidate_id,
        "queries": [
            {
                "step_id": f"{candidate_id}:query",
                "operation": RetrievalOperation.SEARCH_CORPUS.value,
                "query": query,
                "corpus": "research-papers",
                "max_results": 3,
                "metadata": {"evidence_type": "experiment"},
            }
        ],
        "expected_evidence": ["experiment"],
        "expected_gaps": [],
        "confidence": 0.8,
        "metadata": {"planner": "worker"},
    }


class _Worker:
    def __init__(self, output: dict, *, status: HarnessWorkerStatus = HarnessWorkerStatus.SUCCEEDED) -> None:
        self.output = output
        self.status = status
        self.requests = []

    def generate(self, request: dict) -> HarnessWorkerResult:
        self.requests.append(request)
        return HarnessWorkerResult(status=self.status, output=self.output)
