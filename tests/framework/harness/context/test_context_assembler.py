from __future__ import annotations

from framework.harness import ContextAssembler, ContextCacheScope, ContextSegmentType


def test_context_assembler_builds_fixed_six_segment_order_and_snapshot() -> None:
    assembler = ContextAssembler()
    envelope = assembler.assemble(
        {
            "run_id": "run-context",
            "workflow_id": "research-runtime",
            "step_id": "collect-evidence",
            "phase": "execute",
            "worker_id": "llm.collector",
            "worker_type": "llm",
            "source_refs": ("source://paper#section=methods",),
            "artifact_refs": ("artifact://pdf-parse",),
            "current_instruction": "Extract candidate evidence with source refs.",
        }
    )

    assert tuple(segment.segment_type for segment in envelope.segments) == (
        ContextSegmentType.GLOBAL_POLICY,
        ContextSegmentType.WORKFLOW,
        ContextSegmentType.WORKER_CONTRACT,
        ContextSegmentType.RUN_STATE,
        ContextSegmentType.EVIDENCE_MEMORY,
        ContextSegmentType.CURRENT_TASK,
    )
    assert [segment.cache_scope for segment in envelope.segments[:3]] == [ContextCacheScope.STABLE_PREFIX] * 3
    assert [segment.cache_scope for segment in envelope.segments[3:]] == [ContextCacheScope.DYNAMIC_TAIL] * 3
    assert envelope.snapshot_ref == "context-snapshot://1"
    assert any(event["event_type"] == "context_snapshot_written" for event in assembler.events)
