from __future__ import annotations

from framework.harness import FakeSubAgentRuntime, SubAgentTranscriptGate, fake_subagent_spec


def test_each_invocation_has_independent_transcript() -> None:
    runtime = FakeSubAgentRuntime(fake_subagent_spec())
    first = runtime.invoke(runtime.build_invocation(parent_run_id="parent", input_refs=("input://1",)))
    second = runtime.invoke(runtime.build_invocation(parent_run_id="parent", input_refs=("input://2",)))

    assert first.transcript_ref != second.transcript_ref
    assert runtime.transcript_store.refs_for_parent("parent") == (first.transcript_ref, second.transcript_ref)


def test_parent_trace_can_reference_child_transcript() -> None:
    runtime = FakeSubAgentRuntime(fake_subagent_spec())
    result = runtime.invoke(runtime.build_invocation(parent_run_id="parent"))
    transcript = runtime.transcript_store.read(result.transcript_ref or "")

    assert transcript.parent_run_id == "parent"
    assert transcript.child_run_id != transcript.parent_run_id
    assert transcript.to_dict()["ref"] == result.transcript_ref
    assert SubAgentTranscriptGate().evaluate(result).passed is True
