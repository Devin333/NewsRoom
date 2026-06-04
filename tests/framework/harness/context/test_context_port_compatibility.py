from __future__ import annotations

from framework.harness import (
    ContextEnvelope,
    FakeContextAssembler,
    FakeContextCompressor,
    FakeContextSnapshotStore,
    FakeLLMWorker,
    FakeRAGSessionController,
    FakeSkillWorker,
    FakeSubAgentWorker,
    HarnessWorkerResult,
    RAGSessionRequest,
)
from framework.harness.context import context_payload


def test_context_envelope_can_feed_llm_skill_subagent_and_rag_fakes() -> None:
    envelope = ContextEnvelope(
        envelope_id="context://run/1",
        stable_prefix={"policy": {"tool_allowlist": ["search"]}},
        dynamic_tail={"task": "summarize"},
        artifact_refs=("artifact://large-result",),
        evidence_refs=("evidence:1",),
        token_estimate=128,
    )
    payload = context_payload(envelope)
    llm = FakeLLMWorker((HarnessWorkerResult(status="succeeded", output={"candidate": "ok"}),))
    skill = FakeSkillWorker(responses=(HarnessWorkerResult(status="succeeded", output={"result": "ok"}),))
    subagent = FakeSubAgentWorker((HarnessWorkerResult(status="succeeded", output={"handoff": "ok"}),))
    rag = FakeRAGSessionController()

    assert llm.generate({"context": payload}).status == "succeeded"
    assert skill.run_skill("skill.fake", {}, payload).diagnostics["skill_version"] == "0.1.0"
    assert subagent.run_subagent("reader", {"context": payload}, {"max_turns": 1}).status == "succeeded"
    assert rag.build_context_pack(RAGSessionRequest(query="q", context_refs=(envelope.envelope_id,))).context_refs == (
        envelope.envelope_id,
    )


def test_context_snapshot_stores_refs_not_large_payload() -> None:
    assembler = FakeContextAssembler(token_limit=100)
    envelope = assembler.assemble(
        {
            "envelope_id": "context://large",
            "dynamic_tail": {"large_payload": "x" * 1000},
            "artifact_refs": ("artifact://large",),
            "token_estimate": 200,
        }
    )
    compressor = FakeContextCompressor()
    snapshot_store = FakeContextSnapshotStore()

    summary = compressor.compress(envelope)
    snapshot = snapshot_store.save(envelope)

    assert envelope.metadata["over_budget"] is True
    assert summary.summary_ref.startswith("artifact://context-summary/")
    assert snapshot.refs == ("artifact://large",)
    assert "large_payload" not in snapshot.to_dict()
    assert snapshot.metadata["payload_saved"] is False
