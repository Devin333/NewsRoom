from __future__ import annotations

from business.research.workflows import build_paper_rag_workflow_spec


def test_paper_rag_workflow_declares_business_projection_only() -> None:
    spec = build_paper_rag_workflow_spec()
    payload = spec.to_dict()

    assert payload["metadata"]["generic_loop_owner"] == "framework.harness.rag"
    assert "execute_retrieval_round" in spec.step_ids
    assert len(spec.step_ids) == len(set(spec.step_ids))
