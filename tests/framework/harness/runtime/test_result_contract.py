from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from framework.harness.runtime import (
    ArtifactClass,
    ArtifactRecord,
    BoundedSummary,
    CacheRef,
    ContextAssemblyRequest,
    ContextLoadMode,
    ContextPolicy,
    ContextPurpose,
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    NodeResultBinding,
    NodeResultEnvelope,
    NodeResultStatus,
    PersistenceDecision,
    PersistenceMode,
    PersistenceReason,
    ResultMetrics,
    ResultProvenance,
    ResultSensitivity,
    RetentionClass,
)
from framework.harness.runtime.result_canonical import sha256_checksum
from framework.shared.json import stable_json_dumps


NOW = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
CHECKSUM = "sha256:" + "a" * 64
SCHEMA_DIGEST = "sha256:" + "b" * 64
DEPENDENCY_DIGEST = "sha256:" + "c" * 64
TENANT_SCOPE_REF = "sha256:" + "d" * 64


def _binding(run_id: str = "run-1") -> NodeResultBinding:
    return NodeResultBinding(
        tenant_id="tenant-1",
        tenant_scope_ref=TENANT_SCOPE_REF,
        run_id=run_id,
        graph_id="research-graph",
        graph_version="research-graph@1",
        node_id="collect-evidence",
        attempt_id="attempt-1",
        parent_checkpoint_ref="checkpoint://run-1/0",
    )


def _provenance() -> ResultProvenance:
    return ResultProvenance(
        producer_ref="research-worker@1",
        producer_revision="research-worker-revision@abc123",
        source_refs=("source://paper/1",),
    )


def _decision(
    mode: PersistenceMode = PersistenceMode.INLINE,
    *,
    size: int = 17,
) -> PersistenceDecision:
    return PersistenceDecision(
        mode=mode,
        reason=(
            PersistenceReason.BELOW_INLINE_THRESHOLD
            if mode is PersistenceMode.INLINE
            else PersistenceReason.LARGE_PAYLOAD
        ),
        artifact_class=ArtifactClass.CONTROL,
        retention_class=RetentionClass.RUN,
        estimated_bytes=size,
        reserved_bytes=size if mode in {PersistenceMode.ARTIFACT, PersistenceMode.CACHE} else 0,
        context_policy=ContextPolicy.SUMMARY_ONLY,
        required=False,
        policy_version="graph-artifact-policy@1",
    )


def _artifact(
    *,
    run_id: str = "run-1",
    content_checksum: str = CHECKSUM,
) -> ArtifactRecord:
    return ArtifactRecord(
        ref="artifact://tenant-1/run-1/result",
        artifact_id="artifact-1",
        artifact_type="node_result",
        content_checksum=content_checksum,
        byte_size=17,
        media_type="application/json",
        artifact_class=ArtifactClass.CONTROL,
        tenant_id="tenant-1",
        run_id=run_id,
        graph_id="research-graph",
        node_id="collect-evidence",
        attempt_id="attempt-1",
        producer_revision="research-worker-revision@abc123",
        sensitivity=ResultSensitivity.INTERNAL,
        reusable=False,
        dependency_digest=None,
        retention_class=RetentionClass.RUN,
        expires_at=NOW + timedelta(days=30),
        required_for_replay=False,
        required_for_publication=False,
        created_at=NOW,
    )


def _envelope(
    *,
    mode: PersistenceMode = PersistenceMode.INLINE,
    artifact: ArtifactRecord | None = None,
    cache: CacheRef | None = None,
) -> NodeResultEnvelope:
    projection = {"count": 1} if mode is PersistenceMode.INLINE else {}
    summary = BoundedSummary.from_text("one result")
    return NodeResultEnvelope(
        binding=_binding(),
        status=NodeResultStatus.SUCCEEDED,
        output_schema_ref="research-result@1",
        output_schema_digest=SCHEMA_DIGEST,
        candidate_checksum=CHECKSUM,
        summary=summary,
        inline_projection=projection,
        materialized_refs=(artifact,) if artifact is not None else (),
        cache_refs=(cache,) if cache is not None else (),
        provenance=_provenance(),
        persistence_decision=_decision(mode),
        metrics=ResultMetrics(
            candidate_bytes=17,
            candidate_tokens=5,
            summary_bytes=summary.byte_size,
            inline_bytes=len(stable_json_dumps(projection).encode("utf-8")),
        ),
        created_at=NOW,
    )


def test_binding_and_summary_are_immutable_exact_contracts() -> None:
    binding = _binding()
    summary = BoundedSummary.from_text("bounded")

    assert NodeResultBinding.from_dict(binding.to_dict()) == binding
    assert BoundedSummary.from_dict(summary.to_dict()) == summary
    with pytest.raises(FrozenInstanceError):
        binding.run_id = "other"  # type: ignore[misc]
    with pytest.raises(GraphArtifactResultError) as exc_info:
        NodeResultBinding.from_dict({**binding.to_dict(), "route": "publish"})
    assert exc_info.value.error_code is GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID


def test_summary_rejects_mismatched_derived_sizes() -> None:
    with pytest.raises(GraphArtifactResultError) as exc_info:
        BoundedSummary(text="evidence", byte_size=1, token_estimate=1)

    assert exc_info.value.error_code is GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID


def test_inline_envelope_round_trips_with_stable_serialization() -> None:
    envelope = _envelope()
    payload = envelope.to_dict()

    restored = NodeResultEnvelope.from_dict(payload)

    assert restored == envelope
    assert stable_json_dumps(restored.to_dict()) == stable_json_dumps(payload)
    assert restored.run_id == "run-1"
    assert restored.inline_projection == {"count": 1}
    with pytest.raises(TypeError):
        restored.inline_projection["count"] = 2  # type: ignore[index]


def test_artifact_envelope_rejects_cross_run_and_checksum_mismatch() -> None:
    with pytest.raises(GraphArtifactResultError) as cross_run:
        _envelope(mode=PersistenceMode.ARTIFACT, artifact=_artifact(run_id="run-2"))
    assert cross_run.value.error_code is GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH

    with pytest.raises(GraphArtifactResultError) as checksum_mismatch:
        _envelope(
            mode=PersistenceMode.ARTIFACT,
            artifact=_artifact(content_checksum="sha256:" + "d" * 64),
        )
    assert checksum_mismatch.value.error_code is GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH


def test_cache_ref_requires_complete_dependency_identity() -> None:
    with pytest.raises(GraphArtifactResultError) as exc_info:
        ArtifactRecord(
            **{
                **_artifact().to_dict(),
                "created_at": NOW,
                "expires_at": NOW + timedelta(days=1),
                "reusable": True,
                "dependency_digest": None,
            }
        )

    assert exc_info.value.error_code is GraphArtifactResultErrorCode.CACHE_IDENTITY_INVALID


def test_context_request_deduplicates_refs_and_enforces_budget() -> None:
    request = ContextAssemblyRequest(
        tenant_id="tenant-1",
        run_id="run-1",
        graph_id="graph-1",
        node_id="node-1",
        purpose=ContextPurpose.VERIFY,
        allowed_artifact_classes=(ArtifactClass.EVIDENCE,),
        allowed_sensitivities=(ResultSensitivity.INTERNAL,),
        artifact_refs=("artifact://one", "artifact://one"),
        max_refs=2,
        max_bytes=1024,
        max_tokens=256,
        load_mode=ContextLoadMode.SUMMARY_ONLY,
    )
    assert request.artifact_refs == ("artifact://one",)
    assert ContextAssemblyRequest.from_dict(request.to_dict()) == request

    with pytest.raises(GraphArtifactResultError) as over_budget:
        ContextAssemblyRequest(
            tenant_id="tenant-1",
            run_id="run-1",
            graph_id="graph-1",
            node_id="node-1",
            purpose=ContextPurpose.VERIFY,
            allowed_artifact_classes=(ArtifactClass.EVIDENCE,),
            allowed_sensitivities=(ResultSensitivity.INTERNAL,),
            artifact_refs=("artifact://one", "artifact://two"),
            max_refs=1,
            max_bytes=1024,
            max_tokens=256,
            load_mode=ContextLoadMode.FULL,
        )
    assert over_budget.value.error_code is GraphArtifactResultErrorCode.CONTEXT_BUDGET_EXCEEDED


def test_error_payload_is_stable_and_does_not_echo_unknown_details() -> None:
    secret = "sk-private-do-not-serialize"
    error = GraphArtifactResultError(
        GraphArtifactResultErrorCode.ARTIFACT_WRITE_FAILED,
        details={
            "field": "artifact",
            "path": "C:/private/artifact.json",
            "exception": secret,
            "candidate": {"api_key": secret},
        },
    )

    payload = error.to_event_payload()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload == {
        "code": "artifact_write_failed",
        "message": "graph artifact result could not be written",
        "retryable": True,
        "details": {"field": "artifact"},
    }
    assert secret not in serialized
    assert "C:/private" not in serialized


def test_checksum_helper_is_content_deterministic() -> None:
    assert sha256_checksum(b"same") == sha256_checksum(b"same")
    assert sha256_checksum(b"same") != sha256_checksum(b"different")
    assert sha256_checksum(b"same").startswith("sha256:")
