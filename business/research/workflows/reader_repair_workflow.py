from __future__ import annotations

from framework.harness.workflow import HarnessRoutingRule, HarnessStepSpec, HarnessWorkerType, HarnessWorkflowSpec


def build_reader_repair_workflow_spec() -> HarnessWorkflowSpec:
    steps = (
        HarnessStepSpec(
            step_id="detect_reader_issue",
            worker_type=HarnessWorkerType.SCRIPT,
            output_key="reader_issue",
            quality_gate="ReaderIssueSchemaGate",
        ),
        HarnessStepSpec(
            step_id="build_repair_memory_query",
            worker_type=HarnessWorkerType.SCRIPT,
            input_keys=("reader_issue",),
            output_key="repair_memory_query",
            quality_gate="RepairMemoryNamespaceGate",
        ),
        HarnessStepSpec(
            step_id="recall_repair_memory",
            worker_type=HarnessWorkerType.MEMORY,
            input_keys=("repair_memory_query",),
            output_key="repair_memory_hits",
            quality_gate="RepairMemoryPolicyGate",
        ),
        HarnessStepSpec(
            step_id="run_repair_rag",
            worker_type=HarnessWorkerType.RETRIEVAL,
            input_keys=("reader_issue", "repair_memory_hits"),
            output_key="repair_rag_context",
            quality_gate="ResearchRAGMemoryNamespaceGate",
        ),
        HarnessStepSpec(
            step_id="build_repair_context_pack",
            worker_type=HarnessWorkerType.SCRIPT,
            input_keys=("reader_issue", "repair_memory_hits", "repair_rag_context"),
            output_key="reader_repair_context_pack",
            quality_gate="ReaderRepairSourceLineageGate",
        ),
        HarnessStepSpec(
            step_id="propose_repair_candidate",
            worker_type=HarnessWorkerType.SUBAGENT,
            input_keys=("reader_repair_context_pack",),
            output_key="repair_candidate",
            quality_gate="ReaderRepairCandidateSchemaGate",
        ),
        HarnessStepSpec(
            step_id="verify_repair_candidate",
            worker_type=HarnessWorkerType.QUALITY_GATE,
            input_keys=("repair_candidate",),
            output_key="repair_candidate_verdict",
            quality_gate="ReaderRepairPayloadFidelityGate",
        ),
        HarnessStepSpec(
            step_id="apply_repair",
            worker_type=HarnessWorkerType.SCRIPT,
            input_keys=("repair_candidate_verdict",),
            output_key="repaired_payload",
            quality_gate="ReaderPayloadSchemaGate",
        ),
        HarnessStepSpec(
            step_id="verify_reader_payload",
            worker_type=HarnessWorkerType.QUALITY_GATE,
            input_keys=("repaired_payload",),
            output_key="reader_payload_verdict",
            quality_gate="ReaderRepairPayloadFidelityGate",
        ),
        HarnessStepSpec(
            step_id="commit_repair_episode_memory",
            worker_type=HarnessWorkerType.MEMORY,
            input_keys=("reader_payload_verdict",),
            output_key="repair_memory_write_intent",
            quality_gate="ReaderRepairMemoryPolicyGate",
        ),
    )
    return HarnessWorkflowSpec(
        workflow_id="research.reader_repair",
        steps=steps,
        entry_step_id="detect_reader_issue",
        routing_rules=tuple(HarnessRoutingRule(from_step=left.step_id, to_step=right.step_id) for left, right in zip(steps, steps[1:])),
        metadata={
            "scope": "stage_5_modeling_only",
            "publishes_skill": False,
            "writes_memory_directly": False,
            "memory_write_owner": "framework.harness",
        },
    )


__all__ = ["build_reader_repair_workflow_spec"]
