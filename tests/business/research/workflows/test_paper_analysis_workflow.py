from __future__ import annotations

from business.research.ports.artifact_publication import (
    RESEARCH_ARTIFACT_EFFECT_KIND,
    RESEARCH_ARTIFACT_HANDLER_REF,
)
from business.research.workflows import build_paper_analysis_workflow_spec
from business.research.workflows.paper_analysis_workflow import (
    RESEARCH_ARTIFACT_NOT_REQUIRED_EVIDENCE_REF,
    RESEARCH_ARTIFACT_TERMINAL_POLICY_ID,
    RESEARCH_ARTIFACT_TERMINAL_POLICY_VERSION,
)


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


def test_paper_analysis_workflow_declares_exact_artifact_authority() -> None:
    spec = build_paper_analysis_workflow_spec()
    publish_step = next(
        step for step in spec.steps if step.step_id == "publish_artifacts"
    )

    assert str(publish_step.side_effect_handler) == RESEARCH_ARTIFACT_HANDLER_REF
    assert publish_step.metadata["approval_required"] is False
    assert publish_step.metadata["output_schema"]["required"] == [
        "artifact_bundle_ref",
        "artifact_types",
    ]

    terminal = spec.terminal_side_effect_policy
    assert terminal is not None
    assert terminal.policy_id == RESEARCH_ARTIFACT_TERMINAL_POLICY_ID
    assert terminal.version == RESEARCH_ARTIFACT_TERMINAL_POLICY_VERSION
    assert str(terminal.handler) == RESEARCH_ARTIFACT_HANDLER_REF
    assert terminal.kind == RESEARCH_ARTIFACT_EFFECT_KIND
    assert terminal.requires_approval is False
    assert terminal.retry_limit == 2
    assert terminal.not_required_evidence_ref == (
        RESEARCH_ARTIFACT_NOT_REQUIRED_EVIDENCE_REF
    )
    assert terminal.inherited_gate_refs == ("ResearchQualityGate@1",)
