from __future__ import annotations

from dataclasses import replace

from framework.harness import (
    ContextAssembler,
    ContextCachePolicyBuilder,
    ContextCacheScope,
    ContextEnvelope,
    ContextSegment,
    ContextSegmentType,
)
from tests.framework.harness.context.test_context_models import _graph_identity


def test_cache_key_depends_on_stable_prefix_not_dynamic_paper_content() -> None:
    assembler = ContextAssembler()
    first = assembler.assemble(
        {
            "workflow_id": "wf",
            "worker_id": "worker",
            "source_refs": ("source://paper-a#section=intro",),
            "current_instruction": "Analyze paper A.",
        }
    )
    second = replace(
        first,
        segments=(
            *first.segments[:4],
            replace(first.segments[4], content_ref="evidence-memory://paper-b", provenance_refs=("source://paper-b#section=method",)),
            replace(first.segments[5], summary="Analyze paper B."),
        ),
    )
    second_policy = ContextCachePolicyBuilder().build(second)

    assert first.cache_policy is not None
    assert first.cache_policy.cache_key == (
        "context-cache:2331cc55737f42dd6dca81ddaf6aa0bd0baa02792cdbf62d2e3f9992a74b1afd"
    )
    assert first.cache_policy.cache_key == second_policy.cache_key


def test_graph_cache_key_binds_graph_stage_not_dynamic_tail_or_task_attempt() -> None:
    stable_segment = ContextSegment(
        segment_id="policy",
        segment_type=ContextSegmentType.GLOBAL_POLICY,
        content_ref="policy://graph-context",
        summary="Harness controls dispatch.",
        token_estimate=8,
        cache_scope=ContextCacheScope.STABLE_PREFIX,
    )
    first = ContextEnvelope.for_graph(
        envelope_id="context://graph-cache/one",
        graph_identity=_graph_identity(),
        phase="EXECUTE",
        worker_id="task-plan-worker",
        worker_type="task_plan",
        segments=(stable_segment,),
        dynamic_tail={"input": "paper-a"},
    )
    second = ContextEnvelope.for_graph(
        envelope_id="context://graph-cache/two",
        graph_identity=_graph_identity(),
        phase="EXECUTE",
        worker_id="task-plan-worker",
        worker_type="task_plan",
        segments=(stable_segment,),
        dynamic_tail={"input": "paper-b"},
    )
    other_graph = ContextEnvelope.for_graph(
        envelope_id="context://graph-cache/other",
        graph_identity=_graph_identity(graph_id="other.research.graph"),
        phase="EXECUTE",
        worker_id="task-plan-worker",
        worker_type="task_plan",
        segments=(stable_segment,),
        dynamic_tail={"input": "paper-a"},
    )
    builder = ContextCachePolicyBuilder()

    first_policy = builder.build(first)
    second_policy = builder.build(second)
    other_policy = builder.build(other_graph)

    assert first_policy.cache_key == second_policy.cache_key
    assert first_policy.cache_key != other_policy.cache_key
    assert first.bind_cache_policy(first_policy).checksum != first.checksum
