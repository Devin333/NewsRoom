from __future__ import annotations

from framework.harness import (
    ContextAssembler,
    ContextEnvelope,
    ContextProvenanceGate,
    FakeContextRuntime,
    RAGContextPack,
    SubAgentContextEnvelope,
    fake_subagent_spec,
)
from framework.harness.retrieval import EvidencePack


def test_fake_context_runtime_assembles_snapshots_and_replays_without_llm() -> None:
    runtime = FakeContextRuntime()
    envelope = runtime.assemble({"run_id": "run-fake", "step_id": "current"})
    replayed = runtime.replay(envelope.snapshot_ref or "")

    assert replayed.to_dict() == envelope.to_dict()
    assert any(event["event_type"] == "context_snapshot_written" for event in runtime.assembler.events)


def test_rag_context_pack_must_enter_prompt_through_context_segment_with_provenance() -> None:
    pack = RAGContextPack(
        pack_id="rag://pack",
        query="reader issue",
        evidence=(
            EvidencePack(
                evidence_id="evidence:reader",
                title="Reader source",
                summary="Evidence with source refs.",
                source_refs=("source://paper#section=discussion",),
                confidence=0.9,
                freshness="fixture",
                lineage=("retrieval.fake",),
            ),
        ),
    )
    envelope = ContextAssembler().assemble(
        {
            "source_refs": pack.evidence[0].source_refs,
            "evidence_refs": tuple(item.evidence_id for item in pack.evidence),
            "evidence_memory_ref": pack.pack_id,
        }
    )

    assert ContextProvenanceGate().evaluate(envelope).passed is True


def test_subagent_context_projection_excludes_parent_raw_messages_and_sibling_notes() -> None:
    spec = fake_subagent_spec()
    envelope = ContextEnvelope(envelope_id="context://safe-subagent", stable_prefix={"policy": "ok"})
    subagent_context = SubAgentContextEnvelope(
        child_run_id="child",
        parent_run_id="parent",
        subagent_id=spec.subagent_id,
        role=spec.role,
        allowed_input_refs=("input://1",),
        context_pack=envelope,
        memory_context_refs=("memory://research.public",),
        tool_policy_ref="tool-policy://child",
        budget_snapshot={},
    )

    payload = subagent_context.to_dict()["context_pack"]
    assert "parent_raw_messages" not in payload
    assert "sibling_private_notes" not in payload
