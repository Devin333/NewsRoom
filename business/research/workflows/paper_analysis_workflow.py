from __future__ import annotations

from framework.events.canonical import checksum_for
from framework.harness.side_effects import HarnessTerminalSideEffectPolicy
from framework.harness.workflow import (
    HarnessGraphSpec,
    HarnessStepSpec,
    HarnessWorkerType,
    HarnessWorkflowSpec,
    ParallelAll,
    ParallelBranch,
    Sequence,
    StepRef,
    VerifiedAggregation,
)

from business.research.ports.artifact_publication import (
    RESEARCH_ARTIFACT_EFFECT_KIND,
    RESEARCH_ARTIFACT_HANDLER_REF,
)


RESEARCH_ARTIFACT_TERMINAL_POLICY_ID = "research.artifact.publication"
RESEARCH_ARTIFACT_TERMINAL_POLICY_VERSION = "1"
RESEARCH_ARTIFACT_NOT_REQUIRED_EVIDENCE_REF = checksum_for(
    {
        "policy": "not_required",
        "handler": RESEARCH_ARTIFACT_HANDLER_REF,
        "policy_id": RESEARCH_ARTIFACT_TERMINAL_POLICY_ID,
        "version": RESEARCH_ARTIFACT_TERMINAL_POLICY_VERSION,
    }
)


def build_paper_analysis_workflow_spec() -> HarnessWorkflowSpec:
    steps = (
        HarnessStepSpec(
            step_id="load_paper_source",
            worker_type=HarnessWorkerType.SCRIPT,
            output_key="paper_source",
            quality_gate="PaperSourceLineageGate@1",
        ),
        HarnessStepSpec(
            step_id="compile_document",
            worker_type=HarnessWorkerType.SCRIPT,
            input_keys=("paper_source",),
            output_key="document",
            quality_gate="ResearchDocumentSchemaGate@1",
        ),
        HarnessStepSpec(
            step_id="run_research_rag",
            worker_type=HarnessWorkerType.RETRIEVAL,
            input_keys=("document",),
            output_key="research_rag_context",
            quality_gate="ResearchRAGContextProjectionGate@1",
        ),
        HarnessStepSpec(
            step_id="build_evidence_pack",
            worker_type=HarnessWorkerType.SCRIPT,
            input_keys=("document", "research_rag_context"),
            output_key="evidence_pack",
            quality_gate="ResearchEvidenceCoverageGate@1",
        ),
        HarnessStepSpec(
            step_id="analyze_structure",
            worker_type=HarnessWorkerType.SUBAGENT,
            input_keys=("document", "evidence_pack"),
            output_key="structure_candidate",
            quality_gate="SummarySchemaGate@1",
        ),
        HarnessStepSpec(
            step_id="analyze_contribution",
            worker_type=HarnessWorkerType.SUBAGENT,
            input_keys=("document", "evidence_pack"),
            output_key="contribution_candidate",
            quality_gate="SummaryEvidenceCoverageGate@1",
        ),
        HarnessStepSpec(
            step_id="analyze_experiments",
            worker_type=HarnessWorkerType.SUBAGENT,
            input_keys=("document", "evidence_pack"),
            output_key="experiment_candidate",
            quality_gate="BenchmarkEvidenceLineageGate@1",
        ),
        HarnessStepSpec(
            step_id="verify_claims",
            worker_type=HarnessWorkerType.QUALITY_GATE,
            input_keys=("evidence_pack", "analysis_branch_refs"),
            output_key="claim_verification",
            quality_gate="ClaimEvidenceGate@1",
        ),
        HarnessStepSpec(
            step_id="quality_gate",
            worker_type=HarnessWorkerType.QUALITY_GATE,
            input_keys=("claim_verification",),
            output_key="research_quality",
            quality_gate="ResearchQualityGate@1",
        ),
        HarnessStepSpec(
            step_id="build_reader_payload",
            worker_type=HarnessWorkerType.SCRIPT,
            input_keys=("document", "evidence_pack", "research_quality"),
            output_key="reader_payload",
            quality_gate="ReaderPayloadSchemaGate@1",
        ),
        HarnessStepSpec(
            step_id="build_paper_card",
            worker_type=HarnessWorkerType.SCRIPT,
            input_keys=("paper_source", "reader_payload", "research_quality"),
            output_key="paper_card",
            quality_gate="ResearchPaperCardGate@1",
        ),
        HarnessStepSpec(
            step_id="publish_artifacts",
            worker_type=HarnessWorkerType.ARTIFACT,
            input_keys=("reader_payload", "paper_card", "research_quality"),
            output_key="artifact_refs",
            side_effect_handler=RESEARCH_ARTIFACT_HANDLER_REF,
            metadata={
                "output_schema": {
                    "required": ["artifact_bundle_ref", "artifact_types"],
                    "properties": {
                        "artifact_bundle_ref": {"type": "string"},
                        "artifact_types": {"type": "array"},
                    },
                },
                "approval_required": False,
            },
        ),
    )
    return HarnessWorkflowSpec(
        workflow_id="research.paper_analysis",
        steps=steps,
        entry_step_id="load_paper_source",
        graph=HarnessGraphSpec(
            graph_id="research.paper_analysis.graph",
            root=Sequence(
                (
                    StepRef("load_paper_source"),
                    StepRef("compile_document"),
                    StepRef("run_research_rag"),
                    StepRef("build_evidence_pack"),
                    ParallelAll(
                        fork_id="analysis_fork",
                        join_id="analysis_join",
                        branches=(
                            ParallelBranch(
                                "structure",
                                StepRef("analyze_structure"),
                                "analysis.structure",
                            ),
                            ParallelBranch(
                                "contribution",
                                StepRef("analyze_contribution"),
                                "analysis.contribution",
                            ),
                            ParallelBranch(
                                "experiments",
                                StepRef("analyze_experiments"),
                                "analysis.experiments",
                            ),
                        ),
                        merge=VerifiedAggregation(
                            StepRef("verify_claims"),
                            "analysis_branch_refs",
                        ),
                    ),
                    StepRef("quality_gate"),
                    StepRef("build_reader_payload"),
                    StepRef("build_paper_card"),
                    StepRef("publish_artifacts"),
                )
            ),
        ),
        terminal_policies={"publish_requires_verify": True},
        terminal_side_effect_policy=HarnessTerminalSideEffectPolicy(
            policy_id=RESEARCH_ARTIFACT_TERMINAL_POLICY_ID,
            version=RESEARCH_ARTIFACT_TERMINAL_POLICY_VERSION,
            handler=RESEARCH_ARTIFACT_HANDLER_REF,
            kind=RESEARCH_ARTIFACT_EFFECT_KIND,
            requires_approval=False,
            # One initial terminal attempt plus one bounded recovery attempt
            # closes the crash window after manifest visibility but before
            # the durable outcome is read back.
            retry_limit=2,
            not_required_evidence_ref=RESEARCH_ARTIFACT_NOT_REQUIRED_EVIDENCE_REF,
            inherited_gate_refs=("ResearchQualityGate@1",),
        ),
        metadata={"scope": "harness_side_effect_authority"},
    )


__all__ = [
    "RESEARCH_ARTIFACT_NOT_REQUIRED_EVIDENCE_REF",
    "RESEARCH_ARTIFACT_TERMINAL_POLICY_ID",
    "RESEARCH_ARTIFACT_TERMINAL_POLICY_VERSION",
    "build_paper_analysis_workflow_spec",
]
