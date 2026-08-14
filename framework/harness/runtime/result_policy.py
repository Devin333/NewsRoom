from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from framework.events.canonical import canonical_json_bytes
from framework.harness.runtime.result_canonical import (
    aware_datetime,
    boolean,
    bounded_int,
    canonical_mapping,
    checksum,
    datetime_from_json,
    datetime_to_json,
    enum_value,
    estimated_tokens,
    exact_keys,
    exact_reference,
    media_type,
    non_negative_int,
    optional_text,
    serialize_candidate,
    sha256_checksum,
    stable_tuple,
    thaw_mapping,
)
from framework.harness.runtime.result_errors import (
    GraphArtifactResultErrorCode,
    result_error,
)
from framework.harness.runtime.result_models import (
    ArtifactClass,
    BoundedSummary,
    ContextPolicy,
    NodeResultBinding,
    NodeResultStatus,
    PersistenceDecision,
    PersistenceMode,
    PersistenceReason,
    ResultProvenance,
    ResultSensitivity,
    RetentionClass,
)


MIB = 1024 * 1024
DEFAULT_GRAPH_ARTIFACT_POLICY_VERSION = "graph-artifact-policy@1"


class GraphArtifactRolloutMode(StrEnum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    ENFORCE = "enforce"
    READ_ONLY = "read_only"


class GraphArtifactDedupScope(StrEnum):
    TENANT_CHECKSUM_MEDIA_TYPE = "tenant_checksum_media_type"


@dataclass(frozen=True, slots=True)
class GraphArtifactRetentionSettings:
    ephemeral_days: int = 1
    run_days: int = 30
    evidence_days: int = 180
    report_days: int | None = None
    cache_days: int = 1

    def __post_init__(self) -> None:
        for field_name, minimum, maximum in (
            ("ephemeral_days", 1, 30),
            ("run_days", 1, 365),
            ("evidence_days", 1, 3_650),
            ("cache_days", 1, 30),
        ):
            object.__setattr__(
                self,
                field_name,
                bounded_int(
                    getattr(self, field_name),
                    f"retention.{field_name}",
                    minimum=minimum,
                    maximum=maximum,
                ),
            )
        if self.report_days is not None:
            object.__setattr__(
                self,
                "report_days",
                bounded_int(
                    self.report_days,
                    "retention.report_days",
                    minimum=1,
                    maximum=36_500,
                ),
            )

    def to_dict(self) -> dict[str, int | None]:
        return {
            "ephemeral_days": self.ephemeral_days,
            "run_days": self.run_days,
            "evidence_days": self.evidence_days,
            "report_days": self.report_days,
            "cache_days": self.cache_days,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        return cls(
            **exact_keys(
                value,
                required=frozenset(
                    {
                        "ephemeral_days",
                        "run_days",
                        "evidence_days",
                        "report_days",
                        "cache_days",
                    }
                ),
                model=cls.__name__,
            )
        )


@dataclass(frozen=True, slots=True)
class GraphArtifactPersistenceConfig:
    mode: GraphArtifactRolloutMode = GraphArtifactRolloutMode.SHADOW
    policy_version: str = DEFAULT_GRAPH_ARTIFACT_POLICY_VERSION
    readable_policy_versions: tuple[str, ...] = (
        DEFAULT_GRAPH_ARTIFACT_POLICY_VERSION,
    )
    inline_max_bytes: int = 32 * 1024
    inline_max_depth: int = 8
    inline_max_keys: int = 256
    summary_max_bytes: int = 8 * 1024
    summary_max_tokens: int = 2_048
    sample_max_bytes: int = 64 * 1024
    max_artifact_bytes: int = 512 * MIB
    max_artifacts_per_run: int = 200
    max_materialized_bytes_per_run: int = 500 * MIB
    max_artifacts_per_tenant: int = 20_000
    max_materialized_bytes_per_tenant: int = 50 * 1024 * MIB
    max_artifacts_per_class: int = 10_000
    max_materialized_bytes_per_class: int = 20 * 1024 * MIB
    max_context_artifact_refs: int = 12
    max_context_loaded_bytes: int = 4 * MIB
    max_context_loaded_tokens: int = 1_048_576
    dedup_scope: GraphArtifactDedupScope = (
        GraphArtifactDedupScope.TENANT_CHECKSUM_MEDIA_TYPE
    )
    cache_default_ttl_seconds: int = 86_400
    quota_alert_threshold_basis_points: int = 8_000
    gc_backlog_alert_bytes: int = 1024 * MIB
    cache_stampede_miss_threshold: int = 25
    retention: GraphArtifactRetentionSettings = field(
        default_factory=GraphArtifactRetentionSettings
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "mode",
            enum_value(GraphArtifactRolloutMode, self.mode, "config.mode"),
        )
        policy_version = exact_reference(self.policy_version, "config.policy_version")
        readable = stable_tuple(
            self.readable_policy_versions,
            "config.readable_policy_versions",
            normalize=exact_reference,
            allow_empty=False,
        )
        if policy_version not in readable:
            raise result_error(
                GraphArtifactResultErrorCode.POLICY_VERSION_UNSUPPORTED,
                policy_version=policy_version,
            )
        object.__setattr__(self, "policy_version", policy_version)
        object.__setattr__(self, "readable_policy_versions", readable)
        bounds = (
            ("inline_max_bytes", 1, MIB),
            ("inline_max_depth", 1, 32),
            ("inline_max_keys", 1, 4_096),
            ("summary_max_bytes", 1, MIB),
            ("summary_max_tokens", 1, 262_144),
            ("sample_max_bytes", 1, 16 * MIB),
            ("max_artifact_bytes", 1_024, 512 * MIB),
            ("max_artifacts_per_run", 1, 100_000),
            ("max_materialized_bytes_per_run", 1_024, 100 * 1024 * MIB),
            ("max_artifacts_per_tenant", 1, 10_000_000),
            ("max_materialized_bytes_per_tenant", 1_024, 10 * 1024 * 1024 * MIB),
            ("max_artifacts_per_class", 1, 10_000_000),
            ("max_materialized_bytes_per_class", 1_024, 10 * 1024 * 1024 * MIB),
            ("max_context_artifact_refs", 1, 1_024),
            ("max_context_loaded_bytes", 1, 512 * MIB),
            ("max_context_loaded_tokens", 1, 134_217_728),
            ("cache_default_ttl_seconds", 60, 2_592_000),
            ("quota_alert_threshold_basis_points", 1, 10_000),
            ("gc_backlog_alert_bytes", 1, 10 * 1024 * 1024 * MIB),
            ("cache_stampede_miss_threshold", 2, 1_000_000),
        )
        for field_name, minimum, maximum in bounds:
            object.__setattr__(
                self,
                field_name,
                bounded_int(
                    getattr(self, field_name),
                    f"config.{field_name}",
                    minimum=minimum,
                    maximum=maximum,
                ),
            )
        if self.summary_max_bytes > self.inline_max_bytes:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="config.summary_max_bytes",
            )
        if self.sample_max_bytes < self.summary_max_bytes:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="config.sample_max_bytes",
            )
        if (
            self.max_artifacts_per_run > self.max_artifacts_per_tenant
            or self.max_artifacts_per_class > self.max_artifacts_per_tenant
            or self.max_materialized_bytes_per_run
            > self.max_materialized_bytes_per_tenant
            or self.max_materialized_bytes_per_class
            > self.max_materialized_bytes_per_tenant
        ):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="config.aggregate_quota",
            )
        object.__setattr__(
            self,
            "dedup_scope",
            enum_value(
                GraphArtifactDedupScope,
                self.dedup_scope,
                "config.dedup_scope",
            ),
        )
        if not isinstance(self.retention, GraphArtifactRetentionSettings):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="config.retention",
            )

    def ensure_readable_policy_version(self, value: str) -> str:
        version = exact_reference(value, "policy_version")
        if version not in self.readable_policy_versions:
            raise result_error(
                GraphArtifactResultErrorCode.POLICY_VERSION_UNSUPPORTED,
                policy_version=version,
            )
        return version

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "policy_version": self.policy_version,
            "readable_policy_versions": list(self.readable_policy_versions),
            "inline_max_bytes": self.inline_max_bytes,
            "inline_max_depth": self.inline_max_depth,
            "inline_max_keys": self.inline_max_keys,
            "summary_max_bytes": self.summary_max_bytes,
            "summary_max_tokens": self.summary_max_tokens,
            "sample_max_bytes": self.sample_max_bytes,
            "max_artifact_bytes": self.max_artifact_bytes,
            "max_artifacts_per_run": self.max_artifacts_per_run,
            "max_materialized_bytes_per_run": self.max_materialized_bytes_per_run,
            "max_artifacts_per_tenant": self.max_artifacts_per_tenant,
            "max_materialized_bytes_per_tenant": self.max_materialized_bytes_per_tenant,
            "max_artifacts_per_class": self.max_artifacts_per_class,
            "max_materialized_bytes_per_class": self.max_materialized_bytes_per_class,
            "max_context_artifact_refs": self.max_context_artifact_refs,
            "max_context_loaded_bytes": self.max_context_loaded_bytes,
            "max_context_loaded_tokens": self.max_context_loaded_tokens,
            "dedup_scope": self.dedup_scope.value,
            "cache_default_ttl_seconds": self.cache_default_ttl_seconds,
            "quota_alert_threshold_basis_points": self.quota_alert_threshold_basis_points,
            "gc_backlog_alert_bytes": self.gc_backlog_alert_bytes,
            "cache_stampede_miss_threshold": self.cache_stampede_miss_threshold,
            "retention": self.retention.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "mode",
                    "policy_version",
                    "readable_policy_versions",
                    "inline_max_bytes",
                    "inline_max_depth",
                    "inline_max_keys",
                    "summary_max_bytes",
                    "summary_max_tokens",
                    "sample_max_bytes",
                    "max_artifact_bytes",
                    "max_artifacts_per_run",
                    "max_materialized_bytes_per_run",
                    "max_artifacts_per_tenant",
                    "max_materialized_bytes_per_tenant",
                    "max_artifacts_per_class",
                    "max_materialized_bytes_per_class",
                    "max_context_artifact_refs",
                    "max_context_loaded_bytes",
                    "max_context_loaded_tokens",
                    "dedup_scope",
                    "cache_default_ttl_seconds",
                    "quota_alert_threshold_basis_points",
                    "gc_backlog_alert_bytes",
                    "cache_stampede_miss_threshold",
                    "retention",
                }
            ),
            model=cls.__name__,
        )
        payload["readable_policy_versions"] = tuple(
            payload["readable_policy_versions"]
        )
        payload["retention"] = GraphArtifactRetentionSettings.from_dict(
            payload["retention"]
        )
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class PersistenceBudgetSnapshot:
    materialized_bytes: int = 0
    artifact_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "materialized_bytes",
            non_negative_int(self.materialized_bytes, "budget.materialized_bytes"),
        )
        object.__setattr__(
            self,
            "artifact_count",
            non_negative_int(self.artifact_count, "budget.artifact_count"),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "materialized_bytes": self.materialized_bytes,
            "artifact_count": self.artifact_count,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        return cls(
            **exact_keys(
                value,
                required=frozenset({"materialized_bytes", "artifact_count"}),
                model=cls.__name__,
            )
        )


@dataclass(frozen=True, slots=True)
class NodeResultRequest:
    binding: NodeResultBinding
    status: NodeResultStatus
    output_schema_ref: str
    output_schema_digest: str
    candidate: Any = field(repr=False, compare=False)
    media_type: str
    summary: BoundedSummary
    inline_projection: Mapping[str, Any]
    inline_allowed_fields: tuple[str, ...]
    provenance: ResultProvenance
    artifact_class: ArtifactClass
    retention_class: RetentionClass
    sensitivity: ResultSensitivity
    required_for_replay: bool
    required_for_publication: bool
    reusable: bool
    side_effect_free: bool
    dependency_digest: str | None
    context_policy: ContextPolicy
    created_at: datetime
    candidate_checksum: str = field(init=False)
    candidate_bytes: int = field(init=False)
    candidate_tokens: int = field(init=False)
    inline_bytes: int = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.binding, NodeResultBinding):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="binding",
            )
        object.__setattr__(
            self,
            "status",
            enum_value(NodeResultStatus, self.status, "status"),
        )
        object.__setattr__(
            self,
            "output_schema_ref",
            exact_reference(self.output_schema_ref, "output_schema_ref"),
        )
        object.__setattr__(
            self,
            "output_schema_digest",
            checksum(self.output_schema_digest, "output_schema_digest"),
        )
        normalized_media_type = media_type(self.media_type)
        canonical_candidate, candidate_bytes = serialize_candidate(
            self.candidate,
            normalized_media_type,
        )
        object.__setattr__(self, "media_type", normalized_media_type)
        object.__setattr__(self, "candidate", canonical_candidate)
        object.__setattr__(self, "candidate_checksum", sha256_checksum(candidate_bytes))
        object.__setattr__(self, "candidate_bytes", len(candidate_bytes))
        object.__setattr__(self, "candidate_tokens", estimated_tokens(len(candidate_bytes)))
        if not isinstance(self.summary, BoundedSummary):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="summary",
            )
        allowed_fields = stable_tuple(
            self.inline_allowed_fields,
            "inline_allowed_fields",
            normalize=lambda value, field_name: optional_text(
                value,
                field_name,
                max_length=128,
            ),
        )
        if any(value is None for value in allowed_fields):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="inline_allowed_fields",
            )
        normalized_allowed = tuple(value for value in allowed_fields if value is not None)
        object.__setattr__(self, "inline_allowed_fields", normalized_allowed)
        projection = canonical_mapping(
            self.inline_projection,
            "inline_projection",
            max_depth=32,
            max_keys=4_096,
            max_bytes=MIB,
            allowed_root_fields=frozenset(normalized_allowed),
        )
        object.__setattr__(self, "inline_projection", projection)
        object.__setattr__(self, "inline_bytes", len(canonical_json_bytes(projection)))
        if not isinstance(self.provenance, ResultProvenance):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="provenance",
            )
        object.__setattr__(
            self,
            "artifact_class",
            enum_value(ArtifactClass, self.artifact_class, "artifact_class"),
        )
        object.__setattr__(
            self,
            "retention_class",
            enum_value(RetentionClass, self.retention_class, "retention_class"),
        )
        object.__setattr__(
            self,
            "sensitivity",
            enum_value(ResultSensitivity, self.sensitivity, "sensitivity"),
        )
        for field_name in (
            "required_for_replay",
            "required_for_publication",
            "reusable",
            "side_effect_free",
        ):
            object.__setattr__(
                self,
                field_name,
                boolean(getattr(self, field_name), field_name),
            )
        dependency = self.dependency_digest
        if dependency is not None:
            dependency = checksum(dependency, "dependency_digest")
        if self.reusable and (not self.side_effect_free or dependency is None):
            raise result_error(
                GraphArtifactResultErrorCode.CACHE_IDENTITY_INVALID,
                field="dependency_digest",
            )
        object.__setattr__(self, "dependency_digest", dependency)
        object.__setattr__(
            self,
            "context_policy",
            enum_value(ContextPolicy, self.context_policy, "context_policy"),
        )
        object.__setattr__(self, "created_at", aware_datetime(self.created_at, "created_at"))

    @property
    def required(self) -> bool:
        return (
            self.required_for_replay
            or self.required_for_publication
            or self.artifact_class
            in {
                ArtifactClass.EVIDENCE,
                ArtifactClass.TRANSCRIPT,
                ArtifactClass.REPORT,
            }
        )

    def decision_projection(self) -> dict[str, Any]:
        return {
            "binding": self.binding.to_dict(),
            "status": self.status.value,
            "output_schema_ref": self.output_schema_ref,
            "output_schema_digest": self.output_schema_digest,
            "candidate_checksum": self.candidate_checksum,
            "candidate_bytes": self.candidate_bytes,
            "candidate_tokens": self.candidate_tokens,
            "media_type": self.media_type,
            "summary": self.summary.to_dict(),
            "inline_projection": thaw_mapping(self.inline_projection),
            "inline_allowed_fields": list(self.inline_allowed_fields),
            "provenance": self.provenance.to_dict(),
            "artifact_class": self.artifact_class.value,
            "retention_class": self.retention_class.value,
            "sensitivity": self.sensitivity.value,
            "required_for_replay": self.required_for_replay,
            "required_for_publication": self.required_for_publication,
            "reusable": self.reusable,
            "side_effect_free": self.side_effect_free,
            "dependency_digest": self.dependency_digest,
            "context_policy": self.context_policy.value,
            "created_at": datetime_to_json(self.created_at),
        }


@dataclass(frozen=True, slots=True)
class PersistenceEvaluation:
    candidate_checksum: str
    candidate_bytes: int
    candidate_tokens: int
    decision: PersistenceDecision

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_checksum",
            checksum(self.candidate_checksum, "candidate_checksum"),
        )
        object.__setattr__(
            self,
            "candidate_bytes",
            non_negative_int(self.candidate_bytes, "candidate_bytes"),
        )
        object.__setattr__(
            self,
            "candidate_tokens",
            non_negative_int(self.candidate_tokens, "candidate_tokens"),
        )
        if not isinstance(self.decision, PersistenceDecision):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="decision",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_checksum": self.candidate_checksum,
            "candidate_bytes": self.candidate_bytes,
            "candidate_tokens": self.candidate_tokens,
            "decision": self.decision.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "candidate_checksum",
                    "candidate_bytes",
                    "candidate_tokens",
                    "decision",
                }
            ),
            model=cls.__name__,
        )
        return cls(
            candidate_checksum=payload["candidate_checksum"],
            candidate_bytes=payload["candidate_bytes"],
            candidate_tokens=payload["candidate_tokens"],
            decision=PersistenceDecision.from_dict(payload["decision"]),
        )


class PersistencePolicy:
    """Pure tier selection; it has no writer, store, clock, or event dependency."""

    def __init__(self, config: GraphArtifactPersistenceConfig) -> None:
        if not isinstance(config, GraphArtifactPersistenceConfig):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="config",
            )
        self._config = config

    @property
    def config(self) -> GraphArtifactPersistenceConfig:
        return self._config

    def evaluate(
        self,
        request: NodeResultRequest,
        *,
        budget: PersistenceBudgetSnapshot | None = None,
    ) -> PersistenceEvaluation:
        if not isinstance(request, NodeResultRequest):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="request",
            )
        actual_budget = budget or PersistenceBudgetSnapshot()
        if not isinstance(actual_budget, PersistenceBudgetSnapshot):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="budget",
            )
        self._validate_bounds(request)
        mode, reason = self._select_tier(request, actual_budget)
        reserved_bytes = (
            request.candidate_bytes
            if mode in {PersistenceMode.ARTIFACT, PersistenceMode.CACHE}
            else 0
        )
        decision = PersistenceDecision(
            mode=mode,
            reason=reason,
            artifact_class=request.artifact_class,
            retention_class=(
                RetentionClass.CACHE
                if mode is PersistenceMode.CACHE
                else request.retention_class
            ),
            estimated_bytes=request.candidate_bytes,
            reserved_bytes=reserved_bytes,
            context_policy=request.context_policy,
            required=request.required,
            policy_version=self._config.policy_version,
        )
        return PersistenceEvaluation(
            candidate_checksum=request.candidate_checksum,
            candidate_bytes=request.candidate_bytes,
            candidate_tokens=request.candidate_tokens,
            decision=decision,
        )

    def _validate_bounds(self, request: NodeResultRequest) -> None:
        config = self._config
        if request.sensitivity is ResultSensitivity.SECRET:
            raise result_error(
                GraphArtifactResultErrorCode.SENSITIVE_PAYLOAD_REJECTED,
                field="sensitivity",
            )
        if request.candidate_bytes > config.max_artifact_bytes:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_TOO_LARGE,
                field="candidate",
                actual=request.candidate_bytes,
                limit=config.max_artifact_bytes,
            )
        if (
            request.summary.byte_size > config.summary_max_bytes
            or request.summary.token_estimate > config.summary_max_tokens
        ):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_TOO_LARGE,
                field="summary",
            )
        canonical_mapping(
            request.inline_projection,
            "inline_projection",
            max_depth=config.inline_max_depth,
            max_keys=config.inline_max_keys,
            max_bytes=config.inline_max_bytes,
            allowed_root_fields=frozenset(request.inline_allowed_fields),
        )

    def _select_tier(
        self,
        request: NodeResultRequest,
        budget: PersistenceBudgetSnapshot,
    ) -> tuple[PersistenceMode, PersistenceReason]:
        forced_reason = _forced_artifact_reason(request)
        if forced_reason is not None:
            self._require_quota(request, budget)
            return PersistenceMode.ARTIFACT, forced_reason
        if request.sensitivity is ResultSensitivity.RESTRICTED:
            if self._fits_quota(request, budget):
                return PersistenceMode.ARTIFACT, PersistenceReason.LARGE_PAYLOAD
            return self._quota_outcome(request)
        if request.reusable:
            if self._fits_quota(request, budget):
                return (
                    PersistenceMode.CACHE,
                    PersistenceReason.REUSABLE_DETERMINISTIC_RESULT,
                )
            return self._quota_outcome(request)
        if (
            request.candidate_bytes <= self._config.inline_max_bytes
            and request.inline_bytes <= self._config.inline_max_bytes
        ):
            return (
                PersistenceMode.INLINE,
                PersistenceReason.BELOW_INLINE_THRESHOLD,
            )
        if self._fits_quota(request, budget):
            return PersistenceMode.ARTIFACT, PersistenceReason.LARGE_PAYLOAD
        return self._quota_outcome(request)

    def _fits_quota(
        self,
        request: NodeResultRequest,
        budget: PersistenceBudgetSnapshot,
    ) -> bool:
        return (
            budget.artifact_count < self._config.max_artifacts_per_run
            and budget.materialized_bytes + request.candidate_bytes
            <= self._config.max_materialized_bytes_per_run
        )

    def _require_quota(
        self,
        request: NodeResultRequest,
        budget: PersistenceBudgetSnapshot,
    ) -> None:
        if not self._fits_quota(request, budget):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_QUOTA_EXCEEDED,
                artifact_class=request.artifact_class.value,
                required=True,
            )

    def _quota_outcome(
        self,
        request: NodeResultRequest,
    ) -> tuple[PersistenceMode, PersistenceReason]:
        if request.required:
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_QUOTA_EXCEEDED,
                artifact_class=request.artifact_class.value,
                required=True,
            )
        return PersistenceMode.OMITTED, PersistenceReason.QUOTA_EXCEEDED


def _forced_artifact_reason(
    request: NodeResultRequest,
) -> PersistenceReason | None:
    if request.artifact_class is ArtifactClass.EVIDENCE:
        return PersistenceReason.REQUIRED_EVIDENCE
    if request.artifact_class is ArtifactClass.TRANSCRIPT:
        return PersistenceReason.REQUIRED_TRANSCRIPT
    if request.artifact_class is ArtifactClass.REPORT:
        return PersistenceReason.REQUIRED_REPORT
    if request.required_for_publication:
        return PersistenceReason.REQUIRED_FOR_PUBLICATION
    if request.required_for_replay:
        return PersistenceReason.REQUIRED_FOR_REPLAY
    return None


__all__ = [
    "DEFAULT_GRAPH_ARTIFACT_POLICY_VERSION",
    "GraphArtifactDedupScope",
    "GraphArtifactPersistenceConfig",
    "GraphArtifactRetentionSettings",
    "GraphArtifactRolloutMode",
    "NodeResultRequest",
    "PersistenceBudgetSnapshot",
    "PersistenceEvaluation",
    "PersistencePolicy",
]
