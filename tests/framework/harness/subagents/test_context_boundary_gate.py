from __future__ import annotations

from framework.harness import ContextEnvelope, FakeSubAgentRuntime, SubAgentContextBoundaryGate, fake_subagent_spec


class UnsafeEnvelope:
    def to_dict(self):
        return {"context_pack": {"dynamic_tail": {"sibling_private_notes": ["do not share"]}}}


def test_context_boundary_gate_rejects_sibling_private_notes() -> None:
    result = SubAgentContextBoundaryGate().evaluate(UnsafeEnvelope())  # type: ignore[arg-type]

    assert result.passed is False
    assert result.details["forbidden"] == ["sibling_private_notes"]


def test_fake_runtime_child_does_not_receive_parent_raw_messages() -> None:
    runtime = FakeSubAgentRuntime(fake_subagent_spec())
    invocation = runtime.build_invocation(context=ContextEnvelope(envelope_id="context://safe"))
    result = runtime.invoke(invocation)

    assert result.status == "succeeded"
    context_payload = invocation.context_envelope.to_dict()["context_pack"]
    assert "parent_raw_messages" not in context_payload
