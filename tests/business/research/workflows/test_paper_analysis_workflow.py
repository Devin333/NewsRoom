from __future__ import annotations

from business.research.workflows import build_paper_analysis_workflow_spec


def test_paper_analysis_workflow_declares_unique_harness_steps() -> None:
    spec = build_paper_analysis_workflow_spec()

    assert spec.workflow_id == "research.paper_analysis"
    assert len(spec.step_ids) == len(set(spec.step_ids))
    assert spec.entry_step_id == "load_paper_source"
    assert "publish_artifacts" in spec.step_ids
    assert spec.to_dict()["terminal_policies"]["publish_requires_verify"] is True
