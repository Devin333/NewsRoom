from __future__ import annotations

import pytest

from backend.research.domain.reader_repair import ReaderRepairRAGPolicy
from backend.research.reader_repair import ReaderRepairGateSuite


def test_repair_rag_policy_uses_repair_namespace_and_bounded_budget() -> None:
    policy = ReaderRepairRAGPolicy(policy_id="repair-policy")
    results = ReaderRepairGateSuite().verify_rag_policy(policy)

    assert policy.allowed_memory_namespaces == ["research.reader_repair"]
    assert all(result.passed for result in results)


def test_repair_rag_policy_rejects_exhausted_budget() -> None:
    policy = ReaderRepairRAGPolicy(
        policy_id="repair-policy",
        budget={"max_rounds": 0, "max_queries": 3, "max_memory_hits": 4},
    )

    results = ReaderRepairGateSuite().verify_rag_policy(policy)

    budget_result = next(result for result in results if result.gate_name == "RepairRAGBudgetGate")
    assert budget_result.passed is False
    assert budget_result.metadata["budget"] == {"max_rounds": 0}


def test_repair_rag_policy_rejects_namespace_escape() -> None:
    with pytest.raises(ValueError, match="unauthorized memory namespaces"):
        ReaderRepairRAGPolicy(
            policy_id="bad-policy",
            allowed_memory_namespaces=["research.reader_repair", "research.private_notes"],
        )
