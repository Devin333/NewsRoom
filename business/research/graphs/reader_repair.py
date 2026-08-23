from __future__ import annotations

from types import MappingProxyType

from framework.events.canonical import checksum_for
from framework.harness.context.models import (
    CONTEXT_GRAPH_TASK_PLAN_STAGE_IDENTITY_SCHEMA_V2,
    ContextGraphIdentity,
)
from framework.harness.control_plane.terminal_failure import (
    HARNESS_GRAPH_TERMINAL_FAILURE_RECORD_SCHEMA,
)
from framework.harness.graph import (
    HarnessContractKind,
    HarnessContractReference,
    HarnessGraphCommittedNodeOutputBinding,
    HarnessGraphDefinition,
    HarnessGraphCompiler,
    HarnessGraphLeafBinding,
    HarnessGraphRepairBinding,
    HarnessGraphRepairTrigger,
    HarnessGraphSpec,
    HarnessLeafActivityKind,
    HarnessRetryPolicy,
    HarnessStepSpec,
    HarnessTerminalFailureSideEffectPolicy,
    HarnessTerminalSideEffectPolicy,
    HarnessWorkerType,
    Sequence,
    StepRef,
)
from framework.harness.subagents import SubAgentSpec

from business.research.domain.reader_repair import READER_REPAIR_NAMESPACE
from business.research.graphs.reader_repair_contracts import (
    READER_REPAIR_APPLICATION_OUTPUT_KEY,
    READER_REPAIR_APPLICATION_STEP_ID,
    READER_REPAIR_APPLICATION_VERIFICATION_OUTPUT_KEY,
    READER_REPAIR_APPLICATION_VERIFICATION_STEP_ID,
    READER_REPAIR_COMMITTED_OUTPUT_BINDING_ID,
    READER_REPAIR_COMMITTED_OUTPUT_RECEIPT_KEY,
    READER_REPAIR_GRAPH_ID,
    READER_REPAIR_GRAPH_VERSION,
    READER_REPAIR_RESULT_OUTPUT_KEY,
    READER_REPAIR_RESULT_STEP_ID,
)
from business.research.ports.repair_memory import (
    READER_REPAIR_MEMORY_EFFECT_KIND,
    READER_REPAIR_MEMORY_HANDLER_REF,
)
from business.research.ports.reader_repair_failure_diagnostic import (
    READER_REPAIR_FAILURE_DIAGNOSTIC_EFFECT_KIND,
    READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_REF,
)

READER_REPAIR_MEMORY_POLICY_ID = "research.reader_repair.memory"
READER_REPAIR_MEMORY_POLICY_VERSION = "1"
READER_REPAIR_MEMORY_NOT_REQUIRED_EVIDENCE_REF = checksum_for(
    {
        "policy": "not_required",
        "handler": READER_REPAIR_MEMORY_HANDLER_REF,
        "policy_id": READER_REPAIR_MEMORY_POLICY_ID,
        "version": READER_REPAIR_MEMORY_POLICY_VERSION,
    }
)
READER_REPAIR_FAILURE_DIAGNOSTIC_POLICY_ID = (
    "research.reader_repair.memory.failure_diagnostic"
)
READER_REPAIR_FAILURE_DIAGNOSTIC_POLICY_VERSION = "1"
READER_REPAIR_FAILURE_DIAGNOSTIC_NOT_REQUIRED_EVIDENCE_REF = checksum_for(
    {
        "policy": "not_required",
        "handler": READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_REF,
        "policy_id": READER_REPAIR_FAILURE_DIAGNOSTIC_POLICY_ID,
        "version": READER_REPAIR_FAILURE_DIAGNOSTIC_POLICY_VERSION,
        "disposition": "quarantine",
    }
)
READER_REPAIR_SUBAGENT_IDS = MappingProxyType(
    {
        "propose_repair_candidate": "reader_repair_proposer",
        "collect_repair_application_observation": "reader_repair_verifier",
    }
)
READER_REPAIR_SUBAGENT_WORKER_REFS = MappingProxyType(
    {
        activity_id: f"research.reader_repair.{subagent_id}@1"
        for activity_id, subagent_id in READER_REPAIR_SUBAGENT_IDS.items()
    }
)

_GRAPH_INPUT_KEYS = ("reader_payload", "run_id", "source_format")
_GRAPH_TERMINAL_OUTPUT_KEYS = (
    "reader_repair_result",
    "reader_repair_case",
    "strategy_candidate_bundle",
    "memory_write_candidate",
)


def build_reader_repair_graph_definition() -> HarnessGraphDefinition:
    activities = _activities()
    root = HarnessGraphSpec(
        graph_id=READER_REPAIR_GRAPH_ID,
        root=Sequence(tuple(StepRef(activity.step_id) for activity in activities)),
        input_keys=_GRAPH_INPUT_KEYS,
        terminal_output_keys=_GRAPH_TERMINAL_OUTPUT_KEYS,
        metadata={
            "domain": "research",
            "operation": "reader_repair",
            "memory_namespace": READER_REPAIR_NAMESPACE,
        },
    )
    return HarnessGraphDefinition(
        graph_id=READER_REPAIR_GRAPH_ID,
        graph_version=READER_REPAIR_GRAPH_VERSION,
        root=root,
        activities=activities,
        leaf_activity_bindings=tuple(_leaf_binding(activity) for activity in activities),
        task_plan_stage_bindings=(),
        committed_output_bindings=(
            HarnessGraphCommittedNodeOutputBinding(
                binding_id=READER_REPAIR_COMMITTED_OUTPUT_BINDING_ID,
                producer_activity_id=READER_REPAIR_APPLICATION_STEP_ID,
                producer_node_id=READER_REPAIR_APPLICATION_STEP_ID,
                producer_output_key=READER_REPAIR_APPLICATION_OUTPUT_KEY,
                consumer_activity_id=READER_REPAIR_RESULT_STEP_ID,
                consumer_node_id=READER_REPAIR_RESULT_STEP_ID,
                receipt_input_key=READER_REPAIR_COMMITTED_OUTPUT_RECEIPT_KEY,
            ),
        ),
        repair_bindings=_repair_bindings(),
        terminal_side_effect_policy=build_reader_repair_memory_terminal_policy(),
        terminal_failure_side_effect_policy=(
            build_reader_repair_failure_diagnostic_terminal_policy()
        ),
    )


def build_reader_repair_context_graph_identity(
    *,
    run_id: str,
    stage_id: str,
) -> ContextGraphIdentity:
    """Build the exact Graph/stage identity used by Reader Repair contexts."""

    definition = build_reader_repair_graph_definition()
    activities = {activity.step_id: activity for activity in definition.activities}
    if stage_id not in activities:
        raise ValueError(f"Unknown Reader Repair Graph stage: {stage_id}")
    graph = HarnessGraphCompiler().compile(definition).graph
    stage_binding_checksum = checksum_for(
        {
            "definition_checksum": definition.definition_checksum,
            "graph_checksum": graph.checksum,
            "stage_id": stage_id,
            "activity": activities[stage_id].to_dict(),
        }
    )
    identity_projection = {
        "schema_version": CONTEXT_GRAPH_TASK_PLAN_STAGE_IDENTITY_SCHEMA_V2,
        "run_id": run_id,
        "graph_schema_version": graph.schema_version,
        "compiler_version": graph.compiler_version,
        "condition_policy_version": graph.condition_policy_version,
        "graph_id": graph.graph_id,
        "graph_version": graph.graph_version,
        "graph_checksum": graph.checksum,
        "stage_id": stage_id,
        "stage_binding_checksum": stage_binding_checksum,
        "graph_ref": graph.graph_ref.exact_ref,
    }
    return ContextGraphIdentity(
        run_id=run_id,
        graph_id=graph.graph_id,
        graph_version=graph.graph_version,
        graph_ref=graph.graph_ref.exact_ref,
        graph_schema_version=graph.schema_version,
        compiler_version=graph.compiler_version,
        condition_policy_version=graph.condition_policy_version,
        graph_checksum=graph.checksum,
        stage_id=stage_id,
        stage_binding_checksum=stage_binding_checksum,
        stage_identity_schema=CONTEXT_GRAPH_TASK_PLAN_STAGE_IDENTITY_SCHEMA_V2,
        stage_identity_checksum=checksum_for(identity_projection),
    )


def build_reader_repair_subagent_specs() -> tuple[SubAgentSpec, SubAgentSpec]:
    proposer = SubAgentSpec(
        subagent_id=READER_REPAIR_SUBAGENT_IDS["propose_repair_candidate"],
        role="repair_proposer",
        purpose=(
            "Generate localized reader repair candidates from approved repair "
            "context packs without routing or side-effect authority."
        ),
        input_schema={
            "required": ["reader_payload", "reader_repair_context_pack"],
            "additionalProperties": False,
        },
        output_schema={
            "required": [
                "candidate_id",
                "repair_summary",
                "target_region_refs",
                "patch_operations",
                "expected_effect",
                "risks",
                "confidence",
                "metadata",
            ],
            "additionalProperties": False,
        },
        allowed_tools=("retrieval.read_source",),
        allowed_memory_namespaces=(READER_REPAIR_NAMESPACE,),
        context_policy={
            "allow_sibling_history": False,
            "allow_private_notes_export": False,
        },
        budget={"max_turns": 4, "max_tool_calls": 2, "max_memory_ops": 0},
        metadata={"candidate_only": True},
    )
    verifier = SubAgentSpec(
        subagent_id=READER_REPAIR_SUBAGENT_IDS[
            "collect_repair_application_observation"
        ],
        role="repair_verifier",
        purpose=(
            "Collect source-backed repair observations for deterministic Harness "
            "gates; never issue a pass/fail or promotion verdict."
        ),
        input_schema={
            "required": [
                "reader_issue",
                "reader_repair_patch_candidate",
                "reader_repair_application_candidate",
            ],
            "additionalProperties": False,
        },
        output_schema={
            "required": [
                "candidate_id",
                "application_id",
                "observations",
                "source_refs",
                "input_bindings",
                "metadata",
            ],
            "additionalProperties": False,
        },
        allowed_tools=("retrieval.read_source",),
        allowed_memory_namespaces=(READER_REPAIR_NAMESPACE,),
        context_policy={
            "allow_sibling_history": False,
            "allow_proposer_private_notes": False,
        },
        budget={"max_turns": 4, "max_tool_calls": 2, "max_memory_ops": 0},
        metadata={"candidate_only": True},
    )
    return proposer, verifier


def build_reader_repair_memory_terminal_policy() -> HarnessTerminalSideEffectPolicy:
    return HarnessTerminalSideEffectPolicy(
        policy_id=READER_REPAIR_MEMORY_POLICY_ID,
        version=READER_REPAIR_MEMORY_POLICY_VERSION,
        handler=READER_REPAIR_MEMORY_HANDLER_REF,
        kind=READER_REPAIR_MEMORY_EFFECT_KIND,
        requires_approval=False,
        retry_limit=2,
        not_required_evidence_ref=READER_REPAIR_MEMORY_NOT_REQUIRED_EVIDENCE_REF,
        inherited_gate_refs=("ReaderRepairMemoryPolicyGate@1",),
    )


def build_reader_repair_failure_diagnostic_terminal_policy(
) -> HarnessTerminalFailureSideEffectPolicy:
    return HarnessTerminalFailureSideEffectPolicy(
        policy_id=READER_REPAIR_FAILURE_DIAGNOSTIC_POLICY_ID,
        version=READER_REPAIR_FAILURE_DIAGNOSTIC_POLICY_VERSION,
        handler=READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_REF,
        kind=READER_REPAIR_FAILURE_DIAGNOSTIC_EFFECT_KIND,
        failure_record_schema=HARNESS_GRAPH_TERMINAL_FAILURE_RECORD_SCHEMA,
        terminal_reason_codes=(
            "graph_terminal_failure",
            "verification_failed_replans_exhausted",
        ),
        requires_approval=False,
        retry_limit=2,
        not_required_evidence_ref=(
            READER_REPAIR_FAILURE_DIAGNOSTIC_NOT_REQUIRED_EVIDENCE_REF
        ),
    )


def _activities() -> tuple[HarnessStepSpec, ...]:
    return (
        HarnessStepSpec(
            step_id="detect_reader_issue",
            worker_type=HarnessWorkerType.FUNCTION,
            input_keys=("reader_payload", "run_id", "source_format"),
            output_key="reader_issue",
            quality_gate="ReaderRepairIssueGate@1",
        ),
        HarnessStepSpec(
            step_id="assemble_repair_context",
            worker_type=HarnessWorkerType.FUNCTION,
            input_keys=("reader_issue",),
            output_key="reader_repair_context_pack",
            quality_gate="ReaderRepairContextGate@1",
        ),
        HarnessStepSpec(
            step_id="propose_repair_candidate",
            worker_type=HarnessWorkerType.SUBAGENT,
            input_keys=("reader_payload", "reader_repair_context_pack"),
            output_key="reader_repair_patch_candidate",
            retry_policy=HarnessRetryPolicy(max_retries=1, max_attempts=2),
            quality_gate="ReaderRepairPatchCandidateGate@1",
            metadata={"candidate_only": True},
        ),
        HarnessStepSpec(
            step_id=READER_REPAIR_APPLICATION_STEP_ID,
            worker_type=HarnessWorkerType.FUNCTION,
            input_keys=("reader_payload", "reader_repair_patch_candidate"),
            output_key=READER_REPAIR_APPLICATION_OUTPUT_KEY,
            retry_policy=HarnessRetryPolicy(max_retries=0, max_attempts=1),
            quality_gate="ReaderRepairApplicationCandidateGate@1",
        ),
        HarnessStepSpec(
            step_id="collect_repair_application_observation",
            worker_type=HarnessWorkerType.SUBAGENT,
            input_keys=(
                "reader_issue",
                "reader_repair_patch_candidate",
                READER_REPAIR_APPLICATION_OUTPUT_KEY,
            ),
            output_key="reader_repair_application_observation",
            retry_policy=HarnessRetryPolicy(max_retries=1, max_attempts=2),
            quality_gate="ReaderRepairApplicationObservationGate@1",
            metadata={"candidate_only": True, "deterministic_verdict": False},
        ),
        HarnessStepSpec(
            step_id=READER_REPAIR_APPLICATION_VERIFICATION_STEP_ID,
            worker_type=HarnessWorkerType.FUNCTION,
            input_keys=(
                "reader_payload",
                "reader_issue",
                "reader_repair_patch_candidate",
                READER_REPAIR_APPLICATION_OUTPUT_KEY,
                "reader_repair_application_observation",
            ),
            output_key=READER_REPAIR_APPLICATION_VERIFICATION_OUTPUT_KEY,
            retry_policy=HarnessRetryPolicy(max_retries=0, max_attempts=1),
            quality_gate="ReaderRepairApplicationVerificationGate@1",
        ),
        HarnessStepSpec(
            step_id=READER_REPAIR_RESULT_STEP_ID,
            worker_type=HarnessWorkerType.FUNCTION,
            input_keys=(
                "reader_payload",
                "reader_issue",
                "reader_repair_patch_candidate",
                READER_REPAIR_APPLICATION_OUTPUT_KEY,
                "reader_repair_application_observation",
                READER_REPAIR_APPLICATION_VERIFICATION_OUTPUT_KEY,
            ),
            output_key=READER_REPAIR_RESULT_OUTPUT_KEY,
            quality_gate="ReaderRepairCommittedResultGate@1",
        ),
        HarnessStepSpec(
            step_id="build_repair_case",
            worker_type=HarnessWorkerType.FUNCTION,
            input_keys=("reader_repair_context_pack", "reader_repair_result"),
            output_key="reader_repair_case",
            quality_gate="ReaderRepairCaseGate@1",
        ),
        HarnessStepSpec(
            step_id="prepare_skill_candidate_bundle",
            worker_type=HarnessWorkerType.FUNCTION,
            input_keys=("reader_repair_context_pack", "reader_repair_case"),
            output_key="strategy_candidate_bundle",
            quality_gate="ReaderRepairStrategyBoundaryGate@1",
            metadata={
                "candidate_only": True,
                "requires_harness_skill_evolution": True,
            },
        ),
        HarnessStepSpec(
            step_id="prepare_memory_write",
            worker_type=HarnessWorkerType.FUNCTION,
            input_keys=("reader_repair_case", "strategy_candidate_bundle"),
            output_key="memory_write_candidate",
            quality_gate="ReaderRepairMemoryPolicyGate@1",
            side_effect_handler=READER_REPAIR_MEMORY_HANDLER_REF,
            metadata={
                "candidate_only": True,
                "output_schema": {
                    "required": ["memory_write_candidate"],
                    "properties": {
                        "memory_write_candidate": {"type": "object"},
                    },
                },
            },
        ),
    )


def _repair_bindings() -> tuple[HarnessGraphRepairBinding, ...]:
    triggers = (
        HarnessGraphRepairTrigger.WORKER_FAILURE_AFTER_RETRY_EXHAUSTION,
        HarnessGraphRepairTrigger.VERIFICATION_FAILURE,
    )
    source_node_ids = (
        "propose_repair_candidate",
        READER_REPAIR_APPLICATION_STEP_ID,
        "collect_repair_application_observation",
        READER_REPAIR_APPLICATION_VERIFICATION_STEP_ID,
    )
    return tuple(
        HarnessGraphRepairBinding(
            binding_id=f"reader-repair-{source_node_id}-replan",
            source_node_id=source_node_id,
            repair_node_id=f"reader-repair-replan:{source_node_id}",
            repair_activity_id="propose_repair_candidate",
            triggers=triggers,
        )
        for source_node_id in source_node_ids
    )


def _leaf_binding(activity: HarnessStepSpec) -> HarnessGraphLeafBinding:
    worker_ref = READER_REPAIR_SUBAGENT_WORKER_REFS.get(
        activity.step_id,
        f"research.reader_repair.{activity.step_id}@1",
    )
    worker_id, worker_version = worker_ref.split("@", maxsplit=1)
    return HarnessGraphLeafBinding(
        activity_id=activity.step_id,
        leaf_activity_kind=HarnessLeafActivityKind(activity.worker_type.value),
        worker_ref=HarnessContractReference(
            HarnessContractKind.WORKER,
            worker_id,
            worker_version,
        ),
        activity_ref=HarnessContractReference(
            HarnessContractKind.ACTIVITY,
            f"research.reader_repair.{activity.step_id}",
            "1",
        ),
    )


__all__ = [
    "READER_REPAIR_APPLICATION_OUTPUT_KEY",
    "READER_REPAIR_APPLICATION_STEP_ID",
    "READER_REPAIR_APPLICATION_VERIFICATION_OUTPUT_KEY",
    "READER_REPAIR_APPLICATION_VERIFICATION_STEP_ID",
    "READER_REPAIR_COMMITTED_OUTPUT_BINDING_ID",
    "READER_REPAIR_COMMITTED_OUTPUT_RECEIPT_KEY",
    "READER_REPAIR_FAILURE_DIAGNOSTIC_EFFECT_KIND",
    "READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_REF",
    "READER_REPAIR_GRAPH_ID",
    "READER_REPAIR_GRAPH_VERSION",
    "READER_REPAIR_MEMORY_EFFECT_KIND",
    "READER_REPAIR_MEMORY_HANDLER_REF",
    "READER_REPAIR_MEMORY_NOT_REQUIRED_EVIDENCE_REF",
    "READER_REPAIR_MEMORY_POLICY_ID",
    "READER_REPAIR_MEMORY_POLICY_VERSION",
    "READER_REPAIR_FAILURE_DIAGNOSTIC_NOT_REQUIRED_EVIDENCE_REF",
    "READER_REPAIR_FAILURE_DIAGNOSTIC_POLICY_ID",
    "READER_REPAIR_FAILURE_DIAGNOSTIC_POLICY_VERSION",
    "READER_REPAIR_SUBAGENT_IDS",
    "READER_REPAIR_SUBAGENT_WORKER_REFS",
    "build_reader_repair_graph_definition",
    "build_reader_repair_context_graph_identity",
    "build_reader_repair_failure_diagnostic_terminal_policy",
    "build_reader_repair_memory_terminal_policy",
    "build_reader_repair_subagent_specs",
]
