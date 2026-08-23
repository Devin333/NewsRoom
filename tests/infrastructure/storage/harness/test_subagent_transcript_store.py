from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from framework.events.canonical import checksum_for
from framework.harness import (
    HarnessValidationError,
    SubAgentAttemptIdentity,
    SubAgentContextEvidence,
    SubAgentOutputDocument,
    SubAgentTranscript,
    SubAgentTranscriptCorruptError,
)
from framework.harness.graph.versioning import (
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
)
from framework.harness.subagents.transcript import (
    SUBAGENT_BUNDLE_SCHEMA_V3,
    SUBAGENT_RECEIPT_SCHEMA_V3,
)
from infrastructure.storage.harness import FilesystemSubAgentTranscriptStore


FIXED_TIME = datetime(2026, 8, 19, 1, 2, 3, tzinfo=UTC)


def _identity(*, parent_run_id: str = "run-1", attempt: int = 1) -> SubAgentAttemptIdentity:
    return SubAgentAttemptIdentity(
        invocation_id=f"invocation://{parent_run_id}/task-1/{attempt}",
        parent_run_id=parent_run_id,
        child_run_id=f"{parent_run_id}:stage-1:task-instance-{attempt}",
        graph_id="research.paper_analysis.dynamic",
        graph_version="3",
        graph_ref="research.paper_analysis.dynamic@3",
        graph_schema_version=GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
        compiler_version=HARNESS_GRAPH_ONLY_COMPILER_VERSION,
        condition_policy_version=HARNESS_CONDITION_POLICY_VERSION,
        graph_checksum=checksum_for({"graph": "research.paper_analysis.dynamic@3"}),
        stage_id="dynamic_analysis_stage",
        stage_binding_checksum=checksum_for({"stage": "dynamic_analysis_stage"}),
        stage_identity_schema="newsroom.harness-task-plan-stage-identity/v2",
        stage_identity_checksum=checksum_for({"stage_identity": "dynamic_analysis_stage"}),
        plan_id="plan-1",
        plan_version=1,
        plan_checksum=checksum_for({"plan": "plan-1"}),
        task_id="structure",
        task_definition_checksum=checksum_for({"task": "structure"}),
        context_envelope_id="context://run-1/task-1",
        context_envelope_checksum=checksum_for({"context": "run-1/task-1"}),
        node_id="dynamic-analysis-node",
        node_instance_id=f"dynamic-analysis-node-instance-{attempt}",
        activity_id=f"dynamic-analysis-activity-{attempt}",
        activity_attempt=1,
        task_instance_id=f"task-instance-{attempt}",
        attempt=attempt,
        subagent_id="research-structure-analyst",
    )


def _documents(identity: SubAgentAttemptIdentity) -> tuple[SubAgentContextEvidence, SubAgentOutputDocument, SubAgentTranscript]:
    context = SubAgentContextEvidence(
        identity=identity,
        context_envelope_ref=identity.context_envelope_id,
        input_refs=("artifact://input/source",),
        memory_context_refs=(),
        redaction_report={"raw_parent_messages_included": False},
    )
    output = SubAgentOutputDocument(
        identity=identity,
        status="succeeded",
        output={"result": "ok"},
        artifact_refs=("artifact://analysis/structure",),
    )
    gate = {
        "gate_id": "subagent_output_schema",
        "gate_version": "1",
        "input_checksum": checksum_for({"output": "ok"}),
        "passed": True,
        "reason_code": "subagent_output_schema_passed",
    }
    transcript = SubAgentTranscript(
        identity=identity,
        context_envelope_ref=context.context_envelope_ref,
        input_refs=context.input_refs,
        output_ref=output.ref,
        output_checksum=output.output_checksum,
        artifact_refs=output.artifact_refs,
        gate_results=({**gate, "evidence_checksum": checksum_for(gate)},),
        budget_snapshot={"max_turns": 3},
        redaction_report=context.redaction_report,
        events=({"event_type": "subagent_completed"},),
        observed_at=FIXED_TIME,
    )
    return context, output, transcript


def test_filesystem_store_roundtrips_only_v3_bundle(tmp_path: Path) -> None:
    documents = _documents(_identity())
    store = FilesystemSubAgentTranscriptStore(tmp_path, clock=lambda: FIXED_TIME)

    receipt = store.write(*documents)
    payload = json.loads(next(tmp_path.rglob("*.json")).read_text(encoding="utf-8"))

    assert payload["schema_version"] == SUBAGENT_BUNDLE_SCHEMA_V3
    assert receipt.schema_version == SUBAGENT_RECEIPT_SCHEMA_V3
    assert receipt.transcript_ref.startswith("subagent-transcript://v3/")
    assert store.verify(receipt) == receipt
    assert store.read(receipt.transcript_ref) == documents[2]
    assert store.read_context(receipt.context_ref) == documents[0]
    assert store.read_output(receipt.output_ref) == documents[1]


def test_filesystem_store_rejects_tampered_v3_bundle(tmp_path: Path) -> None:
    documents = _documents(_identity())
    store = FilesystemSubAgentTranscriptStore(tmp_path, clock=lambda: FIXED_TIME)
    receipt = store.write(*documents)
    path = next(tmp_path.rglob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["output"]["output"]["result"] = "forged"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SubAgentTranscriptCorruptError):
        store.verify(receipt)


def test_filesystem_store_rejects_pre_cutover_refs(tmp_path: Path) -> None:
    store = FilesystemSubAgentTranscriptStore(tmp_path)

    with pytest.raises(HarnessValidationError):
        store.read("subagent-transcript://v2/run-1/sat_" + "0" * 64)
