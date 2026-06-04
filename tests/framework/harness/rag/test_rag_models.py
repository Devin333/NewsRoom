from __future__ import annotations

from framework.harness import (
    RAGBudget,
    RAGBudgetSnapshot,
    RetrievalOperation,
    RetrievalPlanCandidate,
    RetrievalStepSpec,
    fake_rag_session_spec,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.rag import ensure_jsonable_rag_model


def test_rag_session_spec_requires_explicit_allowlists_and_budget() -> None:
    spec = fake_rag_session_spec()

    assert spec.allowed_corpora == ("research-papers",)
    assert spec.allowed_memory_namespaces == ("research.reader_repair",)
    assert spec.allowed_tools == ("retrieval.read_source",)
    assert spec.budget.max_rounds > 0


def test_retrieval_plan_candidate_rejects_flow_control_fields() -> None:
    step = RetrievalStepSpec(
        step_id="query-1",
        operation=RetrievalOperation.SEARCH_CORPUS,
        query="reader repair method evidence",
        corpus="research-papers",
    )

    try:
        RetrievalPlanCandidate(candidate_id="bad-plan", queries=(step,), metadata={"write_memory": True})
    except HarnessValidationError as exc:
        assert exc.details["forbidden"] == ["write_memory"]
    else:
        raise AssertionError("expected HarnessValidationError")


def test_rag_models_are_json_serializable() -> None:
    snapshot = RAGBudgetSnapshot().with_usage(rounds=1, queries=2, source_reads=3)
    budget = RAGBudget.safe_default()

    ensure_jsonable_rag_model({"budget": budget, "snapshot": snapshot, "spec": fake_rag_session_spec()})

    assert snapshot.queries_used == 2
