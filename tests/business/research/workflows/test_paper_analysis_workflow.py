from __future__ import annotations

from business.research.workflows import build_paper_analysis_workflow_spec


def test_paper_analysis_workflow_declares_unique_harness_steps() -> None:
    spec = build_paper_analysis_workflow_spec()

    assert spec.workflow_id == "research.paper_analysis"
    assert len(spec.step_ids) == len(set(spec.step_ids))
    assert spec.entry_step_id == "load_paper_source"
    assert "publish_artifacts" in spec.step_ids
    assert spec.to_dict()["terminal_policies"]["publish_requires_verify"] is True


def test_paper_analysis_workflow_uses_exact_active_gate_versions() -> None:
    spec = build_paper_analysis_workflow_spec()

    assert {step.step_id: step.quality_gate for step in spec.steps} == {
        "load_paper_source": "PaperSourceLineageGate@1",
        "compile_document": "ResearchDocumentSchemaGate@1",
        "run_research_rag": "ResearchRAGContextProjectionGate@1",
        "build_evidence_pack": "ResearchEvidenceCoverageGate@1",
        "analyze_structure": "SummarySchemaGate@1",
        "analyze_contribution": "SummaryEvidenceCoverageGate@1",
        "analyze_experiments": "BenchmarkEvidenceLineageGate@1",
        "verify_claims": "ClaimEvidenceGate@1",
        "quality_gate": "ResearchQualityGate@1",
        "build_reader_payload": "ReaderPayloadSchemaGate@1",
        "build_paper_card": "ResearchPaperCardGate@1",
        "publish_artifacts": None,
    }
