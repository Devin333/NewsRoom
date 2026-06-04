from __future__ import annotations

from dataclasses import replace

from framework.harness import ContextAssembler, ContextCachePolicyBuilder


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
    assert first.cache_policy.cache_key == second_policy.cache_key
