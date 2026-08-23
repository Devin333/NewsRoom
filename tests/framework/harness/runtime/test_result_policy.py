from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from framework.harness.runtime import (
    ArtifactClass,
    BoundedSummary,
    ContextPolicy,
    GraphArtifactPersistenceConfig,
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    GraphArtifactRolloutMode,
    NodeResultBinding,
    NodeResultRequest,
    NodeResultStatus,
    PersistenceBudgetSnapshot,
    PersistenceMode,
    PersistencePolicy,
    PersistenceReason,
    ResultProvenance,
    ResultSensitivity,
    RetentionClass,
)
from framework.shared.json import stable_json_dumps


NOW = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
DEPENDENCY = "sha256:" + "b" * 64


def _request(
    *,
    candidate: object = None,
    summary: str = "bounded summary",
    artifact_class: ArtifactClass = ArtifactClass.CONTROL,
    retention_class: RetentionClass = RetentionClass.RUN,
    sensitivity: ResultSensitivity = ResultSensitivity.INTERNAL,
    required_for_replay: bool = False,
    required_for_publication: bool = False,
    reusable: bool = False,
    side_effect_free: bool = True,
    dependency_digest: str | None = None,
) -> NodeResultRequest:
    actual_candidate = {"count": 1} if candidate is None else candidate
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
        candidate=actual_candidate,
        media_type="application/json",
        summary=BoundedSummary.from_text(summary),
        inline_projection=(
            {"count": actual_candidate.get("count", 0)}
            if isinstance(actual_candidate, dict)
            else {}
        ),
        inline_allowed_fields=("count",),
        provenance=ResultProvenance(
            producer_ref="worker@1",
            producer_revision="worker-revision@abc123",
        ),
        artifact_class=artifact_class,
        retention_class=retention_class,
        sensitivity=sensitivity,
        required_for_replay=required_for_replay,
        required_for_publication=required_for_publication,
        reusable=reusable,
        side_effect_free=side_effect_free,
        dependency_digest=dependency_digest,
        context_policy=ContextPolicy.SUMMARY_ONLY,
        created_at=NOW,
    )


def test_default_config_matches_prd_and_round_trips() -> None:
    config = GraphArtifactPersistenceConfig()

    assert config.mode is GraphArtifactRolloutMode.ENFORCE
    assert config.inline_max_bytes == 32 * 1024
    assert config.summary_max_bytes == 8 * 1024
    assert config.max_artifact_bytes == 512 * 1024 * 1024
    assert config.max_materialized_bytes_per_run == 500 * 1024 * 1024
    assert config.max_materialized_bytes_per_tenant == 50 * 1024 * 1024 * 1024
    assert config.max_materialized_bytes_per_class == 20 * 1024 * 1024 * 1024
    assert config.quota_alert_threshold_basis_points == 8_000
    assert GraphArtifactPersistenceConfig.from_dict(config.to_dict()) == config


@pytest.mark.parametrize("mode", ("legacy", "shadow", "read_only"))
def test_config_rejects_retired_rollout_modes(mode: str) -> None:
    with pytest.raises(GraphArtifactResultError) as exc_info:
        GraphArtifactPersistenceConfig(mode=mode)

    assert exc_info.value.error_code is GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("inline_max_bytes", 0),
        ("inline_max_depth", 33),
        ("summary_max_bytes", 2 * 1024 * 1024),
        ("max_artifact_bytes", 513 * 1024 * 1024),
        ("max_artifacts_per_run", 0),
        ("max_artifacts_per_tenant", 0),
        ("max_materialized_bytes_per_class", 0),
        ("quota_alert_threshold_basis_points", 10_001),
        ("cache_stampede_miss_threshold", 1),
        ("cache_default_ttl_seconds", 59),
    ],
)
def test_config_rejects_out_of_range_values(field: str, value: int) -> None:
    with pytest.raises(GraphArtifactResultError) as exc_info:
        replace(GraphArtifactPersistenceConfig(), **{field: value})

    assert exc_info.value.error_code is GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_artifacts_per_run": 3, "max_artifacts_per_tenant": 2},
        {"max_artifacts_per_class": 3, "max_artifacts_per_tenant": 2},
        {
            "max_materialized_bytes_per_run": 2_048,
            "max_materialized_bytes_per_tenant": 1_024,
        },
        {
            "max_materialized_bytes_per_class": 2_048,
            "max_materialized_bytes_per_tenant": 1_024,
        },
    ],
)
def test_config_rejects_inconsistent_aggregate_quota(
    overrides: dict[str, int],
) -> None:
    with pytest.raises(GraphArtifactResultError) as exc_info:
        replace(GraphArtifactPersistenceConfig(), **overrides)

    assert exc_info.value.error_code is GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID


def test_config_rejects_unreadable_policy_and_accepts_explicit_rollback() -> None:
    with pytest.raises(GraphArtifactResultError) as exc_info:
        GraphArtifactPersistenceConfig(
            policy_version="graph-artifact-policy@2",
            readable_policy_versions=("graph-artifact-policy@1",),
        )
    assert exc_info.value.error_code is GraphArtifactResultErrorCode.POLICY_VERSION_UNSUPPORTED

    config = GraphArtifactPersistenceConfig(
        policy_version="graph-artifact-policy@2",
        readable_policy_versions=(
            "graph-artifact-policy@1",
            "graph-artifact-policy@2",
        ),
    )
    assert config.ensure_readable_policy_version("graph-artifact-policy@1") == "graph-artifact-policy@1"


def test_small_control_candidate_is_inline_and_deterministic() -> None:
    request = _request(candidate={"message": "small", "count": 1})
    policy = PersistencePolicy(GraphArtifactPersistenceConfig())

    first = policy.evaluate(request)
    second = policy.evaluate(request)

    assert first == second
    assert first.decision.mode is PersistenceMode.INLINE
    assert first.decision.reason is PersistenceReason.BELOW_INLINE_THRESHOLD
    assert first.decision.reserved_bytes == 0
    assert stable_json_dumps(first.to_dict()) == stable_json_dumps(second.to_dict())


@pytest.mark.parametrize(
    ("artifact_class", "reason"),
    [
        (ArtifactClass.EVIDENCE, PersistenceReason.REQUIRED_EVIDENCE),
        (ArtifactClass.TRANSCRIPT, PersistenceReason.REQUIRED_TRANSCRIPT),
        (ArtifactClass.REPORT, PersistenceReason.REQUIRED_REPORT),
    ],
)
def test_required_durable_classes_are_artifacts(
    artifact_class: ArtifactClass,
    reason: PersistenceReason,
) -> None:
    evaluation = PersistencePolicy(GraphArtifactPersistenceConfig()).evaluate(
        _request(artifact_class=artifact_class)
    )

    assert evaluation.decision.mode is PersistenceMode.ARTIFACT
    assert evaluation.decision.reason is reason
    assert evaluation.decision.required is True


def test_reusable_side_effect_free_candidate_with_dependency_uses_cache() -> None:
    evaluation = PersistencePolicy(GraphArtifactPersistenceConfig()).evaluate(
        _request(
            artifact_class=ArtifactClass.INTERMEDIATE,
            retention_class=RetentionClass.CACHE,
            reusable=True,
            dependency_digest=DEPENDENCY,
        )
    )

    assert evaluation.decision.mode is PersistenceMode.CACHE
    assert evaluation.decision.reason is PersistenceReason.REUSABLE_DETERMINISTIC_RESULT
    assert evaluation.decision.retention_class is RetentionClass.CACHE


def test_reusable_candidate_without_complete_identity_fails_closed() -> None:
    with pytest.raises(GraphArtifactResultError) as exc_info:
        _request(reusable=True, dependency_digest=None)

    assert exc_info.value.error_code is GraphArtifactResultErrorCode.CACHE_IDENTITY_INVALID


def test_large_optional_candidate_uses_artifact_then_omits_at_quota() -> None:
    config = GraphArtifactPersistenceConfig(
        max_artifact_bytes=2 * 1024 * 1024,
        max_materialized_bytes_per_run=2 * 1024 * 1024,
    )
    request = _request(candidate={"body": "x" * 40_000, "count": 1})
    policy = PersistencePolicy(config)

    available = policy.evaluate(request)
    omitted = policy.evaluate(
        request,
        budget=PersistenceBudgetSnapshot(
            materialized_bytes=config.max_materialized_bytes_per_run,
            artifact_count=0,
        ),
    )

    assert available.decision.mode is PersistenceMode.ARTIFACT
    assert available.decision.reason is PersistenceReason.LARGE_PAYLOAD
    assert omitted.decision.mode is PersistenceMode.OMITTED
    assert omitted.decision.reason is PersistenceReason.QUOTA_EXCEEDED


def test_required_candidate_at_quota_fails_closed() -> None:
    config = GraphArtifactPersistenceConfig()
    with pytest.raises(GraphArtifactResultError) as exc_info:
        PersistencePolicy(config).evaluate(
            _request(artifact_class=ArtifactClass.EVIDENCE),
            budget=PersistenceBudgetSnapshot(
                materialized_bytes=config.max_materialized_bytes_per_run,
                artifact_count=config.max_artifacts_per_run,
            ),
        )

    assert exc_info.value.error_code is GraphArtifactResultErrorCode.ARTIFACT_QUOTA_EXCEEDED


@pytest.mark.parametrize("key", ["run_id", "route", "gate_decision", "policy_version"])
def test_worker_candidate_cannot_supply_harness_control_fields(key: str) -> None:
    with pytest.raises(GraphArtifactResultError) as exc_info:
        _request(candidate={"count": 1, key: "worker-choice"})

    assert exc_info.value.error_code is GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID


@pytest.mark.parametrize("key", ["api_key", "password", "private_context", "raw_prompt"])
def test_secret_like_candidate_key_is_rejected_without_echo(key: str) -> None:
    secret = "sk-private-value"
    with pytest.raises(GraphArtifactResultError) as exc_info:
        _request(candidate={"count": 1, key: secret})

    error = exc_info.value
    assert error.error_code is GraphArtifactResultErrorCode.SENSITIVE_PAYLOAD_REJECTED
    assert secret not in stable_json_dumps(error.to_event_payload())


def test_secret_classification_and_oversized_candidate_fail_closed() -> None:
    policy = PersistencePolicy(GraphArtifactPersistenceConfig())
    with pytest.raises(GraphArtifactResultError) as sensitive:
        policy.evaluate(_request(sensitivity=ResultSensitivity.SECRET))
    assert sensitive.value.error_code is GraphArtifactResultErrorCode.SENSITIVE_PAYLOAD_REJECTED

    config = GraphArtifactPersistenceConfig(
        max_artifact_bytes=1024,
        max_materialized_bytes_per_run=1024,
    )
    with pytest.raises(GraphArtifactResultError) as too_large:
        PersistencePolicy(config).evaluate(
            _request(candidate={"body": "x" * 2048, "count": 1})
        )
    assert too_large.value.error_code is GraphArtifactResultErrorCode.RESULT_TOO_LARGE


def test_oversized_summary_fails_without_truncation() -> None:
    config = GraphArtifactPersistenceConfig(summary_max_bytes=16, summary_max_tokens=16)
    request = _request(summary="summary is deliberately over sixteen bytes")

    with pytest.raises(GraphArtifactResultError) as exc_info:
        PersistencePolicy(config).evaluate(request)

    assert exc_info.value.error_code is GraphArtifactResultErrorCode.RESULT_TOO_LARGE
    assert request.summary.text == "summary is deliberately over sixteen bytes"
