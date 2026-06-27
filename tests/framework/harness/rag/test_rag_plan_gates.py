from __future__ import annotations

from framework.harness import (
    DeterministicRAGPlanner,
    RAGBudget,
    RAGBudgetSnapshot,
    RAGExecutionPolicy,
    RAGGateSuite,
    RetrievalOperation,
    RetrievalPlanCandidate,
    RetrievalStepSpec,
    fake_rag_session_spec,
)


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
