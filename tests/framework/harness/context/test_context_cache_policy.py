from __future__ import annotations

from framework.harness import (
    ContextCachePolicyBuilder,
    ContextCacheScope,
    ContextEnvelope,
    ContextSegment,
    ContextSegmentType,
)
from tests.framework.harness.context.test_context_models import _graph_identity


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
