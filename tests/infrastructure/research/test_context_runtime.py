from __future__ import annotations

import json

from framework.events.canonical import checksum_for
from framework.harness import (
    ContextBudget,
    ContextGraphIdentity,
    FakeArtifactPort,
    HarnessEventType,
    InMemoryHarnessEventPort,
)
from framework.harness.context.models import (
    CONTEXT_GRAPH_TASK_PLAN_STAGE_IDENTITY_SCHEMA_V2,
)
from framework.harness.graph.versioning import (
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
)
from infrastructure.research.context_runtime import build_research_context_assembler


def test_research_context_assembler_commits_exact_no_compaction_evidence() -> None:
    artifacts = FakeArtifactPort()
    events = InMemoryHarnessEventPort()
    assembler = build_research_context_assembler(
        artifact_port=artifacts,
        event_port=events,
        provider="test-provider",
        model="test-model",
        max_input_tokens=16_384,
        max_output_tokens=1_024,
    )

    envelope = assembler.assemble(
        {
            "run_id": "research-context-production",
            "graph_identity": _graph_identity(),
            "phase": "EXECUTE",
            "worker_id": "research-artifact-publisher",
            "worker_type": "function",
            "current_task_ref": "task://publish_artifacts",
            "current_instruction": "Publish verified Research artifacts.",
            "source_refs": ("source://paper",),
            "artifact_refs": tuple(
                f"artifact://research/{index}" for index in range(32)
            ),
            "evidence_refs": tuple(
                f"evidence://research/{index}" for index in range(16)
            ),
            "budget": ContextBudget(
                max_input_tokens=8_192,
                max_output_tokens=1_024,
                max_context_segments=6,
                max_evidence_items=8,
                max_memory_items=6,
                max_artifact_refs=24,
                reserved_output_tokens=512,
            ),
        }
    )

    assert envelope.metadata["context_verification_classification"] == (
        "versioned_no_compaction_evidence"
    )
    assert envelope.metadata["context_dispatch_authorized"] is False
    assert envelope.metadata["context_prepared_fingerprint"].startswith("sha256:")
    assert envelope.metadata["context_durable_refs"]["initial_admission"]
    assert envelope.metadata["context_durable_refs"]["compression_record"] is None
    assert events.events[-1].event_type is HarnessEventType.CONTEXT_COMPACTION_PLANNED
    assert events.events[-1].payload["status"] == "no_compaction_required"
    admission_ref = envelope.metadata["context_durable_refs"]["initial_admission"]
    admission = artifacts.read_artifact(admission_ref["ref"])["payload"]
    assert admission["fixed_input_tokens"] + sum(
        admission["group_input_tokens"].values()
    ) == admission["input_tokens"]
    durable_projection = json.dumps(
        {
            "artifacts": artifacts.storage,
            "events": [event.to_dict() for event in events.events],
        },
        sort_keys=True,
    )
    assert "Publish verified Research artifacts." not in durable_projection


def _graph_identity() -> ContextGraphIdentity:
    projection = {
        "schema_version": CONTEXT_GRAPH_TASK_PLAN_STAGE_IDENTITY_SCHEMA_V2,
        "run_id": "research-context-production",
        "graph_schema_version": GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
        "compiler_version": HARNESS_GRAPH_ONLY_COMPILER_VERSION,
        "condition_policy_version": HARNESS_CONDITION_POLICY_VERSION,
        "graph_id": "research.paper_analysis",
        "graph_version": "1",
        "graph_checksum": "sha256:" + "1" * 64,
        "stage_id": "publish_artifacts",
        "stage_binding_checksum": "sha256:" + "2" * 64,
        "graph_ref": "research.paper_analysis@1",
    }
    return ContextGraphIdentity(
        run_id=projection["run_id"],
        graph_id=projection["graph_id"],
        graph_version=projection["graph_version"],
        graph_ref=projection["graph_ref"],
        graph_schema_version=projection["graph_schema_version"],
        compiler_version=projection["compiler_version"],
        condition_policy_version=projection["condition_policy_version"],
        graph_checksum=projection["graph_checksum"],
        stage_id=projection["stage_id"],
        stage_binding_checksum=projection["stage_binding_checksum"],
        stage_identity_schema=projection["schema_version"],
        stage_identity_checksum=checksum_for(projection),
    )
