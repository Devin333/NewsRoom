from __future__ import annotations

from framework.harness import ContextAssembler, ContextCacheScope, ContextSegmentType
from tests.framework.harness.context.test_context_models import _graph_identity


def test_context_assembler_builds_fixed_six_segment_order_and_snapshot() -> None:
    assembler = ContextAssembler()
    envelope = assembler.assemble(
        {
            "graph_identity": _graph_identity(),
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
        ContextSegmentType.GRAPH,
        ContextSegmentType.WORKER_CONTRACT,
        ContextSegmentType.RUN_STATE,
        ContextSegmentType.EVIDENCE_MEMORY,
        ContextSegmentType.CURRENT_TASK,
    )
    assert [segment.cache_scope for segment in envelope.segments[:3]] == [ContextCacheScope.STABLE_PREFIX] * 3
    assert [segment.cache_scope for segment in envelope.segments[3:]] == [ContextCacheScope.DYNAMIC_TAIL] * 3
    assert envelope.snapshot_ref == "context-snapshot://1"
    assert envelope.is_graph_only is True
    assert envelope.graph_identity == _graph_identity()
    assert "workflow_id" not in envelope.to_dict()
    assert any(event["event_type"] == "context_snapshot_written" for event in assembler.events)
