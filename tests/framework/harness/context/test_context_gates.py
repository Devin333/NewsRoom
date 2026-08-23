from __future__ import annotations

from dataclasses import replace

from framework.harness import (
    ContextAssembler,
    ContextCacheKeyGate,
    ContextPrivacyGate,
    ContextProvenanceGate,
    ContextSegmentOrderGate,
    ContextStablePrefixGate,
)
from tests.framework.harness.context.test_context_models import _graph_identity


def _request(**values):
    return {
        "graph_identity": _graph_identity(),
        "phase": "EXECUTE",
        "worker_id": "context-worker",
        "worker_type": "function",
        **values,
    }


def test_context_gates_accept_valid_assembled_envelope() -> None:
    envelope = ContextAssembler().assemble(
        _request(source_refs=("source://paper#section=abstract",))
    )

    assert ContextSegmentOrderGate().evaluate(envelope).passed is True
    assert ContextStablePrefixGate().evaluate(envelope).passed is True
    assert ContextProvenanceGate().evaluate(envelope).passed is True
    assert ContextCacheKeyGate().evaluate(envelope).passed is True


def test_stable_prefix_gate_rejects_dynamic_tool_result() -> None:
    envelope = ContextAssembler().assemble(_request())
    bad_segment = replace(envelope.segments[0], metadata={**envelope.segments[0].metadata, "content_markers": ["tool_result"]})
    bad = replace(
        envelope,
        segments=(bad_segment, *envelope.segments[1:]),
        checksum=None,
    )

    result = ContextStablePrefixGate().evaluate(bad)

    assert result.passed is False
    assert result.details["violations"] == ["global-policy"]


def test_privacy_gate_rejects_private_memory_without_consent() -> None:
    envelope = ContextAssembler().assemble(_request())
    private_segment = replace(
        envelope.segments[4],
        metadata={**envelope.segments[4].metadata, "content_markers": ["private_memory"]},
    )
    bad = replace(
        envelope,
        segments=(*envelope.segments[:4], private_segment, envelope.segments[5]),
        checksum=None,
    )

    result = ContextPrivacyGate().evaluate(bad)

    assert result.passed is False
    assert result.details["violations"] == ["evidence-memory"]
