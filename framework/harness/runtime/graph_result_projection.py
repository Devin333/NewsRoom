from __future__ import annotations

from framework.harness.control_plane.graph_result_lineage import (
    HarnessGraphArtifactRefProjection,
    HarnessGraphCacheRefProjection,
    HarnessGraphResultLineage,
    HarnessGraphResultSummary,
)
from framework.harness.runtime.result_models import NodeResultEnvelope
from framework.harness.graph.canonical import canonical_checksum, required_text
from framework.shared.time import format_datetime


def graph_result_lineage_from_envelope(
    envelope: NodeResultEnvelope,
    *,
    node_instance_id: str,
    attempt: int,
    identity_scope_ref: str | None = None,
    subject_scope_ref: str | None = None,
    context_fingerprint: str | None = None,
) -> HarnessGraphResultLineage:
    """Project a complete materialized envelope into bounded control-plane lineage."""

    if not isinstance(envelope, NodeResultEnvelope):
        raise TypeError("envelope must be NodeResultEnvelope")
    decision = envelope.persistence_decision
    binding = envelope.binding
    resolved_node_instance_id = required_text(node_instance_id, "node_instance_id")
    return HarnessGraphResultLineage(
        tenant_id=envelope.binding.tenant_id,
        run_id=envelope.binding.run_id,
        graph_id=envelope.binding.graph_id,
        graph_version=envelope.binding.graph_version,
        node_id=envelope.binding.node_id,
        node_instance_id=resolved_node_instance_id,
        attempt_id=envelope.binding.attempt_id,
        attempt=attempt,
        parent_checkpoint_ref=envelope.binding.parent_checkpoint_ref,
        status=envelope.status.value,
        output_schema_ref=envelope.output_schema_ref,
        output_schema_digest=envelope.output_schema_digest,
        candidate_checksum=envelope.candidate_checksum,
        envelope_checksum=canonical_checksum(envelope.to_dict()),
        candidate_bytes=envelope.metrics.candidate_bytes,
        candidate_tokens=envelope.metrics.candidate_tokens,
        summary=HarnessGraphResultSummary(**envelope.summary.to_dict()),
        inline_projection=envelope.inline_projection,
        artifact_refs=tuple(
            HarnessGraphArtifactRefProjection(
                ref=item.ref,
                artifact_id=item.artifact_id,
                artifact_type=item.artifact_type,
                content_checksum=item.content_checksum,
                byte_size=item.byte_size,
                media_type=item.media_type,
                artifact_class=item.artifact_class.value,
                retention_class=item.retention_class.value,
                tenant_id=item.tenant_id,
                run_id=item.run_id,
                graph_id=item.graph_id,
                node_id=item.node_id,
                attempt_id=item.attempt_id,
                sensitivity=item.sensitivity.value,
                context_policy=decision.context_policy.value,
                required_for_replay=item.required_for_replay,
                required_for_publication=item.required_for_publication,
            )
            for item in envelope.materialized_refs
        ),
        cache_refs=tuple(
            HarnessGraphCacheRefProjection(
                ref=item.ref,
                tenant_id=item.tenant_id,
                content_checksum=item.content_checksum,
                dependency_digest=item.dependency_digest,
                media_type=item.media_type,
                byte_size=item.byte_size,
                policy_version=item.policy_version,
                expires_at=format_datetime(item.expires_at) or "",
            )
            for item in envelope.cache_refs
        ),
        persistence_mode=decision.mode.value,
        policy_version=decision.policy_version,
        required=decision.required,
        tenant_scope_ref=binding.tenant_scope_ref,
        identity_scope_ref=identity_scope_ref,
        subject_scope_ref=subject_scope_ref,
        context_fingerprint=context_fingerprint,
        producer_ref=envelope.provenance.producer_ref,
        producer_revision=envelope.provenance.producer_revision,
        source_refs=envelope.provenance.source_refs,
        parent_result_refs=envelope.provenance.parent_result_refs,
        inline_bytes=envelope.metrics.inline_bytes,
    )


__all__ = ["graph_result_lineage_from_envelope"]
