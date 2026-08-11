from __future__ import annotations

import json

from framework.harness import (
    ContextBudget,
    FakeArtifactPort,
    HarnessEventType,
    InMemoryHarnessEventPort,
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
            "workflow_id": "research.paper_analysis",
            "step_id": "publish_artifacts",
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
