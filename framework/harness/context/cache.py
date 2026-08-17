from __future__ import annotations

import hashlib

from framework.harness.context.models import ContextCachePolicy, ContextCacheScope, ContextEnvelope
from framework.shared.json import stable_json_dumps


class ContextCachePolicyBuilder:
    def build(self, envelope: ContextEnvelope, *, provider_hint: str | None = None) -> ContextCachePolicy:
        stable_segments = tuple(
            segment.segment_id for segment in envelope.segments if segment.cache_scope == ContextCacheScope.STABLE_PREFIX
        )
        dynamic_segments = tuple(
            segment.segment_id for segment in envelope.segments if segment.cache_scope == ContextCacheScope.DYNAMIC_TAIL
        )
        stable_payload = [
            segment.to_dict()
            for segment in envelope.segments
            if segment.cache_scope == ContextCacheScope.STABLE_PREFIX
        ]
        if envelope.is_graph_only:
            if envelope.graph_identity is None:  # pragma: no cover - model invariant
                raise AssertionError("Graph-only context identity is unavailable")
            cache_projection = {
                "schema_version": envelope.schema_version,
                "graph_identity": envelope.graph_identity.to_dict(),
                "worker_id": envelope.worker_id,
                "worker_type": envelope.worker_type,
                "stable_segments": stable_payload,
            }
        else:
            cache_projection = {
                "workflow_id": envelope.workflow_id,
                "worker_id": envelope.worker_id,
                "worker_type": envelope.worker_type,
                "stable_segments": stable_payload,
            }
        digest = hashlib.sha256(
            stable_json_dumps(cache_projection).encode()
        ).hexdigest()
        return ContextCachePolicy(
            cache_enabled=bool(stable_segments),
            stable_prefix_segments=stable_segments,
            dynamic_tail_segments=dynamic_segments,
            cache_key=f"context-cache:{digest}",
            provider_hint=provider_hint,
            ttl_hint=3600,
        )


__all__ = ["ContextCachePolicyBuilder"]
