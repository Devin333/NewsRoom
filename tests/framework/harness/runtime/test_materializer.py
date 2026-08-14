from __future__ import annotations

import hashlib
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from framework.harness.artifacts.catalog import (
    ArtifactCatalogClaim,
    ArtifactCatalogEntry,
    ArtifactCatalogRegistrationRequest,
    ArtifactCatalogRegistrationResult,
)
from framework.harness.artifacts.ports import ArtifactPort, ArtifactRef, ArtifactWriteRequest
from framework.harness.runtime import (
    ArtifactClass,
    BoundedSummary,
    ContextPolicy,
    GraphArtifactPersistenceConfig,
    GraphArtifactRolloutMode,
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    NodeResultBinding,
    NodeResultRequest,
    NodeResultStatus,
    PersistenceMode,
    PersistencePolicy,
    ResultMaterializationOutcome,
    ResultMaterializer,
    ResultQuotaReservation,
    ResultSensitivity,
    ResultProvenance,
    RetentionClass,
)
from framework.harness.runtime.materializer import ResultCacheWriteRequest
from framework.harness.runtime.result_models import NodeResultEnvelope
from framework.shared.json import stable_json_dumps


NOW = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
DEPENDENCY = "sha256:" + "b" * 64


class RecordingArtifactPort:
    def __init__(self) -> None:
        self.payloads: dict[str, dict[str, Any]] = {}
        self.refs: dict[str, ArtifactRef] = {}
        self.tamper = False
        self.write_count = 0

    @contextmanager
    def bind_run(self, run_id: str):
        yield run_id

    def write_artifact(self, request: ArtifactWriteRequest) -> ArtifactRef:
        self.write_count += 1
        content = stable_json_dumps(request.to_dict()).encode("utf-8")
        ref = f"artifact://recording/{request.artifact_type}"
        artifact_ref = ArtifactRef(
            ref=ref,
            artifact_type=request.artifact_type,
            checksum="sha256:" + hashlib.sha256(content).hexdigest(),
            media_type=request.media_type,
            metadata=request.metadata,
        )
        self.payloads[ref] = request.to_dict()
        self.refs[ref] = artifact_ref
        return artifact_ref

    def read_artifact(self, ref: str) -> dict[str, Any]:
        payload = self.payloads[ref]
        if self.tamper:
            payload = dict(payload)
            nested = dict(payload["payload"])
            nested["candidate_checksum"] = "sha256:" + "f" * 64
            payload["payload"] = nested
        return payload


class RecordingCatalog:
    def __init__(self) -> None:
        self.requests: list[ArtifactCatalogRegistrationRequest] = []

    def register(self, request: ArtifactCatalogRegistrationRequest):
        self.requests.append(request)
        entry = ArtifactCatalogEntry.from_verified_record(
            request.record,
            request.verification,
        )
        return ArtifactCatalogRegistrationResult(
            entry=entry,
            claim=ArtifactCatalogClaim.for_record(
                request.record,
                entry_id=entry.entry_id,
            ),
            reference=request.initial_reference,
            deduplicated=False,
        )


class RecordingQuota:
    def __init__(self, *, allow: bool = True) -> None:
        self.allow = allow
        self.reservations: list[ResultQuotaReservation] = []
        self.settlements: list[tuple[ResultQuotaReservation, int, int, ResultMaterializationOutcome]] = []

    def reserve(
        self,
        *,
        tenant_id,
        run_id,
        graph_id,
        node_id,
        artifact_class,
        retention_class,
        policy_version,
        reservation_key,
        requested_bytes,
        object_count,
    ):
        if not self.allow:
            return None
        reservation = ResultQuotaReservation(
            reservation_id=f"quota://{len(self.reservations) + 1}",
            tenant_id=tenant_id,
            run_id=run_id,
            graph_id=graph_id,
            node_id=node_id,
            artifact_class=artifact_class,
            retention_class=retention_class,
            policy_version=policy_version,
            reservation_key=reservation_key,
            generation=1,
            reserved_bytes=requested_bytes,
            object_count=object_count,
        )
        self.reservations.append(reservation)
        return reservation

    def settle(self, reservation, *, actual_bytes, object_count, outcome):
        self.settlements.append((reservation, actual_bytes, object_count, outcome))


class RecordingCache:
    def __init__(self) -> None:
        self.entries: dict[str, ResultCacheWriteRequest] = {}
        self.write_count = 0

    def write(self, request: ResultCacheWriteRequest) -> str:
        self.write_count += 1
        self.entries[request.cache_key] = request
        return request.cache_key

    def read(self, ref: str):
        request = self.entries[ref]
        return dict(request.payload)


class RecordingAttempts:
    def __init__(self) -> None:
        self.envelopes: dict[tuple[str, ...], NodeResultEnvelope] = {}
        self.put_count = 0

    def get(self, binding):
        return self.envelopes.get(_key(binding))

    def put(self, envelope):
        self.put_count += 1
        key = _key(envelope.binding)
        existing = self.envelopes.get(key)
        if existing is not None:
            return existing
        self.envelopes[key] = envelope
        return envelope


class FailingAttempts(RecordingAttempts):
    def put(self, envelope):
        raise RuntimeError("ledger unavailable")


def _key(binding):
    return (
        binding.tenant_id,
        binding.tenant_scope_ref,
        binding.run_id,
        binding.graph_id,
        binding.node_id,
        binding.attempt_id,
    )


def _request(
    *,
    candidate: Any = None,
    artifact_class: ArtifactClass = ArtifactClass.CONTROL,
    sensitivity: ResultSensitivity = ResultSensitivity.INTERNAL,
    reusable: bool = False,
    dependency_digest: str | None = None,
    required_for_replay: bool = False,
) -> NodeResultRequest:
    value = {"count": 1} if candidate is None else candidate
    return NodeResultRequest(
        binding=NodeResultBinding(
            tenant_id="tenant-1",
            tenant_scope_ref=DIGEST,
            run_id="run-1",
            graph_id="graph-1",
            graph_version="graph-1@1",
            node_id="node-1",
            attempt_id="attempt-1",
            parent_checkpoint_ref="checkpoint://run-1/0",
        ),
        status=NodeResultStatus.SUCCEEDED,
        output_schema_ref="node-result@1",
        output_schema_digest=DIGEST,
        candidate=value,
        media_type="application/json",
        summary=BoundedSummary.from_text("bounded summary"),
        inline_projection={"count": value.get("count", 0)} if isinstance(value, dict) else {},
        inline_allowed_fields=("count",),
        provenance=ResultProvenance(
            producer_ref="worker@1",
            producer_revision="worker-revision@abc123",
        ),
        artifact_class=artifact_class,
        retention_class=RetentionClass.RUN,
        sensitivity=sensitivity,
        required_for_replay=required_for_replay,
        required_for_publication=False,
        reusable=reusable,
        side_effect_free=True,
        dependency_digest=dependency_digest,
        context_policy=ContextPolicy.SUMMARY_ONLY,
        created_at=NOW,
    )


def _materializer(*, quota=None, attempts=None, cache=None, artifact=None, catalog=None, observations=None, config=None):
    return ResultMaterializer(
        policy=PersistencePolicy(config or GraphArtifactPersistenceConfig()),
        artifact_port=artifact or RecordingArtifactPort(),
        catalog=catalog or RecordingCatalog(),
        quota=quota or RecordingQuota(),
        cache=cache or RecordingCache(),
        attempts=attempts or RecordingAttempts(),
        clock=lambda: NOW,
        observation_sink=(observations.append if observations is not None else None),
    )


def test_inline_and_artifact_threshold_use_single_materializer_path() -> None:
    attempts = RecordingAttempts()
    artifact = RecordingArtifactPort()
    materializer = _materializer(attempts=attempts, artifact=artifact)

    inline = materializer.materialize(_request())
    assert inline.envelope.persistence_decision.mode is PersistenceMode.INLINE
    assert inline.envelope.materialized_refs == ()
    assert artifact.write_count == 0

    large = _request(candidate={"data": "x" * (32 * 1024)})
    large = replace(
        large,
        binding=replace(large.binding, attempt_id="attempt-2"),
    )
    artifact_result = materializer.materialize(large)
    assert artifact_result.envelope.persistence_decision.mode is PersistenceMode.ARTIFACT
    assert len(artifact_result.envelope.materialized_refs) == 1
    assert artifact_result.envelope.inline_projection == {"count": 0}
    assert artifact_result.envelope.metrics.inline_bytes > 0
    assert artifact.write_count == 1


def test_require_existing_returns_matching_attempt_without_any_write() -> None:
    attempts = RecordingAttempts()
    artifact = RecordingArtifactPort()
    catalog = RecordingCatalog()
    quota = RecordingQuota()
    cache = RecordingCache()
    materializer = _materializer(
        attempts=attempts,
        artifact=artifact,
        catalog=catalog,
        quota=quota,
        cache=cache,
        config=GraphArtifactPersistenceConfig(
            mode=GraphArtifactRolloutMode.ENFORCE
        ),
    )
    request = _request(
        candidate={"data": "x" * (32 * 1024)},
        required_for_replay=True,
    )
    first = materializer.materialize(request).envelope
    write_counts = (
        artifact.write_count,
        attempts.put_count,
        len(catalog.requests),
        len(quota.settlements),
    )

    read_only = _materializer(
        attempts=attempts,
        artifact=artifact,
        catalog=catalog,
        quota=quota,
        cache=cache,
        config=GraphArtifactPersistenceConfig(
            mode=GraphArtifactRolloutMode.READ_ONLY
        ),
    )

    assert read_only.require_existing(request) == first
    assert (
        artifact.write_count,
        attempts.put_count,
        len(catalog.requests),
        len(quota.settlements),
    ) == write_counts


def test_require_existing_fails_closed_for_missing_or_conflicting_attempt() -> None:
    attempts = RecordingAttempts()
    artifact = RecordingArtifactPort()
    materializer = _materializer(
        attempts=attempts,
        artifact=artifact,
        config=GraphArtifactPersistenceConfig(
            mode=GraphArtifactRolloutMode.READ_ONLY
        ),
    )
    request = _request(required_for_replay=True)

    with pytest.raises(GraphArtifactResultError) as missing:
        materializer.require_existing(request)

    assert missing.value.error_code is GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED
    assert artifact.write_count == 0
    assert attempts.put_count == 0

    writer = _materializer(
        attempts=attempts,
        artifact=artifact,
        config=GraphArtifactPersistenceConfig(
            mode=GraphArtifactRolloutMode.ENFORCE
        ),
    )
    writer.materialize(request)
    conflicting = replace(request, candidate={"count": 2})

    with pytest.raises(GraphArtifactResultError) as conflict:
        materializer.require_existing(conflicting)

    assert conflict.value.error_code is GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT


def test_artifact_readback_registers_catalog_and_settles_once() -> None:
    quota = RecordingQuota()
    catalog = RecordingCatalog()
    materializer = _materializer(quota=quota, catalog=catalog)

    result = materializer.materialize(_request(candidate={"data": "x" * (32 * 1024)}))

    assert len(catalog.requests) == 1
    assert quota.settlements[0][2:] == (1, ResultMaterializationOutcome.SUCCEEDED)
    assert quota.settlements[0][1] == result.envelope.metrics.candidate_bytes


def test_tampered_artifact_readback_fails_closed_without_catalog() -> None:
    artifact = RecordingArtifactPort()
    catalog = RecordingCatalog()
    quota = RecordingQuota()
    observations = []
    materializer = _materializer(
        artifact=artifact,
        catalog=catalog,
        quota=quota,
        observations=observations,
    )
    request = _request(candidate={"data": "x" * (32 * 1024)})
    artifact.tamper = True

    with pytest.raises(GraphArtifactResultError) as exc_info:
        materializer.materialize(request)

    assert exc_info.value.error_code is GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED
    assert catalog.requests == []
    assert quota.settlements[0][3] is ResultMaterializationOutcome.FAILED
    assert observations[-1].error_code is GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED


def test_required_quota_rejection_fails_and_optional_result_is_omitted() -> None:
    required = _request(
        candidate={"data": "x" * (32 * 1024)},
        artifact_class=ArtifactClass.EVIDENCE,
    )
    required_quota = RecordingQuota(allow=False)
    required_artifact = RecordingArtifactPort()
    with pytest.raises(GraphArtifactResultError) as required_error:
        _materializer(quota=required_quota, artifact=required_artifact).materialize(required)
    assert required_error.value.error_code is GraphArtifactResultErrorCode.ARTIFACT_QUOTA_EXCEEDED
    assert required_artifact.write_count == 0

    optional_quota = RecordingQuota(allow=False)
    observations = []
    optional = _materializer(quota=optional_quota, observations=observations).materialize(
        _request(candidate={"data": "x" * (32 * 1024)})
    )
    assert optional.envelope.persistence_decision.mode is PersistenceMode.OMITTED
    assert optional.envelope.inline_projection == {}
    assert observations[-1].outcome is ResultMaterializationOutcome.OMITTED


def test_cache_path_verifies_payload_and_returns_tenant_scoped_ref() -> None:
    cache = RecordingCache()
    quota = RecordingQuota()
    attempts = RecordingAttempts()
    result = _materializer(cache=cache, quota=quota, attempts=attempts).materialize(
        _request(
            candidate={"value": "reusable"},
            reusable=True,
            dependency_digest=DEPENDENCY,
        )
    )
    assert result.envelope.persistence_decision.mode is PersistenceMode.CACHE
    assert result.envelope.cache_refs[0].tenant_id == "tenant-1"
    assert result.envelope.inline_projection == {"count": 0}
    assert cache.write_count == 1


def test_retry_is_idempotent_and_conflicting_candidate_is_rejected() -> None:
    attempts = RecordingAttempts()
    artifact = RecordingArtifactPort()
    materializer = _materializer(attempts=attempts, artifact=artifact)
    request = _request(candidate={"data": "x" * (32 * 1024)})

    first = materializer.materialize(request)
    second = materializer.materialize(request)
    assert second.envelope == first.envelope
    assert artifact.write_count == 1
    assert attempts.put_count == 1

    with pytest.raises(GraphArtifactResultError) as exc_info:
        materializer.materialize(_request(candidate={"data": "different" * 4096}))
    assert exc_info.value.error_code is GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT


def test_ledger_failure_does_not_settle_quota_twice() -> None:
    quota = RecordingQuota()
    with pytest.raises(GraphArtifactResultError) as exc_info:
        _materializer(quota=quota, attempts=FailingAttempts()).materialize(
            _request(candidate={"data": "x" * (32 * 1024)})
        )
    assert exc_info.value.error_code is GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED
    assert len(quota.settlements) == 1


def test_observation_does_not_contain_candidate_payload() -> None:
    observations = []
    result = _materializer(observations=observations).materialize(
        _request(candidate={"data": "secret-looking-but-not-sensitive"})
    )
    rendered = stable_json_dumps(result.observation.to_dict())
    assert "secret-looking-but-not-sensitive" not in rendered
